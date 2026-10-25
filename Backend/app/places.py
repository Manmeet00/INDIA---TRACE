"""Real coordinates for the places reports name, so reports can be shown at an approximate location.

A report that names one town (or says "at"/"near" a town) is placed at that town's coordinates from
OpenStreetMap Nominatim. This is labelled approximate everywhere: it tells a dispatcher which town the
report is about, not where on the road the problem is. Districts, valleys and names used in more than
one state are never placed. Reviewer-entered coordinates remain the only precise locations.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException

from .database import get_connection
from .monitoring import log_call
from .regions import active_region
from .road_intelligence import INDIA_BOX, _cached_json, _place_rank, _request_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RETRY_AFTER = timedelta(days=30)  # a place Nominatim could not find is tried again after this
MIN_INTERVAL_S = 1.1  # Nominatim's usage policy: at most one request per second
MAX_PER_RUN = 25


def place_points(connection: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """Coordinates of every place looked up so far, by place name."""
    rows = connection.execute("SELECT name, latitude, longitude FROM place_locations WHERE latitude IS NOT NULL").fetchall()
    return {row["name"]: (row["latitude"], row["longitude"]) for row in rows}


def pending_places(connection: sqlite3.Connection, incidents: list[dict[str, Any]]) -> list[str]:
    """Locatable places named in reports that have not been looked up (or failed over 30 days ago)."""
    region = active_region()
    known = {row["name"]: row for row in connection.execute("SELECT * FROM place_locations").fetchall()}
    cutoff = (datetime.now(timezone.utc) - RETRY_AFTER).isoformat()
    named = dict.fromkeys(name for item in incidents for name in item["mentions"]["places"])
    return [name for name in named
            if region.place_index[name].locatable
            and (name not in known or (known[name]["latitude"] is None and known[name]["geocoded_at"] < cutoff))]


def geocode_places(connection: sqlite3.Connection, names: list[str]) -> dict[str, Any]:
    """Look places up with Nominatim and store the results; one request per second at most."""
    region = active_region()
    found = missing = failed = 0
    connection.commit()  # do not hold a write transaction open while waiting on the network
    for index, name in enumerate(names[:MAX_PER_RUN]):
        if index:
            time.sleep(MIN_INTERVAL_S)
        place = region.place_index[name]
        query = ", ".join(part for part in (place.name, place.district, place.state, "India") if part)
        started = time.monotonic()
        try:
            results = _request_json(f"{NOMINATIM_URL}?{urlencode({'q': query, 'format': 'jsonv2', 'limit': 1, 'countrycodes': 'in'})}")
        except HTTPException:
            log_call(connection, "nominatim", "failed", started)
            connection.commit()  # the next lookup waits on the network; release the write lock first
            failed += 1
            continue
        log_call(connection, "nominatim", "ok", started)
        result = results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else None
        try:
            latitude, longitude = (float(result["lat"]), float(result["lon"])) if result else (None, None)
        except (KeyError, TypeError, ValueError):
            latitude = longitude = None
        connection.execute(
            "INSERT OR REPLACE INTO place_locations (name, latitude, longitude, display_name, geocoded_at) VALUES (?, ?, ?, ?, ?)",
            (name, latitude, longitude, (result or {}).get("display_name"), datetime.now(timezone.utc).isoformat()))
        connection.commit()
        found, missing = (found + 1, missing) if latitude is not None else (found, missing + 1)
    return {"looked_up": found + missing + failed, "found": found, "not_found": missing, "failed": failed}


PHOTON_URL = "https://photon.komoot.io/api/"
SUGGEST_CACHE_S = 7 * 86400
SUGGEST_LIMIT = 6


def _valid_photon(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("features"), list)


def suggest_places(query: str) -> list[dict[str, Any]]:
    """Place suggestions while someone types a start or destination, like a maps search box.

    The region's own towns come first; then Photon (OpenStreetMap search built for type-ahead, unlike
    Nominatim, whose policy forbids autocomplete) for places in India. Photon answers are cached for a week;
    if Photon is down the region's towns are still suggested.
    """
    text = query.strip()
    region = active_region()
    lowered = text.lower()
    local = [place for place in region.places if place.kind == "town" and place.state
             and any(name.lower().startswith(lowered) for name in (place.name, *place.aliases))]
    suggestions = [{"label": place.name, "detail": ", ".join(part for part in (place.district, place.state) if part),
                    "value": f"{place.name}, {place.state}", "source": "region"} for place in local]
    if len(text) >= 3:
        params = urlencode({"q": text, "limit": 10, "lang": "en", "lat": 26.1, "lon": 91.8})
        try:
            data, _ = _cached_json(f"{PHOTON_URL}?{params}", SUGGEST_CACHE_S, _valid_photon)
        except HTTPException:
            data = {"features": []}
        for feature in data["features"]:
            props = feature.get("properties") or {} if isinstance(feature, dict) else {}
            name = props.get("name")
            if props.get("countrycode") != "IN" or not isinstance(name, str):
                continue
            detail = ", ".join(part for part in (props.get("county") or props.get("city"), props.get("state")) if isinstance(part, str) and part)
            value = ", ".join(part for part in (name, props.get("state")) if isinstance(part, str) and part)
            rank = _place_rank(props.get("osm_key"), props.get("osm_value"))
            same = next((item for item in suggestions if item["value"].lower() == value.lower()), None)
            if same is None:
                suggestions.append({"label": name, "detail": detail, "value": value, "source": "search", "point": _point(feature), "rank": rank})
            elif same["source"] == "search" and rank < same["rank"] and _point(feature):
                same.update(point=_point(feature), rank=rank)  # "Patiala, Punjab": the city, not the district around it
    suggestions = suggestions[:SUGGEST_LIMIT]
    _remember_points(suggestions)
    return [{key: item for key, item in suggestion.items() if key not in ("point", "rank")} for suggestion in suggestions]


def _point(feature: dict[str, Any]) -> tuple[float, float] | None:
    """A Photon feature's (latitude, longitude), when it has a usable point inside India."""
    coordinates = (feature.get("geometry") or {}).get("coordinates") if isinstance(feature.get("geometry"), dict) else None
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError, IndexError):
        return None
    south, north, west, east = INDIA_BOX
    return (latitude, longitude) if south <= latitude <= north and west <= longitude <= east else None


def _remember_points(suggestions: list[dict[str, Any]]) -> None:
    """Keeps the coordinates of the places suggested, for when one is chosen (see road_intelligence._geocode)."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [(item["value"], *item["point"], now, item.get("rank")) for item in suggestions if item.get("point")]
    if rows:
        with get_connection() as connection:
            # A later, worse match (the district of "Nongpoh, Meghalaya") never replaces the town saved earlier.
            connection.executemany(
                """INSERT INTO suggested_places (value, latitude, longitude, suggested_at, place_rank) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(value) DO UPDATE SET latitude = excluded.latitude, longitude = excluded.longitude,
                suggested_at = excluded.suggested_at, place_rank = excluded.place_rank
                WHERE COALESCE(excluded.place_rank, 9) <= COALESCE(suggested_places.place_rank, 9)""", rows)
