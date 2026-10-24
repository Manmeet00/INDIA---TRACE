"""Provider adapters and persistence for road intelligence.

Search results are evidence candidates, never verified road closures. Location is
left unknown unless a structured coordinate is available from a trusted source.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
import sqlite3
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4
import certifi

from fastapi import HTTPException

from .config import get_settings
from .database import get_connection
from .evidence import annotate, normalize_source_url


def _request_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request = Request(url, headers={"User-Agent": get_settings().geocoder_user_agent, **(headers or {})})
    try:
        with urlopen(request, timeout=15, context=ssl.create_default_context(cafile=certifi.where())) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"An external routing or search service is unavailable: {exc}") from exc


def _geocode(place: str) -> dict[str, Any]:
    query = urlencode({"q": f"{place}, India", "format": "jsonv2", "limit": 1, "countrycodes": "in"})
    results = _request_json(f"https://nominatim.openstreetmap.org/search?{query}")
    if not results:
        raise HTTPException(status_code=422, detail=f"Could not find '{place}' in India. Try a more specific place name.")
    item = results[0]
    return {"name": item.get("display_name", place), "latitude": float(item["lat"]), "longitude": float(item["lon"])}


def plan_route(payload) -> dict[str, Any]:
    origin, destination = _geocode(payload.origin), _geocode(payload.destination)
    coordinates = f"{origin['longitude']},{origin['latitude']};{destination['longitude']},{destination['latitude']}"
    routes = _request_json(
        f"https://router.project-osrm.org/route/v1/driving/{coordinates}?{urlencode({'overview':'full','geometries':'geojson','alternatives':'3','steps':'false'})}"
    )
    if routes.get("code") != "Ok" or not routes.get("routes"):
        raise HTTPException(status_code=422, detail="The routing service could not find a drivable route between these places.")
    with get_connection() as connection:
        incident_rows = connection.execute("SELECT * FROM incidents").fetchall()
    incident_items = [incident_from_row(row) for row in incident_rows]
    candidates = []
    for index, route in enumerate(routes["routes"]):
        candidates.append({
            "id": f"route-{index + 1}",
            "distance_m": round(route["distance"]),
            "duration_s": round(route["duration"]),
            "geometry": route["geometry"],
            "priority_rank": index + 1,
            "vehicle_suitability": "unknown",
            "exposure": route_exposure(route["geometry"], incident_items),
        })
    if payload.priority == "fastest":
        candidates.sort(key=lambda r: r["duration_s"])
    elif payload.priority == "shortest":
        candidates.sort(key=lambda r: r["distance_m"])
    elif payload.priority == "cautious":
        candidates.sort(key=lambda r: (r["exposure"]["nearby"]["confirmed"], _unconfirmed_nearby(r["exposure"]), r["duration_s"]))
    for index, route in enumerate(candidates):
        route["priority_rank"] = index + 1
    newest_collection = max((item["collected_at"] for item in incident_items), default=None)
    for route in candidates:
        route["recommendation"], route["recommendation_reasons"] = recommend(route, candidates, newest_collection)
    return {
        "origin": origin,
        "destination": destination,
        "vehicle_type": payload.vehicle_type,
        "priority": payload.priority,
        "provider": "OpenStreetMap Nominatim + OSRM",
        "routes": candidates,
        "recommendation": candidates[0]["recommendation"],
        "recommendation_reason": " ".join(candidates[0]["recommendation_reasons"]),
        "data_note": "Distance and duration are live OSRM estimates. They do not include verified disruption or vehicle restriction data.",
    }


RELATIVE_TIME = re.compile(r"^(\d+|an?|one)\s+(minute|hour|day|week|month|year)s?\s+ago$", re.IGNORECASE)
UNIT_SECONDS = {"minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def parse_published(text: str | None, collected_at: str) -> tuple[datetime | None, bool]:
    """Estimate when a source was published, and whether that estimate is approximate.

    Search results give ISO times, dates such as "Jul 3, 2023", or relative text such as
    "3 months ago", which is counted back from when the result was collected.
    """
    if not text:
        return None, False
    value = text.strip()
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00"))), len(value) <= 10
    except ValueError:
        pass
    match = RELATIVE_TIME.match(value)
    if match:
        amount = int(match[1]) if match[1].isdigit() else 1
        collected = _as_utc(datetime.fromisoformat(collected_at))
        return collected - timedelta(seconds=amount * UNIT_SECONDS[match[2].lower()]), True
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).replace(tzinfo=timezone.utc), True
        except ValueError:
            continue
    return None, False


def _freshness(published: datetime | None, approximate: bool) -> str:
    if published is None:
        return "unknown"
    age_seconds = (datetime.now(timezone.utc) - published).total_seconds()
    if age_seconds < 0:
        # A date-only value can be up to a day ahead of UTC (for example a date in IST).
        if not approximate or age_seconds < -86400:
            return "unknown"
        age_seconds = 0
    return "fresh" if age_seconds <= EVIDENCE_MAX_AGE_S else "stale"


def incident_from_row(row: sqlite3.Row) -> dict[str, Any]:
    published, approximate = parse_published(row["published_at"], row["collected_at"])
    return {
        "id": row["id"], "title": row["title"], "summary": row["summary"],
        "source_name": row["source_name"], "source_url": row["source_url"],
        "published_at": row["published_at"], "collected_at": row["collected_at"],
        "published_estimate": published, "published_approximate": approximate,
        "latitude": row["latitude"], "longitude": row["longitude"],
        "location_text": row["location_text"], "verification": row["verification"],
        "freshness": _freshness(published, approximate), "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
    }


def load_incidents(connection: sqlite3.Connection, limit: int = 500) -> list[dict[str, Any]]:
    """Newest reports first, with duplicate, conflict and mention hints computed across them."""
    rows = connection.execute("SELECT * FROM incidents ORDER BY collected_at DESC LIMIT ?", (limit,)).fetchall()
    return annotate([incident_from_row(row) for row in rows])


def collect_candidates(connection: sqlite3.Connection) -> dict[str, Any]:
    key = get_settings().tinyfish_api_key
    if not key:
        return {"status": "not_configured", "collected": 0, "duplicates": 0,
                "message": "TinyFish is not configured. Add TINYFISH_API_KEY to Backend/.env to collect public web evidence.", "incidents": []}
    queries = [
        "Northeast India road closure landslide highway official update",
        "Assam Arunachal road disruption bridge closure latest",
        "Manipur Mizoram Meghalaya road closure landslide update",
    ]
    collected = 0
    duplicates = 0
    failed_queries = 0
    now = datetime.now(timezone.utc).isoformat()
    for query in queries:
        try:
            response = _request_json(f"https://api.search.tinyfish.ai?{urlencode({'query': query})}", {"X-API-Key": key})
        except HTTPException:
            failed_queries += 1
            continue
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            failed_queries += 1
            continue
        for item in response["results"]:
            if not isinstance(item, dict):
                continue
            raw_url = item.get("url")
            if not isinstance(raw_url, str) or not raw_url.strip():
                continue
            source_url = raw_url.strip()
            if "://" not in source_url:
                source_url = f"https://{source_url.lstrip('/')}"
            parsed_url = urlsplit(source_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username or parsed_url.password:
                continue
            source_url = normalize_source_url(source_url)
            raw_title = item.get("title")
            raw_snippet = item.get("snippet")
            title = (raw_title.strip() if isinstance(raw_title, str) else "")[:300] or "Untitled public source"
            snippet = (raw_snippet.strip() if isinstance(raw_snippet, str) else "")[:3000]
            if not snippet:
                continue
            published_at = item.get("published_at") or item.get("date")
            if published_at and not isinstance(published_at, str):
                published_at = None
            elif isinstance(published_at, str):
                published_at = published_at.strip() or None
            raw_source_name = item.get("site_name")
            source_name = (raw_source_name.strip() if isinstance(raw_source_name, str) else "")[:200] or "Public web source"
            digest = sha256((title + snippet + source_url).encode()).hexdigest()
            try:
                connection.execute(
                    """INSERT INTO incidents
                    (id,title,summary,source_name,source_url,published_at,collected_at,location_text,verification,content_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"in_{uuid4().hex}", title, snippet, source_name, source_url,
                     published_at, now, None, "unverified", digest),
                )
                collected += 1
            except sqlite3.IntegrityError:
                if connection.execute("SELECT 1 FROM incidents WHERE source_url = ?", (source_url,)).fetchone():
                    duplicates += 1
                else:
                    raise
    if failed_queries == len(queries):
        raise HTTPException(status_code=502, detail="TinyFish could not return search results. Try again later.")
    status = "partial" if failed_queries else "complete"
    message = "Search results are unverified evidence candidates. Geographic location is unknown until independently confirmed."
    if failed_queries:
        message = f"{failed_queries} of {len(queries)} TinyFish searches failed. Partial results are shown. " + message
    return {"status": status, "collected": collected, "duplicates": duplicates,
            "message": message,
            "incidents": load_incidents(connection, 100)}


