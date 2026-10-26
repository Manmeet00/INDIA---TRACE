"""Provider adapters and persistence for road intelligence.

Search results are evidence candidates, never verified road closures. Location is
left unknown unless a structured coordinate is available from a trusted source.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import http.client
import json
import logging
import math
import re
import sqlite3
import ssl
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import certifi

from fastapi import HTTPException

from .config import get_settings
from .database import get_connection
from . import google_routes
from .evidence import annotate
from .media import media_for
from .monitoring import log_call
from .tolls import tolls_on_route

logger = logging.getLogger("indiatrace")


def _request_json(url: str, headers: dict[str, str] | None = None, body: Any = None, timeout: float = 15) -> Any:
    """GET, or POST a JSON body; provider failures, timeouts and unreadable responses become 502 errors.

    Responses are asked for gzip-compressed: a route with its turn-by-turn steps is several hundred kilobytes,
    which takes far longer to download from the public servers than they take to compute it.
    """
    headers = {"User-Agent": get_settings().geocoder_user_agent, "Accept-Encoding": "gzip", **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
            body = response.read()
            if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
                body = gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
    # URLError, timeouts and dropped connections are OSErrors; a cut-off or non-JSON body raises IncompleteRead or
    # ValueError; a damaged gzip body raises BadGzipFile (an OSError) or EOFError.
    except (OSError, EOFError, http.client.HTTPException, ValueError) as exc:
        host = urlsplit(url).hostname
        timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
        reason = f"{host} did not answer within {timeout:g} s" if timed_out else f"{host}: {exc}{_error_message(exc)}"
        raise HTTPException(status_code=502, detail=f"An external routing or search service is unavailable ({reason}).") from exc


def _error_message(exc: Exception) -> str:
    """The provider's own explanation of an HTTP error ({"error": {"message": ...}}), such as an API not enabled."""
    if not isinstance(exc, HTTPError):
        return ""
    try:
        message = json.loads(exc.read().decode("utf-8"))["error"]["message"]
    except Exception:  # no readable explanation: the status line is enough
        return ""
    return f" — {str(message).split(chr(10))[0][:200]}"


GEOCODE_CACHE_S = 30 * 86400
ROUTE_CACHE_S = 86400
HIGHWAY_REF = re.compile(r"NH\s*-?\s*0*(\d{1,3}[A-Z]?)", re.IGNORECASE)
MIN_HIGHWAY_M = 2000


def _cached_json(url: str, max_age_s: float, valid: Callable[[Any], bool], body: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, stale_ok: bool = True) -> tuple[Any, str]:
    """Provider response and when it was fetched; serves an older copy if the provider fails (unless stale_ok
    is False, for answers such as live traffic that an old copy would misstate).

    Road geometry and place coordinates change slowly, and the public OSRM and Nominatim
    services are rate-limited and sometimes slow, so successful responses are kept in SQLite.
    A response that fails `valid` counts as a failure and is never cached. A POST body is part of the cache
    key; headers (which can carry an API key) are not stored.
    """
    service = ("nominatim" if "nominatim" in url else "photon" if "photon" in url
               else "open-meteo" if "open-meteo" in url else "google_routes" if "googleapis" in url else "osrm")
    key = f"{url}#{json.dumps(body, sort_keys=True)}" if body is not None else url
    with get_connection() as connection:
        row = connection.execute("SELECT response, fetched_at FROM provider_cache WHERE url = ?", (key,)).fetchone()
        if row and _age_seconds(row["fetched_at"]) <= max_age_s:
            log_call(connection, service, "cache")
            return json.loads(row["response"]), row["fetched_at"]
    started = time.monotonic()
    try:
        data = _request_json(url, headers, body) if body is not None or headers else _request_json(url)
        if not valid(data):
            raise HTTPException(status_code=502, detail=f"An external routing or search service is unavailable ({urlsplit(url).hostname} returned an unexpected response).")
    except HTTPException:
        with get_connection() as connection:
            log_call(connection, service, "stale_cache" if row and stale_ok else "failed", started)
        if row and stale_ok:
            return json.loads(row["response"]), row["fetched_at"]
        raise
    fetched_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        log_call(connection, service, "ok", started)
        connection.execute("INSERT OR REPLACE INTO provider_cache (url, response, fetched_at) VALUES (?, ?, ?)",
                           (key, json.dumps(data), fetched_at))
    return data, fetched_at


