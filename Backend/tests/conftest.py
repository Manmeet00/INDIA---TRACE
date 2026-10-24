from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_connection


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API client on an empty temporary database, with TinyFish switched off."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("TINYFISH_API_KEY", "")
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def add_incident(client):
    def add(incident_id, verification="unverified", latitude=None, longitude=None, collected_at=None):
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO incidents
                (id, title, summary, source_name, source_url, collected_at, latitude, longitude, verification, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (incident_id, f"Report {incident_id}", "Landslide reported", "Test source",
                 f"https://example.org/{incident_id}", collected_at or datetime.now(timezone.utc).isoformat(),
                 latitude, longitude, verification, incident_id),
            )
    return add