MATCH_TOLERANCE_M = 3000
EVIDENCE_MAX_AGE_S = 24 * 3600
VEHICLE_NOTE = "Vehicle restrictions such as weight, height and ghat-road limits are not checked."


def route_exposure(route_geometry: dict[str, Any], incidents: list[dict[str, Any]], tolerance_m: float = MATCH_TOLERANCE_M) -> dict[str, Any]:
    """Count reviewer-located reports near a route by verification state.

    Reports without coordinates are never matched; they are counted as unlocated so
    the recommendation can say exposure to them is unknown. Dismissed reports are ignored.
    """
    relevant = [item for item in incidents if item["verification"] != "dismissed"]
    located = [item for item in relevant if item.get("latitude") is not None and item.get("longitude") is not None]
    exposure: dict[str, Any] = {
        "tolerance_m": tolerance_m,
        "located_reports": len(located),
        "unlocated_reports": len(relevant) - len(located),
        "nearby": {"confirmed": 0, "unverified": 0, "conflicting": 0, "unknown": 0},
        "nearby_stale": 0,
        "nearby_ids": [],
    }
    line = route_geometry.get("coordinates", [])
    if len(line) < 2 or not located:
        return exposure
    # Equirectangular projection around the route's mean latitude; accurate enough at a few km.
    mean_lat = math.radians(sum(point[1] for point in line) / len(line))
    sx, sy = 111320 * math.cos(mean_lat), 111320
    xy = [(point[0] * sx, point[1] * sy) for point in line]
    min_x, max_x = min(x for x, _ in xy) - tolerance_m, max(x for x, _ in xy) + tolerance_m
    min_y, max_y = min(y for _, y in xy) - tolerance_m, max(y for _, y in xy) + tolerance_m
    for incident in located:
        px, py = incident["longitude"] * sx, incident["latitude"] * sy
        if not (min_x <= px <= max_x and min_y <= py <= max_y):
            continue
        if _distance_to_line(px, py, xy) > tolerance_m:
            continue
        state = incident["verification"]
        exposure["nearby"][state] = exposure["nearby"].get(state, 0) + 1
        exposure["nearby_stale"] += incident["freshness"] == "stale"
        exposure["nearby_ids"].append(incident["id"])
    return exposure