# How long saved provider answers are kept. Each must outlive its reuse window, plus a margin in which a stale
# copy can still stand in when the provider is down (Google traffic answers never are).
CACHE_KEEP_S = {"https://routes.googleapis.com": 3600, "https://router.project-osrm.org": 7 * 86400}
CACHE_KEEP_DEFAULT_S = 31 * 86400


def prune_provider_cache(connection: sqlite3.Connection) -> int:
    """Delete saved answers past their keeping time; returns how many. Routes from GPS positions are almost
    never asked for twice, so without this the cache grows by hundreds of kilobytes a plan."""
    now = datetime.now(timezone.utc)
    cutoff = lambda seconds: (now - timedelta(seconds=seconds)).isoformat()
    deleted = 0
    for prefix, seconds in CACHE_KEEP_S.items():
        deleted += connection.execute("DELETE FROM provider_cache WHERE url LIKE ? AND fetched_at < ?",
                                      (f"{prefix}%", cutoff(seconds))).rowcount
    deleted += connection.execute("DELETE FROM provider_cache WHERE fetched_at < ?", (cutoff(CACHE_KEEP_DEFAULT_S),)).rowcount
    return deleted


def _route_highways(route: dict[str, Any]) -> dict[str, int]:
    """National highways the route uses, with metres driven on each (short crossings ignored)."""
    metres: dict[str, float] = {}
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            for number in HIGHWAY_REF.findall(step.get("ref") or ""):
                key = f"NH-{number.upper()}"
                metres[key] = metres.get(key, 0) + step.get("distance", 0)
    return {key: round(value) for key, value in sorted(metres.items()) if value >= MIN_HIGHWAY_M}


def highway_spans(steps: list[dict[str, Any]], highways: dict[str, int]) -> dict[str, list[list[int]]]:
    """Where along the route (metres from the start) it runs on each of its national highways, from the road number
    of each step (OSRM's ref, or the road Google names). The dashboard marks these stretches for reports that name a
    highway but not a place on it."""
    spans: dict[str, list[list[float]]] = {}
    start = 0.0
    for step in steps:
        end = start + (step.get("distance_m") or 0)
        for number in set(HIGHWAY_REF.findall(step.get("ref") or step.get("name") or "")):
            key = f"NH-{number.upper()}"
            if key not in highways or end <= start:
                continue
            runs = spans.setdefault(key, [])
            if runs and start - runs[-1][1] < 1:
                runs[-1][1] = end  # the same highway continues from the step before
            else:
                runs.append([start, end])
        start = end
    return {key: [[round(a), round(b)] for a, b in runs] for key, runs in spans.items()}


