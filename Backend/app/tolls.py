"""NHAI toll plazas along a planned route, from NHAI's published list of toll plazas.

The list (state, plaza code, name, type and coordinates; about 1,450 plazas) is downloaded by the operator as a
CSV from Dataful, which republishes it from NHAI's Rajmargyatra, and saved at TOLL_PLAZAS_PATH. It carries no
prices, so none are shown: a toll price is never estimated. Without the file a route's tolls are "unknown",
never "none". Only plazas within a few hundred metres of the route line count as on it.
"""
from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from typing import Any

NEAR_ROUTE_M = 400  # a plaza further than this from the route line is on another road
DEFAULT_PATH = "./data/toll_plazas.csv"
SOURCE = "NHAI list of toll plazas (via Dataful)"

_cache: dict[str, Any] = {"key": None, "plazas": [], "as_of": None}


def _path() -> Path:
    return Path(os.getenv("TOLL_PLAZAS_PATH", DEFAULT_PATH))


def _float(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_key(text: str) -> tuple[int, ...]:
    """"03-08-2026" (the list's day-month-year) as (2026, 8, 3), so the newest date is found; else as text."""
    parts = text.replace("/", "-").split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        day, month, year = (int(part) for part in parts)
        return (year, month, day) if year > 31 else (day, month, year)
    return (0,)


def load_plazas() -> tuple[list[dict[str, Any]], str | None] | None:
    """The plazas with usable coordinates in India and the list's date, or None when there is no list.

    Read again whenever the file changes, so a newer download is picked up without a restart.
    """
    path = _path()
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _cache["key"] != key:
        plazas, dates = [], set()
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                row = {str(name).strip().lower(): (value or "").strip() for name, value in row.items() if name}
                latitude, longitude = _float(row.get("latitude")), _float(row.get("longitude"))
                name = row.get("toll_plaza_name")
                if not name or latitude is None or longitude is None or not (6 <= latitude <= 38 and 68 <= longitude <= 98):
                    continue  # a plaza without a usable position cannot be placed on a route
                plazas.append({"code": row.get("toll_plaza_code") or None, "name": name, "type": row.get("toll_plaza_type") or None,
                               "state": row.get("state") or None, "latitude": latitude, "longitude": longitude})
                if row.get("data_as_on"):
                    dates.add(row["data_as_on"])
        _cache.update(key=key, plazas=plazas, as_of=max(dates, key=_date_key) if dates else None)
    return _cache["plazas"], _cache["as_of"]


def _metres(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    x = (lon2 - lon1) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(x, (lat2 - lat1) * 110540)


def tolls_on_route(geometry: dict[str, Any], route_distance_m: float) -> dict[str, Any]:
    """{"status": "listed" | "unknown", "plazas": [...in driving order, with km from the start], "source", "as_of"}."""
    loaded = load_plazas()
    if loaded is None:
        return {"status": "unknown", "plazas": [], "source": None, "as_of": None,
                "note": "The NHAI toll plaza list is not loaded, so tolls on this route are unknown."}
    plazas, as_of = loaded
    line = geometry.get("coordinates") or []
    if len(line) < 2:
        return {"status": "unknown", "plazas": [], "source": SOURCE, "as_of": as_of, "note": "The route has no line to check."}
    margin = 0.01
    west, east = min(p[0] for p in line) - margin, max(p[0] for p in line) + margin
    south, north = min(p[1] for p in line) - margin, max(p[1] for p in line) + margin
    along, total = [0.0], 0.0
    for index in range(1, len(line)):
        total += _metres(*line[index - 1][:2], *line[index][:2])
        along.append(total)
    scale = route_distance_m / total if total else 1.0  # the routing service's distances, measured along this line
    found = []
    for plaza in plazas:
        if not (west <= plaza["longitude"] <= east and south <= plaza["latitude"] <= north):
            continue
        best = (math.inf, 0.0)
        for index in range(1, len(line)):
            (ax, ay), (bx, by) = line[index - 1][:2], line[index][:2]
            cos = math.cos(math.radians(ay))
            dx, dy = (bx - ax) * cos, by - ay
            length = dx * dx + dy * dy
            t = 0.0 if not length else max(0.0, min(1.0, ((plaza["longitude"] - ax) * cos * dx + (plaza["latitude"] - ay) * dy) / length))
            gap = _metres(plaza["longitude"], plaza["latitude"], ax + t * (bx - ax), ay + t * (by - ay))
            if gap < best[0]:
                best = (gap, along[index - 1] + t * (along[index] - along[index - 1]))
        if best[0] <= NEAR_ROUTE_M:
            found.append({**plaza, "km_from_start": round(best[1] * scale / 1000, 1), "metres_from_route": round(best[0])})
    found.sort(key=lambda plaza: plaza["km_from_start"])
    return {"status": "listed", "plazas": found, "source": SOURCE, "as_of": as_of,
            "note": "Toll prices are not in this list; check the plaza's rates with NHAI before travelling."}