def _distance_to_line(px: float, py: float, xy: list[tuple[float, float]]) -> float:
    nearest = float("inf")
    for (ax, ay), (bx, by) in zip(xy, xy[1:]):
        dx, dy = bx - ax, by - ay
        fraction = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / max(dx*dx + dy*dy, 1e-9)))
        nearest = min(nearest, math.hypot(px - (ax + fraction*dx), py - (ay + fraction*dy)))
    return nearest


def _unconfirmed_nearby(exposure: dict[str, Any]) -> int:
    return sum(count for state, count in exposure["nearby"].items() if state != "confirmed")


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def recommend(route: dict[str, Any], routes: list[dict[str, Any]], newest_collection: str | None) -> tuple[str, list[str]]:
    """Explain one of: consider_alternative, verify_before_dispatch, proceed_cautiously.

    Never claims a road is clear; proceed_cautiously requires every relevant report to be located.
    """
    exposure = route["exposure"]
    km = f"{exposure['tolerance_m'] / 1000:g} km"
    confirmed = exposure["nearby"]["confirmed"]
    if confirmed:
        reasons = [f"{_plural(confirmed, 'reviewer-confirmed report')} within {km} of this route."]
        alternatives = [other for other in routes if other is not route and other["exposure"]["nearby"]["confirmed"] == 0]
        if alternatives:
            best = min(alternatives, key=lambda other: (_unconfirmed_nearby(other["exposure"]), other["duration_s"]))
            reasons.append(f"Route {best['priority_rank']} has no confirmed reports within {km}; check it before dispatch.")
            return "consider_alternative", reasons + [VEHICLE_NOTE]
        reasons.append("Every candidate route has confirmed reports nearby. Verify locally or delay dispatch.")
        return "verify_before_dispatch", reasons + [VEHICLE_NOTE]
    reasons = []
    unconfirmed = _unconfirmed_nearby(exposure)
    if unconfirmed:
        reasons.append(f"{_plural(unconfirmed, 'report')} within {km} of this route {'is' if unconfirmed == 1 else 'are'} not confirmed by a reviewer.")
    if exposure["unlocated_reports"]:
        reasons.append(f"{_plural(exposure['unlocated_reports'], 'report')} {'has' if exposure['unlocated_reports'] == 1 else 'have'} no reviewer-confirmed location, so exposure to them is unknown.")
    if newest_collection is None:
        reasons.append("No reports have been collected. No reports does not mean the road is clear.")
    elif _age_seconds(newest_collection) > EVIDENCE_MAX_AGE_S:
        reasons.append("The newest collected evidence is more than 24 hours old. Run collection again.")
    if reasons:
        return "verify_before_dispatch", reasons + [VEHICLE_NOTE]
    return "proceed_cautiously", [
        f"None of the {_plural(exposure['located_reports'], 'located report')} is within {km} of this route, and no relevant report lacks a location."
        if exposure["located_reports"] else "A reviewer dismissed every collected report as not relevant.",
        "This is not confirmation that the road is clear; reports can be missing or late.",
        VEHICLE_NOTE,
    ]


def _age_seconds(timestamp: str) -> float:
    return (datetime.now(timezone.utc) - _as_utc(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))).total_seconds()