def _route_steps(route: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn-by-turn steps for navigation, in order: what to do at each point and how far it is to the next one.

    OSRM's own fields are passed on (maneuver type and direction, road name and number, roundabout exit); the
    dashboard words them. A step without a usable maneuver location is left out rather than guessed.
    """
    steps = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            maneuver = step.get("maneuver") if isinstance(step, dict) else None
            location = maneuver.get("location") if isinstance(maneuver, dict) else None
            if not (isinstance(location, list) and len(location) >= 2 and _number(location[0]) and _number(location[1])):
                continue
            steps.append({
                "type": str(maneuver.get("type") or "continue"),
                "modifier": maneuver.get("modifier") if isinstance(maneuver.get("modifier"), str) else None,
                "exit": maneuver.get("exit") if isinstance(maneuver.get("exit"), int) else None,
                "bearing_after": maneuver.get("bearing_after") if _number(maneuver.get("bearing_after")) else None,
                "name": step.get("name") if isinstance(step.get("name"), str) else "",
                "ref": step.get("ref") if isinstance(step.get("ref"), str) else "",
                "distance_m": round(float(step.get("distance") or 0), 1) if _number(step.get("distance") or 0) else 0,
                "duration_s": round(float(step.get("duration") or 0), 1) if _number(step.get("duration") or 0) else 0,
                "location": [float(location[0]), float(location[1])],
            })
    return steps


def _number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _valid_geocode(data: Any) -> bool:
    """A list of places; the first one, if any, must carry numeric coordinates."""
    return isinstance(data, list) and (not data or (isinstance(data[0], dict) and _number(data[0].get("lat")) and _number(data[0].get("lon"))))


def _decode_polyline(encoded: str, precision: int = 6) -> list[list[float]]:
    """An encoded polyline (Google's format, as OSRM sends with geometries=polyline6) as [longitude, latitude] pairs."""
    coordinates, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat, lon = lat + deltas[0], lon + deltas[1]
        coordinates.append([lon / 10 ** precision, lat / 10 ** precision])
    return coordinates


def _route_line(geometry: Any) -> dict[str, Any]:
    """A route's line as GeoJSON, whether OSRM sent an encoded polyline or GeoJSON."""
    if isinstance(geometry, str):
        return {"type": "LineString", "coordinates": _decode_polyline(geometry)}
    return geometry


def _valid_routes(data: Any) -> bool:
    """OSRM's answer; when it reports routes, each needs a distance, a duration and a line geometry."""
    if not isinstance(data, dict):
        return False
    if data.get("code") != "Ok":
        return True  # NoRoute and similar are answers, handled by the caller.
    routes = data.get("routes")
    return isinstance(routes, list) and all(
        isinstance(route, dict) and _number(route.get("distance")) and _number(route.get("duration"))
        and _valid_line(route.get("geometry"))
        for route in routes)


def _valid_line(geometry: Any) -> bool:
    """At least two numeric points, from an encoded polyline or GeoJSON."""
    try:
        line = _route_line(geometry) if isinstance(geometry, (str, dict)) else None
    except (IndexError, TypeError):  # a cut-off polyline
        return False
    coordinates = line.get("coordinates") if isinstance(line, dict) else None
    return isinstance(coordinates, list) and len(coordinates) >= 2 and all(
        isinstance(point, list) and len(point) >= 2 and _number(point[0]) and _number(point[1]) for point in coordinates)


COORDINATES = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
INDIA_BOX = (6.0, 38.0, 68.0, 98.0)  # south, north, west, east
# Where people live and roads lead. A town's name also names its district (OpenStreetMap: an administrative
# boundary), whose centre can be many kilometres from the town, so a settlement of that name wins.
SETTLEMENTS = {"city", "town", "village", "suburb", "hamlet", "neighbourhood", "quarter", "locality", "borough", "isolated_dwelling"}


def _place_rank(key: Any, value: Any) -> int:
    """0 for a settlement, 2 for an administrative boundary or a region, 1 for anything else (a park, a station)."""
    if key == "place" and value in SETTLEMENTS:
        return 0
    return 2 if key == "boundary" or key == "place" else 1


def _geocode(place: str) -> dict[str, Any]:
    # "26.14, 91.73" is a position from the device (Your location in the dashboard): used as given, never looked up.
    match = COORDINATES.match(place)
    if match:
        latitude, longitude = float(match[1]), float(match[2])
        south, north, west, east = INDIA_BOX
        if not (south <= latitude <= north and west <= longitude <= east):
            raise HTTPException(status_code=422, detail="That position is outside India.")
        return {"name": "Your location", "latitude": latitude, "longitude": longitude}
    # A place chosen from the suggestions already has its OpenStreetMap coordinates; no second lookup by name.
    with get_connection() as connection:
        known = connection.execute("SELECT latitude, longitude FROM suggested_places WHERE value = ?", (place,)).fetchone()
    if known:
        return {"name": f"{place}, India", "latitude": known["latitude"], "longitude": known["longitude"]}
    query = urlencode({"q": f"{place}, India", "format": "jsonv2", "limit": 5, "countrycodes": "in"})
    results, _ = _cached_json(f"https://nominatim.openstreetmap.org/search?{query}", GEOCODE_CACHE_S, _valid_geocode)
    usable = [item for item in results if isinstance(item, dict) and _number(item.get("lat")) and _number(item.get("lon"))]
    if not usable:
        raise HTTPException(status_code=422, detail=f"Could not find '{place}' in India. Try a more specific place name.")
    # Nominatim's best match for "Patiala, Punjab" is the district; the city of that name is the destination.
    item = min(usable, key=lambda result: _place_rank(result.get("category"), result.get("type")))
    return {"name": str(item.get("display_name") or place), "latitude": float(item["lat"]), "longitude": float(item["lon"])}


BALANCED_SLACK = 1.10  # "balanced" accepts a route up to 10% slower than the fastest when fewer reports are near it


def _osrm_routes(origin: dict[str, Any], destination: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    coordinates = f"{origin['longitude']},{origin['latitude']};{destination['longitude']},{destination['latitude']}"
    routes, fetched_at = _cached_json(
        f"https://router.project-osrm.org/route/v1/driving/{coordinates}?{urlencode({'overview':'full','geometries':'polyline6','alternatives':'3','steps':'true'})}",
        ROUTE_CACHE_S,
        _valid_routes,
    )
    if routes.get("code") != "Ok" or not routes.get("routes"):
        raise HTTPException(status_code=422, detail="The routing service could not find a drivable route between these places.")
    found = []
    for route in routes["routes"]:
        route = {**route, "geometry": _route_line(route["geometry"])}  # the compact polyline OSRM sends, as GeoJSON
        found.append({"distance_m": round(route["distance"]), "duration_s": round(route["duration"]), "duration_no_traffic_s": None,
                      "geometry": route["geometry"], "highways": _route_highways(route), "steps": _route_steps(route)})
    return found, fetched_at


def _driving_routes(origin: dict[str, Any], destination: dict[str, Any], vehicle: str) -> tuple[list[dict[str, Any]], str, str, str | None]:
    """Routes, when they were fetched, the provider ("google" or "osrm") and a note when Google could not be used.

    With a Google key, Google's routes and traffic times (two-wheeler routes for a bike); an old copy is never
    served for them, as its traffic would be out of date. If Google fails, OSRM's routes, and the note says why
    the times have no traffic.
    """
    key = get_settings().google_maps_api_key
    if not key:
        return (*_osrm_routes(origin, destination), "osrm", None)
    try:
        data, fetched_at = _cached_json(google_routes.URL, google_routes.CACHE_S, google_routes.valid,
                                        body=google_routes.request_body(origin, destination, vehicle),
                                        headers=google_routes.headers(key), stale_ok=False)
        return google_routes.routes(data, _decode_polyline), fetched_at, "google", None
    except HTTPException as exc:
        logger.warning("Google Routes failed, using OSRM: %s", exc.detail)
        found, fetched_at = _osrm_routes(origin, destination)
        return (found, fetched_at, "osrm",
                f"Google Routes could not be used ({google_routes.failure_reason(str(exc.detail))}). Times are OSRM estimates without traffic.")


def _vehicle_note(vehicle: str, provider: str) -> str | None:
    """What the times mean for the chosen vehicle: no service here routes trucks, and OSRM has no two-wheeler routes."""
    if vehicle == "bike" and provider != "google":
        return "OSRM has no two-wheeler routes, so this is the car route and time; a bike may take other roads."
    if vehicle == "truck":
        return "Times are for a car; trucks are usually slower, and truck restrictions are not checked."
    return None


def plan_route(payload) -> dict[str, Any]:
    # Each place keeps the name the person typed: Nominatim's best match can be a road or station in that town.
    origin_query, destination_query = payload.origin.strip(), payload.destination.strip()
    origin = {**_geocode(origin_query)}
    destination = {**_geocode(destination_query)}
    origin["query"] = "Your location" if COORDINATES.match(origin_query) else origin_query
    destination["query"] = "Your location" if COORDINATES.match(destination_query) else destination_query
    found, routing_fetched_at, provider, routing_note = _driving_routes(origin, destination, payload.vehicle_type)
    routing_note = " ".join(note for note in (routing_note, _vehicle_note(payload.vehicle_type, provider)) if note) or None
    with get_connection() as connection:
        incident_items = load_incidents(connection)
    candidates = []
    for index, route in enumerate(found):
        candidates.append({
            "id": f"route-{index + 1}",
            **route,
            "tolls": tolls_on_route(route["geometry"], route["distance_m"]),
            "priority_rank": index + 1,
            "vehicle_suitability": "unknown",
            "exposure": route_exposure(route["geometry"], incident_items, route["highways"]),
            "highway_spans": highway_spans(route["steps"], route["highways"]),
        })
    if payload.priority == "fastest":
        candidates.sort(key=lambda r: r["duration_s"])
    elif payload.priority == "balanced":
        # The fastest route, unless one at most 10% slower has fewer reports placed near it (reviewer-located or at a
        # town on it). Reports that only name a highway are left out: long, busy highways are simply named more often.
        quickest = min(r["duration_s"] for r in candidates)
        def balance(route):
            exposure = route["exposure"]
            close = route["duration_s"] <= quickest * BALANCED_SLACK
            placed = (exposure["nearby"]["confirmed"], _unconfirmed_nearby(exposure), len(exposure["place_match_ids"]))
            return (not close, placed if close else (0, 0, 0), route["duration_s"])
        candidates.sort(key=balance)
    elif payload.priority == "shortest":
        candidates.sort(key=lambda r: r["distance_m"])
    elif payload.priority == "cautious":
        candidates.sort(key=lambda r: (r["exposure"]["nearby"]["confirmed"], _unconfirmed_nearby(r["exposure"]),
                                       len(r["exposure"]["place_match_ids"]), len(r["exposure"]["highway_mentions"]), r["duration_s"]))
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
        "provider": f"OpenStreetMap Nominatim + {'Google Routes' if provider == 'google' else 'OSRM'}",
        "routing_provider": provider,
        "traffic": provider == "google",
        "routing_fetched_at": routing_fetched_at,
        "routing_note": routing_note,
        "routes": candidates,
        "recommendation": candidates[0]["recommendation"],
        "recommendation_reason": " ".join(candidates[0]["recommendation_reasons"]),
        "data_note": (f"Distance and duration are Google's estimates for a {'two-wheeler' if payload.vehicle_type == 'bike' else 'car'} "
                      f"with traffic as of {routing_fetched_at}." if provider == "google"
                      else "Distance and duration are OSRM estimates for a car without live traffic.")
                     + " They do not include verified disruption or vehicle restriction data.",
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
    item = {
        "id": row["id"], "title": row["title"], "summary": row["summary"],
        "source_name": row["source_name"], "source_url": row["source_url"],
        "published_at": row["published_at"], "collected_at": row["collected_at"],
        "published_estimate": published, "published_approximate": approximate,
        "latitude": row["latitude"], "longitude": row["longitude"],
        "location_text": row["location_text"], "verification": row["verification"],
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
        "last_checked_at": _as_utc(datetime.fromisoformat(row["last_checked_at"])) if row["last_checked_at"] else None,
        "collection_run_id": row["collection_run_id"],
        # Provenance: which TinyFish search found the report, and what TinyFish Fetch read from its page.
        **{key: row[key] for key in ("publisher", "search_query", "search_kind", "last_seen_at", "published_source",
                                     "page_description", "page_excerpt", "page_author", "fetched_at", "fetch_error", "page_image")},
    }
    item["media"] = media_for(item)  # the source's own video, post or preview picture, if it has one
    return item


def load_incidents(connection: sqlite3.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    """Newest reports first (all of them unless limit is given), with duplicate, conflict and mention hints.

    Route checks, reviews and metrics need every report: an older confirmed closure must never drop out
    because newer reports arrived. Only the dashboard's list asks for a limited number.
    """
    rows = connection.execute("SELECT * FROM incidents ORDER BY collected_at DESC LIMIT ?", (-1 if limit is None else limit,)).fetchall()
    incidents = [incident_from_row(row) for row in rows]
    history: dict[str, list[dict[str, Any]]] = {}
    for review in connection.execute("SELECT * FROM incident_reviews ORDER BY reviewed_at DESC").fetchall():
        history.setdefault(review["incident_id"], []).append({
            key: review[key] for key in ("previous_verification", "verification", "review_note", "location_changed",
                                         "location_text", "latitude", "longitude", "reviewed_at")})
    flags: dict[str, list[sqlite3.Row]] = {}
    for flag in connection.execute("SELECT * FROM incident_flags ORDER BY created_at DESC").fetchall():
        flags.setdefault(flag["incident_id"], []).append(flag)
    checks: dict[str, list[sqlite3.Row]] = {}
    for check in connection.execute("SELECT * FROM incident_checks ORDER BY checked_at DESC").fetchall():
        checks.setdefault(check["incident_id"], []).append(check)
    for incident in incidents:
        incident["review_history"] = history.get(incident["id"], [])
        incident["open_flags"] = [{key: flag[key] for key in ("reason", "note", "created_at")}
                                  for flag in flags.get(incident["id"], []) if flag["resolved_at"] is None]
        incident["timeline"] = timeline(incident, checks.get(incident["id"], []), flags.get(incident["id"], []))
    return annotate(incidents, _place_points(connection))


def _place_points(connection: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    rows = connection.execute("SELECT name, latitude, longitude FROM place_locations WHERE latitude IS NOT NULL").fetchall()
    return {row["name"]: (row["latitude"], row["longitude"]) for row in rows}


CHECK_TEXT = {
    "seen_again": "Seen again in a TinyFish search",
    "page_read": "Page read with TinyFish Fetch",
    "page_unchanged": "Re-checked: page read, no change since the last read",
    "page_changed": "Re-checked: the page has changed since the last read; review the source again",
    "page_unreadable": "Page could not be read. This does not mean the road has reopened",
}


def timeline(incident: dict[str, Any], checks: list[sqlite3.Row], flags: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Everything that happened to a report, newest first (report 5: nothing is overwritten).

    Includes how its data was transformed, for example a publication date taken from the page.
    """
    events = []
    if incident["published_estimate"]:
        origin = {"page": "from the page", "search": "from the search result"}.get(incident["published_source"] or "", "")
        events.append({"at": incident["published_estimate"], "kind": "published", "approximate": incident["published_approximate"],
                       "text": f"Published by the source (“{incident['published_at']}”{', ' + origin if origin else ''})"})
    run = f" · run {incident['collection_run_id'].removeprefix('run_')[:8]}" if incident["collection_run_id"] else ""
    events.append({"at": incident["collected_at"], "kind": "collected",
                   "text": f"Collected by TinyFish {incident['search_kind'] or 'web'} search"
                           f"{' “' + incident['search_query'] + '”' if incident['search_query'] else ''}{run}"})
    for check in checks:
        detail = f": {check['detail']}" if check["detail"] and check["outcome"] == "page_unreadable" else ""
        events.append({"at": check["checked_at"], "kind": check["outcome"], "text": CHECK_TEXT.get(check["outcome"], check["outcome"]) + detail})
    if not any(check["kind"] == "fetch" for check in checks) and incident["fetched_at"]:
        # Reports collected before checks were recorded.
        outcome = "page_unreadable" if incident["fetch_error"] else "page_read"
        events.append({"at": incident["fetched_at"], "kind": outcome,
                       "text": CHECK_TEXT[outcome] + (f": {incident['fetch_error']}" if incident["fetch_error"] else "")})
    for review in incident["review_history"]:
        change = f"{review['previous_verification'] or 'new'} → {review['verification']}"
        events.append({"at": review["reviewed_at"], "kind": "review",
                       "text": f"Reviewed: {change}{' · location updated' if review['location_changed'] else ''} — {review['review_note']}"})
    if not incident["review_history"] and incident["review_note"] and incident["reviewed_at"]:
        # Reviewed before every review was kept.
        events.append({"at": incident["reviewed_at"], "kind": "review", "text": f"Reviewed: {incident['verification']} — {incident['review_note']}"})
    for flag in flags:
        events.append({"at": flag["created_at"], "kind": "flagged",
                       "text": f"Flagged as {flag['reason'].replace('_', ' ')}{' — ' + flag['note'] if flag['note'] else ''}"})
        if flag["resolved_at"]:
            events.append({"at": flag["resolved_at"], "kind": "flag_closed", "text": "Flag closed by a review"})
    for event in events:
        event["at"] = _as_utc(event["at"] if isinstance(event["at"], datetime) else datetime.fromisoformat(event["at"]))
        event.setdefault("approximate", False)
    return sorted(events, key=lambda event: event["at"], reverse=True)


MATCH_TOLERANCE_M = 3000
# A report placed at a town (approximate) matches a route passing within this distance of the town.
PLACE_TOLERANCE_M = 5000
EVIDENCE_MAX_AGE_S = 24 * 3600
# Reports a reviewer has dismissed as irrelevant or marked resolved by an authoritative update.
INACTIVE_STATES = {"dismissed", "resolved"}
VEHICLE_NOTE = "Vehicle restrictions such as weight, height and ghat-road limits are not checked."


def route_exposure(route_geometry: dict[str, Any], incidents: list[dict[str, Any]], highways: dict[str, int] | None = None,
                   tolerance_m: float = MATCH_TOLERANCE_M) -> dict[str, Any]:
    """Count reviewer-located reports near a route by verification state.

    Reports without reviewer coordinates are never counted as nearby. Those placed at a town they name
    (approximate) are listed under place_matches when the town is within 5 km of the route; those that name
    a national highway the route uses are listed under highway_mentions; both are lower-confidence relevance.
    A report placed at a town away from the route is about another stretch of that highway and is not listed.
    The rest only count as unlocated. Dismissed and resolved reports are ignored, and so are pages that describe
    no disruption or reopening (a taxi fare, a tour package) unless a reviewer has located them.
    """
    relevant = [item for item in incidents if item["verification"] not in INACTIVE_STATES]
    located = [item for item in relevant if item.get("latitude") is not None and item.get("longitude") is not None]
    located_ids = {item["id"] for item in located}
    unlocated = [item for item in relevant if item["id"] not in located_ids]
    reports = [item for item in unlocated if item.get("road_report", True)]
    line = route_geometry.get("coordinates", [])
    distance_to_route = _route_distance(line)
    place_matches: dict[str, list[str]] = {}
    place_distances: dict[str, int] = {}
    for item in reports:
        point = item.get("approximate_location")
        distance = distance_to_route(point["latitude"], point["longitude"], PLACE_TOLERANCE_M) if point else None
        if distance is not None:
            place_matches.setdefault(point["place"], []).append(item["id"])
            place_distances[item["id"]] = round(distance)
    placed = {incident_id for ids in place_matches.values() for incident_id in ids}
    highway_mentions = {highway: [item["id"] for item in reports if not item.get("approximate_location")
                                  and highway in item.get("mentions", {}).get("highways", [])]
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
        "place_tolerance_m": PLACE_TOLERANCE_M,
        "place_matches": place_matches,
        "place_match_ids": list(placed),
        "place_distances": place_distances,
        "place_matches_stale": sum(item["freshness"] == "stale" for item in unlocated if item["id"] in placed),
    }
    for incident in located:
        distance = distance_to_route(incident["latitude"], incident["longitude"], tolerance_m)
        if distance is None:
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
    matches += [(incident_id, "place") for incident_id in exposure.get("place_match_ids", [])]
    matches += [(incident_id, "road") for incident_id in exposure["highway_mention_ids"]]
    scored = []
    for incident_id, match in matches:
        item = incidents_by_id[incident_id]
        if match == "precise":
            distance = exposure["nearby_distances"][incident_id]
            location = 30 + round(20 * (1 - distance / exposure["tolerance_m"]))
            where = f"{distance / 1000:.1f} km from the route (reviewer-confirmed location)"
        elif match == "place":
            distance = exposure["place_distances"][incident_id]
            location = 18 + round(8 * (1 - distance / exposure["place_tolerance_m"]))
            where = (f"Names {item['approximate_location']['place']}, {distance / 1000:.1f} km from the route "
                     "(approximate: the town, not the exact spot)")
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
    active = [item for item in incidents if item["verification"] not in INACTIVE_STATES and item.get("road_report", True)]
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


def _route_distance(line: list[list[float]]):
    """A function giving a point's distance to the route in metres, or None beyond a tolerance.

    Equirectangular projection around the route's mean latitude; accurate enough at a few km.
    """
    if len(line) < 2:
        return lambda latitude, longitude, tolerance: None
    mean_lat = math.radians(sum(point[1] for point in line) / len(line))
    sx, sy = 111320 * math.cos(mean_lat), 111320
    xy = [(point[0] * sx, point[1] * sy) for point in line]
    min_x, max_x = min(x for x, _ in xy), max(x for x, _ in xy)
    min_y, max_y = min(y for _, y in xy), max(y for _, y in xy)

    def distance(latitude: float, longitude: float, tolerance: float) -> float | None:
        px, py = longitude * sx, latitude * sy
        if not (min_x - tolerance <= px <= max_x + tolerance and min_y - tolerance <= py <= max_y + tolerance):
            return None
        meters = _distance_to_line(px, py, xy)
        return meters if meters <= tolerance else None
    return distance


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
                   f"{f' ({old} past the freshness window for its event type; check it is still current)' if old else ''}."]
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
    placed = len(exposure.get("place_match_ids", []))
    if placed:
        stale = exposure["place_matches_stale"]
        reasons.append(f"{_plural(placed, 'report')} {'names' if placed == 1 else 'name'} a town on this route "
                       f"({', '.join(exposure['place_matches'])}){f', {stale} past their freshness window' if stale else ''}. "
                       "They are placed at the town, not the exact spot on the road.")
    mentioned = len(exposure["highway_mention_ids"])
    if mentioned:
        stale = exposure["highway_mentions_stale"]
        reasons.append(f"{_plural(mentioned, 'report')} without a confirmed location {'mentions' if mentioned == 1 else 'mention'} "
                       f"{', '.join(exposure['highway_mentions'])}, which this route uses"
                       f"{f' ({stale} past their freshness window)' if stale else ''}. Where on the road is not known.")
    other_unlocated = exposure["unlocated_reports"] - mentioned - placed
    if other_unlocated:
        reasons.append(f"{_plural(other_unlocated, 'other report' if mentioned or placed else 'report')} {'has' if other_unlocated == 1 else 'have'} no reviewer-confirmed location, so exposure to them is unknown.")
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
