from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "IndiaTrace API")
        self.api_prefix = os.getenv("API_PREFIX", "/api/v1").rstrip("/")
        self.database_path = Path(os.getenv("DATABASE_PATH", "./data/indiatrace.sqlite3"))
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if origin.strip()
        ]
        self.tinyfish_api_key = os.getenv("TINYFISH_API_KEY", "")
        # Mappls Web Maps static key. Unlike TinyFish, the Mappls SDK runs in the browser and needs this key there,
        # so restrict it to your domains in the Mappls console. Without it the map uses OpenStreetMap tiles.
        self.mappls_static_key = os.getenv("MAPPLS_STATIC_KEY", "").strip()
        # Google Routes API key (server-side only). With it, routes and times come from Google with live traffic;
        # without it, or when Google fails, from OSRM without traffic.
        self.google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
        self.geocoder_user_agent = os.getenv("GEOCODER_USER_AGENT", "INDIA-TRACE/0.1 (hackathon demo)")
        # 0 turns scheduled collection off; otherwise the pilot searches run every N minutes.
        self.collection_interval_minutes = int(os.getenv("COLLECTION_INTERVAL_MINUTES", "0") or 0)
        self.collection_window_days = int(os.getenv("COLLECTION_WINDOW_DAYS", "30") or 0)
        # Which entry of app/regions.py sets places, roads, searches, source policy and freshness windows.
        self.region = os.getenv("REGION", "northeast").strip() or "northeast"


@lru_cache
def get_settings() -> Settings:
    return Settings()
