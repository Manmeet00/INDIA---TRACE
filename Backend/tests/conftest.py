from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import jobs, road_intelligence
from app.config import get_settings
from app.database import get_connection


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches a real service: requests fail unless a test fakes them (see the providers fixture)."""
    def refuse(request, timeout, context):
        raise AssertionError(f"Test tried to reach the network: {request.full_url}")
    monkeypatch.setattr(road_intelligence, "urlopen", refuse)

    # Pages have no preview image unless a test says so (test_media.py tests the real reader with fake pages).
    monkeypatch.setattr("app.media.preview_image", lambda url: None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API client on an empty temporary database, with TinyFish switched off."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    # Tests never inherit the developer's Backend/.env: no keys, no schedule, the default region.
    monkeypatch.setenv("TINYFISH_API_KEY", "")
    monkeypatch.setenv("MAPPLS_STATIC_KEY", "")
    monkeypatch.setenv("COLLECTION_INTERVAL_MINUTES", "0")
    monkeypatch.setenv("COLLECTION_WINDOW_DAYS", "30")
    monkeypatch.setenv("REGION", "northeast")
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as test_client:
        yield test_client
    # A background run must not outlive its test and write into the next one's database.
    assert jobs._running.acquire(timeout=10), "a background run was still going after the test"
    jobs._running.release()
    get_settings.cache_clear()


@pytest.fixture
def add_incident(client):
    def add(incident_id, verification="unverified", latitude=None, longitude=None, collected_at=None,
            summary="Landslide reported", published_at=None, source_url=None, last_checked_at=None):
        collected_at = collected_at or datetime.now(timezone.utc).isoformat()
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO incidents
                (id, title, summary, source_name, source_url, collected_at, latitude, longitude, verification, content_hash,
                published_at, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (incident_id, f"Report {incident_id}", summary, "Test source",
                 source_url or f"https://example.org/{incident_id}", collected_at,
                 latitude, longitude, verification, incident_id, published_at, last_checked_at or collected_at),
            )
    return add


# Guwahati to Shillong as two OSRM routes on NH-6; route 1 passes 25.90, 91.80 and route 2 swings east.
PLACES = {"Guwahati": (26.18, 91.75), "Shillong": (25.58, 91.88)}
ROUTE_LINES = [[[91.75, 26.18], [91.80, 25.90], [91.88, 25.58]], [[91.75, 26.18], [92.10, 25.90], [91.88, 25.58]]]


def nominatim(request):
    query = parse_qs(urlsplit(request.full_url).query)["q"][0]
    return [{"display_name": f"{name}, India", "lat": str(lat), "lon": str(lon)}
            for name, (lat, lon) in PLACES.items() if query.startswith(name)]


def osrm(_request):
    return {"code": "Ok", "routes": [
        {"distance": 100000 + 20000 * index, "duration": 4000 + 600 * index,
         "geometry": {"type": "LineString", "coordinates": line},
         "legs": [{"steps": [{"ref": "NH6", "distance": 90000}]}]}
        for index, line in enumerate(ROUTE_LINES)]}


class Answer:
    """A provider response body, or an error raised while reading it (for example a connection cut mid-body)."""
    def __init__(self, body=b"", error=None):
        self.body, self.error = body, error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        if self.error:
            raise self.error
        return self.body


@pytest.fixture
def providers(monkeypatch):
    """External services faked at the network layer, so the real _request_json runs: timeouts, bad bytes and all.

    Map a host to a function of the request returning JSON data, an Answer, or an exception to raise.
    Requests to a host with no answer fail the test.
    """
    answers = {"nominatim.openstreetmap.org": nominatim, "router.project-osrm.org": osrm, "photon.komoot.io": {"features": []}}
    calls = []

    def urlopen(request, timeout, context):
        host = urlsplit(request.full_url).hostname
        calls.append((host, request))
        assert host in answers, f"Unexpected external request: {request.full_url}"
        answer = answers[host](request) if callable(answers[host]) else answers[host]
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, Answer) else Answer(json.dumps(answer).encode())

    monkeypatch.setattr(road_intelligence, "urlopen", urlopen)
    answers["calls"] = calls
    return answers



SEARCH, FETCH = "api.search.tinyfish.ai", "api.fetch.tinyfish.ai"


@pytest.fixture
def tinyfish_network(client, providers, monkeypatch):
    """TinyFish switched on behind the network fake. Search finds nothing until a test sets providers[SEARCH];
    Fetch reads every page it is given."""
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr("app.places.time.sleep", lambda _: None)
    providers[SEARCH] = {"results": []}
    providers[FETCH] = lambda request: {"results": [{"url": url, "description": "Page"} for url in json.loads(request.data)["urls"]]}
    return providers
