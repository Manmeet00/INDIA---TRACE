"""Driving routes from Google's Routes API: the times Google Maps shows, with live traffic.

Used when GOOGLE_MAPS_API_KEY is set in Backend/.env (the Routes API must be enabled for the key's project).
Google's answer is turned into the shape the rest of the backend uses for OSRM routes, so report matching,
tolls and turn-by-turn navigation work unchanged. Google's times are for a car; vehicle restrictions are not
checked. Answers are cached for a few minutes only, because traffic changes.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
CACHE_S = 300
FIELDS = ",".join([
    "routes.distanceMeters", "routes.duration", "routes.staticDuration", "routes.polyline.encodedPolyline",
    "routes.legs.endLocation", "routes.legs.steps.distanceMeters", "routes.legs.steps.staticDuration",
    "routes.legs.steps.startLocation", "routes.legs.steps.navigationInstruction",
])
HIGHWAY = re.compile(r"\bNH\s*-?\s*0*(\d{1,3}[A-Z]?)\b", re.IGNORECASE)
MIN_HIGHWAY_M = 2000
# The road a step continues on, from Google's words: "Turn left onto NH 44", "Head north on Mall Rd toward ...".
ROAD = re.compile(r"\b(?:onto|to stay on|on)\s+(.+?)(?:\s+toward[s]?\s+.*)?$")
EXIT = re.compile(r"take the (\d+)(?:st|nd|rd|th) exit", re.IGNORECASE)

# Google's maneuver names as OSRM's maneuver type and direction, which the dashboard draws as arrows.
MANEUVERS = {
    "DEPART": ("depart", None), "STRAIGHT": ("continue", "straight"), "NAME_CHANGE": ("new name", "straight"),
    "TURN_LEFT": ("turn", "left"), "TURN_RIGHT": ("turn", "right"),
    "TURN_SLIGHT_LEFT": ("turn", "slight left"), "TURN_SLIGHT_RIGHT": ("turn", "slight right"),
    "TURN_SHARP_LEFT": ("turn", "sharp left"), "TURN_SHARP_RIGHT": ("turn", "sharp right"),
    "UTURN_LEFT": ("turn", "uturn"), "UTURN_RIGHT": ("turn", "uturn"),
    "RAMP_LEFT": ("on ramp", "slight left"), "RAMP_RIGHT": ("on ramp", "slight right"),
    "FORK_LEFT": ("fork", "slight left"), "FORK_RIGHT": ("fork", "slight right"), "MERGE": ("merge", None),
    "ROUNDABOUT_LEFT": ("roundabout", "left"), "ROUNDABOUT_RIGHT": ("roundabout", "right"),
}


def request_body(origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    point = lambda place: {"location": {"latLng": {"latitude": place["latitude"], "longitude": place["longitude"]}}}
    return {"origin": point(origin), "destination": point(destination), "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE", "computeAlternativeRoutes": True,
            "languageCode": "en-IN", "regionCode": "in", "units": "METRIC", "polylineQuality": "HIGH_QUALITY"}


def headers(key: str) -> dict[str, str]:
    return {"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS}


def _seconds(value: Any) -> float | None:
    """Google's "1234s" durations."""
    try:
        return float(str(value).removesuffix("s"))
    except (TypeError, ValueError):
        return None


def _point(location: Any) -> list[float] | None:
    lat_lng = location.get("latLng") if isinstance(location, dict) else None
    try:
        return [float(lat_lng["longitude"]), float(lat_lng["latitude"])]
    except (TypeError, KeyError, ValueError):
        return None


def valid(data: Any) -> bool:
    """Google's answer: a routes list (empty when there is no route), each with a distance, a duration and a line."""
    if not isinstance(data, dict):
        return False
    return all(isinstance(route, dict) and isinstance(route.get("distanceMeters"), (int, float))
               and _seconds(route.get("duration")) is not None
               and isinstance((route.get("polyline") or {}).get("encodedPolyline"), str)
               for route in data.get("routes") or [])


def _step(step: dict[str, Any]) -> dict[str, Any] | None:
    location = _point(step.get("startLocation"))
    if location is None:
        return None  # a step without a place to show it is left out rather than guessed
    guidance = step.get("navigationInstruction") or {}
    text = str(guidance.get("instructions") or "").split("\n")[0].strip()  # later lines are "Pass by ..." hints
    kind, modifier = MANEUVERS.get(guidance.get("maneuver"), ("continue", None))
    road = ROAD.search(text)
    exit_number = EXIT.search(text)
    return {"type": kind, "modifier": modifier, "exit": int(exit_number[1]) if exit_number else None, "bearing_after": None,
            "name": road[1].strip() if road else "", "ref": "", "instruction": text or None,
            "distance_m": round(float(step.get("distanceMeters") or 0), 1),
            "duration_s": round(_seconds(step.get("staticDuration")) or 0, 1), "location": location}


def routes(data: dict[str, Any], decode) -> list[dict[str, Any]]:
    """Google's routes as {distance_m, duration_s, duration_no_traffic_s, geometry, steps, highways}."""
    found = []
    for route in data.get("routes") or []:
        steps, metres = [], {}
        for leg in route.get("legs") or []:
            for raw in leg.get("steps") or []:
                step = _step(raw) if isinstance(raw, dict) else None
                if step is None:
                    continue
                steps.append(step)
                for number in HIGHWAY.findall(step["instruction"] or ""):
                    key = f"NH-{number.upper()}"
                    metres[key] = metres.get(key, 0) + step["distance_m"]
        end = _point((route.get("legs") or [{}])[-1].get("endLocation"))
        if end:
            steps.append({"type": "arrive", "modifier": None, "exit": None, "bearing_after": None, "name": "", "ref": "",
                          "instruction": None, "distance_m": 0, "duration_s": 0, "location": end})
        line = decode(route["polyline"]["encodedPolyline"], 5)
        if len(line) < 2:
            continue
        static = _seconds(route.get("staticDuration"))
        found.append({
            "distance_m": round(route["distanceMeters"]),
            "duration_s": round(_seconds(route["duration"])),
            "duration_no_traffic_s": round(static) if static is not None else None,
            "geometry": {"type": "LineString", "coordinates": line},
            "steps": steps,
            "highways": {key: round(value) for key, value in sorted(metres.items()) if value >= MIN_HIGHWAY_M},
        })
    if not found:
        raise HTTPException(status_code=422, detail="Google found no drivable route between these places.")
    return found
