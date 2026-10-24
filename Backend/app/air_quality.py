"""Current air quality at a point, from Open-Meteo (free, no key; CAMS forecast data), for the map's air layer."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException

from .road_intelligence import INDIA_BOX, _cached_json

AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
CACHE_S = 30 * 60
# US AQI bands, as Open-Meteo reports them.
BANDS = ((50, "Good"), (100, "Moderate"), (150, "Unhealthy for sensitive groups"), (200, "Unhealthy"), (300, "Very unhealthy"))


def _valid(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("current"), dict)


def air_quality(latitude: float, longitude: float) -> dict[str, Any]:
    south, north, west, east = INDIA_BOX
    if not (south <= latitude <= north and west <= longitude <= east):
        raise HTTPException(status_code=422, detail="Air quality is shown for places in India only.")
    # Rounded to about 1 km, so nearby requests share one cached answer.
    params = urlencode({"latitude": round(latitude, 2), "longitude": round(longitude, 2), "current": "us_aqi,pm2_5,pm10"})
    data, fetched_at = _cached_json(f"{AIR_QUALITY_URL}?{params}", CACHE_S, _valid)
    current = data["current"]
    aqi = current.get("us_aqi")
    if not isinstance(aqi, (int, float)):
        raise HTTPException(status_code=502, detail="Open-Meteo has no air quality value for this place right now.")
    band = next((label for limit, label in BANDS if aqi <= limit), "Hazardous")
    return {"us_aqi": round(aqi), "band": band, "pm2_5": current.get("pm2_5"), "pm10": current.get("pm10"),
            "time": current.get("time"), "fetched_at": fetched_at, "source": "Open-Meteo (CAMS)"}
