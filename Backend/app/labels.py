"""Place names for the map's satellite view: cities, towns, suburbs, villages and neighbourhoods from
OpenStreetMap, as Google shows on its satellite map.

Overpass (OpenStreetMap's query service) is too slow to ask while someone pans, so each region's names are
downloaded once, kept in map_labels, and refreshed monthly. Only names and points are used: no boundary lines,
so the map never shows a border other than India's official one.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import sqlite3
import threading
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException

from .database import get_connection
from .monitoring import log_call
from .regions import Region, active_region
from .road_intelligence import _request_json

logger = logging.getLogger("indiatrace")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
REFRESH_AFTER = timedelta(days=30)
# Shown from this zoom level up, most important first, so a zoomed-out map is not crowded.
KINDS = {"city": 5, "town": 8, "suburb": 11, "village": 12, "quarter": 13, "neighbourhood": 13}
MAX_LABELS = 400
_refreshing = threading.Lock()


def _query(region: Region) -> str:
    south, west, north, east = region.bbox
    kinds = "|".join(KINDS)
    return f'[out:json][timeout:180];node["place"~"^({kinds})$"]["name"]({south},{west},{north},{east});out;'


def refresh_labels(connection: sqlite3.Connection, region: Region | None = None) -> dict[str, Any]:
    """Download the region's place names and replace the stored set."""
    region = region or active_region()
    if not _refreshing.acquire(blocking=False):
        return {"status": "running", "labels": 0}
    try:
        started = datetime.now(timezone.utc)
        try:
            data = _request_json(f"{OVERPASS_URL}?{urlencode({'data': _query(region)})}", timeout=200)
        except HTTPException:
            log_call(connection, "overpass", "failed")
            raise
        log_call(connection, "overpass", "ok")
        rows = []
        for element in data.get("elements", []) if isinstance(data, dict) else []:
            tags = element.get("tags") or {}
            name = tags.get("name:en") or tags.get("name")
            kind = tags.get("place")
            if isinstance(name, str) and kind in KINDS and isinstance(element.get("lat"), (int, float)) and isinstance(element.get("lon"), (int, float)):
                rows.append((region.id, name.strip()[:120], kind, element["lat"], element["lon"]))
        connection.execute("DELETE FROM map_labels WHERE region = ?", (region.id,))
        connection.executemany("INSERT INTO map_labels (region, name, kind, latitude, longitude) VALUES (?, ?, ?, ?, ?)", rows)
        connection.execute("INSERT OR REPLACE INTO map_label_sets (region, fetched_at, labels) VALUES (?, ?, ?)",
                           (region.id, started.isoformat(), len(rows)))
        connection.commit()
        return {"status": "ready", "labels": len(rows)}
    finally:
        _refreshing.release()


def labels_due(connection: sqlite3.Connection, region: Region | None = None) -> bool:
    region = region or active_region()
    row = connection.execute("SELECT fetched_at FROM map_label_sets WHERE region = ?", (region.id,)).fetchone()
    return row is None or datetime.fromisoformat(row["fetched_at"]) < datetime.now(timezone.utc) - REFRESH_AFTER


def refresh_in_background() -> None:
    """At startup: fetch the names if the region has none or they are a month old, without delaying the API."""
    def run() -> None:
        try:
            with get_connection() as connection:
                if labels_due(connection):
                    result = refresh_labels(connection)
                    logger.info("Map place names: %s", result)
        except Exception:  # the map works without names; the next start tries again
            logger.exception("Could not download map place names")
    threading.Thread(target=run, name="india-trace-map-labels", daemon=True).start()


def labels_in_view(connection: sqlite3.Connection, south: float, west: float, north: float, east: float, zoom: int) -> dict[str, Any]:
    """Names inside the view that suit the zoom level, most important kinds first."""
    region = active_region()
    kinds = [kind for kind, from_zoom in KINDS.items() if zoom >= from_zoom]
    meta = connection.execute("SELECT fetched_at, labels FROM map_label_sets WHERE region = ?", (region.id,)).fetchone()
    if not kinds or meta is None:
        return {"labels": [], "status": "ready" if meta else ("loading" if _refreshing.locked() else "unavailable"),
                "fetched_at": meta["fetched_at"] if meta else None}
    rank = " ".join(f"WHEN '{kind}' THEN {index}" for index, kind in enumerate(KINDS))
    rows = connection.execute(
        f"""SELECT name, kind, latitude, longitude FROM map_labels
        WHERE region = ? AND latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? AND kind IN ({','.join('?' * len(kinds))})
        ORDER BY CASE kind {rank} END LIMIT ?""",
        (region.id, south, north, west, east, *kinds, MAX_LABELS)).fetchall()
    return {"labels": [dict(row) for row in rows], "status": "ready", "fetched_at": meta["fetched_at"]}
