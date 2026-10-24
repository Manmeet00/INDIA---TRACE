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
        self.geocoder_user_agent = os.getenv("GEOCODER_USER_AGENT", "INDIA-TRACE/0.1 (hackathon demo)")


@lru_cache
def get_settings() -> Settings:
    return Settings()
