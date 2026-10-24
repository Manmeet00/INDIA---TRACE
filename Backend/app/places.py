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

from .monitoring import log_call
from .regions import active_region
from .road_intelligence import _request_json

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
