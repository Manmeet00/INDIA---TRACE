"""Provider adapters and persistence for road intelligence.

Search results are evidence candidates, never verified road closures. Location is
left unknown unless a structured coordinate is available from a trusted source.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import re
import sqlite3
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import certifi

from fastapi import HTTPException

from .config import get_settings
from .database import get_connection
from .evidence import annotate


def _request_json(url: str, headers: dict[str, str] | None = None, body: Any = None, timeout: float = 15) -> Any:
    """GET, or POST a JSON body; provider failures become 502 errors."""
    headers = {"User-Agent": get_settings().geocoder_user_agent, **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"An external routing or search service is unavailable: {exc}") from exc


GEOCODE_CACHE_S = 30 * 86400
ROUTE_CACHE_S = 86400
HIGHWAY_REF = re.compile(r"NH\s*-?\s*0*(\d{1,3}[A-Z]?)", re.IGNORECASE)
MIN_HIGHWAY_M = 2000


def _cached_json(url: str, max_age_s: float) -> tuple[Any, str]:
    """Provider response and when it was fetched; serves an older copy if the provider fails.

    Road geometry and place coordinates change slowly, and the public OSRM and Nominatim
    services are rate-limited and sometimes slow, so successful responses are kept in SQLite.
    """
    with get_connection() as connection:
        row = connection.execute("SELECT response, fetched_at FROM provider_cache WHERE url = ?", (url,)).fetchone()
    if row and _age_seconds(row["fetched_at"]) <= max_age_s:
        return json.loads(row["response"]), row["fetched_at"]
    try:
        data = _request_json(url)
    except HTTPException:
        if row:
            return json.loads(row["response"]), row["fetched_at"]
        raise
    fetched_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        connection.execute("INSERT OR REPLACE INTO provider_cache (url, response, fetched_at) VALUES (?, ?, ?)",
                           (url, json.dumps(data), fetched_at))
    return data, fetched_at


def _route_highways(route: dict[str, Any]) -> dict[str, int]:
    """National highways the route uses, with metres driven on each (short crossings ignored)."""
    metres: dict[str, float] = {}
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            for number in HIGHWAY_REF.findall(step.get("ref") or ""):
                key = f"NH-{number.upper()}"
                metres[key] = metres.get(key, 0) + step.get("distance", 0)
    return {key: round(value) for key, value in sorted(metres.items()) if value >= MIN_HIGHWAY_M}


def _geocode(place: str) -> dict[str, Any]:
    query = urlencode({"q": f"{place}, India", "format": "jsonv2", "limit": 1, "countrycodes": "in"})
    results, _ = _cached_json(f"https://nominatim.openstreetmap.org/search?{query}", GEOCODE_CACHE_S)
    if not results:
        raise HTTPException(status_code=422, detail=f"Could not find '{place}' in India. Try a more specific place name.")
    item = results[0]
    return {"name": item.get("display_name", place), "latitude": float(item["lat"]), "longitude": float(item["lon"])}


def plan_route(payload) -> dict[str, Any]:
    origin, destination = _geocode(payload.origin), _geocode(payload.destination)
    coordinates = f"{origin['longitude']},{origin['latitude']};{destination['longitude']},{destination['latitude']}"
    routes, routing_fetched_at = _cached_json(
        f"https://router.project-osrm.org/route/v1/driving/{coordinates}?{urlencode({'overview':'full','geometries':'geojson','alternatives':'3','steps':'true'})}",
        ROUTE_CACHE_S,
    )
    if routes.get("code") != "Ok" or not routes.get("routes"):
        raise HTTPException(status_code=422, detail="The routing service could not find a drivable route between these places.")
    with get_connection() as connection:
        incident_rows = connection.execute("SELECT * FROM incidents").fetchall()
    incident_items = annotate([incident_from_row(row) for row in incident_rows])
    candidates = []
    for index, route in enumerate(routes["routes"]):
        highways = _route_highways(route)
        candidates.append({
            "id": f"route-{index + 1}",
            "distance_m": round(route["distance"]),
            "duration_s": round(route["duration"]),
            "geometry": route["geometry"],
            "highways": highways,
            "priority_rank": index + 1,
            "vehicle_suitability": "unknown",
            "exposure": route_exposure(route["geometry"], incident_items, highways),
        })
    if payload.priority == "fastest":
        candidates.sort(key=lambda r: r["duration_s"])
    elif payload.priority == "shortest":
        candidates.sort(key=lambda r: r["distance_m"])
    elif payload.priority == "cautious":
        candidates.sort(key=lambda r: (r["exposure"]["nearby"]["confirmed"], _unconfirmed_nearby(r["exposure"]),
                                       len(r["exposure"]["highway_mentions"]), r["duration_s"]))
    for index, route in enumerate(candidates):
        route["priority_rank"] = index + 1
    newest_collection = max((item["collected_at"] for item in incident_items), default=None)
    incidents_by_id = {item["id"]: item for item in incident_items}
    for route in candidates:
        route["recommendation"], route["recommendation_reasons"] = recommend(route, candidates, newest_collection)
        route["impact_reports"] = impact_reports(route["exposure"], incidents_by_id)
        route["coverage"] = route_coverage(route["highways"], incident_items)
    return {
        "origin": origin,
        "destination": destination,
        "vehicle_type": payload.vehicle_type,
        "priority": payload.priority,
        "provider": "OpenStreetMap Nominatim + OSRM",
        "routing_fetched_at": routing_fetched_at,
        "routes": candidates,
        "recommendation": candidates[0]["recommendation"],
        "recommendation_reason": " ".join(candidates[0]["recommendation_reasons"]),
        "data_note": "Distance and duration are OSRM estimates without live traffic. They do not include verified disruption or vehicle restriction data.",
        "impact_note": IMPACT_NOTE,
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


def incident_from_row(row: sqlite3.Row) -> dict[str, Any]:
    published, approximate = parse_published(row["published_at"], row["collected_at"])
    return {
        "id": row["id"], "title": row["title"], "summary": row["summary"],
        "source_name": row["source_name"], "source_url": row["source_url"],
        "published_at": row["published_at"], "collected_at": row["collected_at"],
        "published_estimate": published, "published_approximate": approximate,
        "latitude": row["latitude"], "longitude": row["longitude"],
        "location_text": row["location_text"], "verification": row["verification"],
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
        # Provenance: which TinyFish search found the report, and what TinyFish Fetch read from its page.
        **{key: row[key] for key in ("publisher", "search_query", "search_kind", "last_seen_at", "published_source",
                                     "page_description", "page_excerpt", "page_author", "fetched_at", "fetch_error")},
    }


def load_incidents(connection: sqlite3.Connection, limit: int = 500) -> list[dict[str, Any]]:
    """Newest reports first, with duplicate, conflict and mention hints computed across them."""
    rows = connection.execute("SELECT * FROM incidents ORDER BY collected_at DESC LIMIT ?", (limit,)).fetchall()
    incidents = [incident_from_row(row) for row in rows]
    history: dict[str, list[dict[str, Any]]] = {}
    for review in connection.execute("SELECT * FROM incident_reviews ORDER BY reviewed_at DESC").fetchall():
        history.setdefault(review["incident_id"], []).append({
            key: review[key] for key in ("previous_verification", "verification", "review_note", "location_changed",
                                         "location_text", "latitude", "longitude", "reviewed_at")})
    flags: dict[str, list[dict[str, Any]]] = {}
    for flag in connection.execute("SELECT * FROM incident_flags WHERE resolved_at IS NULL ORDER BY created_at DESC").fetchall():
        flags.setdefault(flag["incident_id"], []).append({key: flag[key] for key in ("reason", "note", "created_at")})
    for incident in incidents:
        incident["review_history"] = history.get(incident["id"], [])
        incident["open_flags"] = flags.get(incident["id"], [])
    return annotate(incidents)


MATCH_TOLERANCE_M = 3000
EVIDENCE_MAX_AGE_S = 24 * 3600
# Reports a reviewer has dismissed as irrelevant or marked resolved by an authoritative update.
INACTIVE_STATES = {"dismissed", "resolved"}
VEHICLE_NOTE = "Vehicle restrictions such as weight, height and ghat-road limits are not checked."


def route_exposure(route_geometry: dict[str, Any], incidents: list[dict[str, Any]], highways: dict[str, int] | None = None,
                   tolerance_m: float = MATCH_TOLERANCE_M) -> dict[str, Any]:
    """Count reviewer-located reports near a route by verification state.

    Reports without coordinates are never matched by distance. Those that name a national
    highway the route uses are listed under highway_mentions as low-confidence relevance;
    the rest only count as unlocated. Dismissed reports are ignored.
    """
    relevant = [item for item in incidents if item["verification"] not in INACTIVE_STATES]
    located = [item for item in relevant if item.get("latitude") is not None and item.get("longitude") is not None]
    located_ids = {item["id"] for item in located}
    unlocated = [item for item in relevant if item["id"] not in located_ids]
    highway_mentions = {highway: [item["id"] for item in unlocated if highway in item.get("mentions", {}).get("highways", [])]
                        for highway in highways or {}}
    highway_mentions = {highway: ids for highway, ids in highway_mentions.items() if ids}
    mention_ids = list(dict.fromkeys(incident_id for ids in highway_mentions.values() for incident_id in ids))
    exposure: dict[str, Any] = {
        "tolerance_m": tolerance_m,
        "located_reports": len(located),
        "unlocated_reports": len(unlocated),
        "nearby": {"confirmed": 0, "unverified": 0, "conflicting": 0, "unknown": 0},
        "nearby_stale": 0,
        "nearby_confirmed_stale": 0,
        "nearby_ids": [],
        "nearby_distances": {},
        "highway_mentions": highway_mentions,
        "highway_mention_ids": mention_ids,
        "highway_mentions_stale": sum(item["freshness"] == "stale" for item in unlocated if item["id"] in mention_ids),
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
        distance = _distance_to_line(px, py, xy)
        if distance > tolerance_m:
            continue
        exposure["nearby_distances"][incident["id"]] = round(distance)
        state = incident["verification"]
        exposure["nearby"][state] = exposure["nearby"].get(state, 0) + 1
        exposure["nearby_stale"] += incident["freshness"] == "stale"
        exposure["nearby_confirmed_stale"] += state == "confirmed" and incident["freshness"] == "stale"
        exposure["nearby_ids"].append(incident["id"])
    return exposure


IMPACT_NOTE = ("The relevance score orders reports for review: location up to 50, freshness 20, evidence 20, "
               "event severity 10. It is not a probability that the road is blocked.")
SEVERITY_POINTS = {"closure": 10, "landslide": 10, "bridge": 10, "flood": 8, "accident": 6, "construction": 4, "weather": 3}


def impact_reports(exposure: dict[str, Any], incidents_by_id: dict[str, dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """Reports that may affect a route, each with a relevance score and the reasons behind it (report 6.6)."""
    matches = [(incident_id, "precise") for incident_id in exposure["nearby_ids"]]
    matches += [(incident_id, "road") for incident_id in exposure["highway_mention_ids"]]
    scored = []
    for incident_id, match in matches:
        item = incidents_by_id[incident_id]
        if match == "precise":
            distance = exposure["nearby_distances"][incident_id]
            location = 30 + round(20 * (1 - distance / exposure["tolerance_m"]))
            where = f"{distance / 1000:.1f} km from the route (reviewer-confirmed location)"
        else:
            distance, location = None, 12
            roads = ", ".join(road for road, ids in exposure["highway_mentions"].items() if incident_id in ids)
            where = f"Names {roads}, which this route uses; where on the road is not known"
        window = item["freshness_window_h"]
        timing, fresh_points = {
            "fresh": (f"Published within the {window} h window for {item['event_type']} reports", 20),
            "stale": (f"Published more than {window} h ago ({item['event_type']} window); may be outdated", 0),
        }.get(item["freshness"], ("Publication time unknown", 8))
        if item["verification"] == "confirmed":
            evidence = 20
        elif item["corroborating_ids"]:
            evidence = 15
        elif item["verification"] == "conflicting" or item["conflict_ids"]:
            evidence = 8
        else:
            evidence = 3 if item["verification"] == "unknown" else 5
        scored.append({
            "id": incident_id, "title": item["title"], "source_name": item["source_name"], "source_url": item["source_url"],
            "published_at": item["published_at"], "evidence_status": item["evidence_status"], "event_type": item["event_type"],
            "match": match, "distance_m": distance,
            "score": location + fresh_points + evidence + SEVERITY_POINTS.get(item["event_type"], 2),
            "factors": [where, timing, f"Evidence: {item['evidence_status']}", f"Event type: {item['event_type']}"],
        })
    return sorted(scored, key=lambda report: -report["score"])[:limit]


def route_coverage(highways: dict[str, int], incidents: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-highway report counts, so missing reports show as a coverage gap rather than a clear road."""
    active = [item for item in incidents if item["verification"] not in INACTIVE_STATES]
    rows = []
    for highway, metres in highways.items():
        reports = [item for item in active if highway in item["mentions"]["highways"]]
        rows.append({"highway": highway, "km": round(metres / 1000), "reports": len(reports),
                     "fresh": sum(item["freshness"] == "fresh" for item in reports)})
    gaps = [row for row in rows if not row["fresh"]]
    if not rows:
        note = "The routing service named no national highways on this route, so highway coverage is unknown."
    elif gaps:
        note = ("No reports within their freshness window for " + ", ".join(f"{row['highway']} ({row['km']} km)" for row in gaps)
                + ". This is a coverage gap, not evidence that the road is clear.")
    else:
        note = "Every national highway on this route has at least one recent report; review them before dispatch."
    return {"highways": rows, "note": note}


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
        old = exposure["nearby_confirmed_stale"]
        reasons = [f"{_plural(confirmed, 'reviewer-confirmed report')} within {km} of this route"
                   f"{f' ({old} published over 24 hours ago; check it is still current)' if old else ''}."]
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
    mentioned = len(exposure["highway_mention_ids"])
    if mentioned:
        stale = exposure["highway_mentions_stale"]
        reasons.append(f"{_plural(mentioned, 'report')} without a confirmed location {'mentions' if mentioned == 1 else 'mention'} "
                       f"{', '.join(exposure['highway_mentions'])}, which this route uses"
                       f"{f' ({stale} older than 24 hours)' if stale else ''}. Where on the road is not known.")
    other_unlocated = exposure["unlocated_reports"] - mentioned
    if other_unlocated:
        reasons.append(f"{_plural(other_unlocated, 'other report' if mentioned else 'report')} {'has' if other_unlocated == 1 else 'have'} no reviewer-confirmed location, so exposure to them is unknown.")
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
