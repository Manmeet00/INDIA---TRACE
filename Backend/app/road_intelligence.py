"""Provider adapters and persistence for road intelligence.

Search results are evidence candidates, never verified road closures. Location is
left unknown unless a structured coordinate is available from a trusted source.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
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
        candidate_matches = route_exposure(route["geometry"], incident_items)
        candidates.append({
            "id": f"route-{index + 1}",
            "distance_m": round(route["distance"]),
            "duration_s": round(route["duration"]),
            "geometry": route["geometry"],
            "priority_rank": index + 1,
            "vehicle_suitability": "unknown",
            "disruption_exposure": "unknown" if candidate_matches is None else "unverified_candidate_reports",
            "candidate_report_matches": candidate_matches,
        })
    if payload.priority == "fastest":
        candidates.sort(key=lambda r: r["duration_s"])
    elif payload.priority == "shortest":
        candidates.sort(key=lambda r: r["distance_m"])
    elif payload.priority == "cautious" and all(route["candidate_report_matches"] is not None for route in candidates):
        candidates.sort(key=lambda r: r["candidate_report_matches"])
    for index, route in enumerate(candidates):
        route["priority_rank"] = index + 1
    return {
        "origin": origin,
        "destination": destination,
        "vehicle_type": payload.vehicle_type,
        "priority": payload.priority,
        "provider": "OpenStreetMap Nominatim + OSRM",
        "routes": candidates,
        "recommendation": "verify_before_dispatch",
        "recommendation_reason": "Search results are unverified and may have unknown locations; vehicle restrictions are not checked. Verify locally before dispatch.",
        "data_note": "Distance and duration are live OSRM estimates. They do not include verified disruption or vehicle restriction data.",
    }


def _freshness(published_at: str | None) -> str:
    if not published_at:
        return "unknown"
    try:
        value = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - value).total_seconds()
        if age_seconds < 0:
            return "unknown"
        return "fresh" if age_seconds <= 24 * 3600 else "stale"
    except (ValueError, TypeError):
        return "unknown"


def incident_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "title": row["title"], "summary": row["summary"],
        "source_name": row["source_name"], "source_url": row["source_url"],
        "published_at": row["published_at"], "collected_at": row["collected_at"],
        "latitude": row["latitude"], "longitude": row["longitude"],
        "location_text": row["location_text"], "verification": row["verification"],
        "freshness": _freshness(row["published_at"]), "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
    }


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
    rows = connection.execute("SELECT * FROM incidents ORDER BY collected_at DESC LIMIT 100").fetchall()
    status = "partial" if failed_queries else "complete"
    message = "Search results are unverified evidence candidates. Geographic location is unknown until independently confirmed."
    if failed_queries:
        message = f"{failed_queries} of {len(queries)} TinyFish searches failed. Partial results are shown. " + message
    return {"status": status, "collected": collected, "duplicates": duplicates,
            "message": message,
            "incidents": [incident_from_row(row) for row in rows]}


def route_exposure(route_geometry: dict[str, Any], incidents: list[dict[str, Any]], tolerance_m: float = 3000) -> int | None:
    """Return a count only when every candidate has coordinates; null means unknown."""
    if not incidents or any(item.get("latitude") is None or item.get("longitude") is None for item in incidents):
        return None
    line = route_geometry.get("coordinates", [])
    if len(line) < 2:
        return None
    # Great-circle approximation around the route midpoint for short segment matching.
    mean_lat = math.radians(sum(point[1] for point in line) / len(line))
    sx, sy = 111320 * math.cos(mean_lat), 111320
    count = 0
    xy = [(point[0] * sx, point[1] * sy) for point in line]
    for incident in incidents:
        px, py = incident["longitude"] * sx, incident["latitude"] * sy
        nearest = float("inf")
        for (ax, ay), (bx, by) in zip(xy, xy[1:]):
            dx, dy = bx - ax, by - ay
            fraction = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / max(dx*dx + dy*dy, 1e-9)))
            nearest = min(nearest, math.hypot(px - (ax + fraction*dx), py - (ay + fraction*dy)))
        count += nearest <= tolerance_m
    return count
