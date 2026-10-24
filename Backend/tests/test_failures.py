"""End-to-end failure cases from the project plan: no results, timeouts, malformed reports,
missing coordinates, stale incidents and database failures.

Each test goes through the HTTP API. External services are faked at the network layer
(see the providers fixture), so the real request, parsing and caching code runs.
"""
import http.client
import sqlite3
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from app import database
from app.config import get_settings
from app.database import get_connection
from app.main import DATABASE_UNAVAILABLE, app
from conftest import FETCH, SEARCH

ROUTE = {"origin": "Guwahati", "destination": "Shillong", "priority": "balanced"}


def collect(client, **body):
    return client.post("/api/collection/run", json={"road": "NH-6", **body})


# --- No results ---------------------------------------------------------------------------

def test_search_with_no_results_is_logged_and_says_absence_is_not_clear(client, tinyfish_network):
    body = collect(client).json()
    assert (body["status"], body["collected"]) == ("complete", 0)
    assert "does not mean the road is clear" in body["message"]
    run = client.get("/api/collection/runs").json()[0]
    assert (run["results"], run["stored"], run["status"]) == (0, 0, "complete")
    assert not any(host == FETCH for host, _ in tinyfish_network["calls"])  # nothing to read


def test_route_with_no_evidence_is_never_called_clear(client, providers):
    body = client.post("/api/routes/plan", json=ROUTE).json()
    assert {route["recommendation"] for route in body["routes"]} == {"verify_before_dispatch"}
    assert "No reports does not mean the road is clear." in body["recommendation_reason"]
    assert body["routes"][0]["coverage"]["highways"][0]["fresh"] == 0  # NH-6 shown as a coverage gap


# --- Timeouts and dropped connections -----------------------------------------------------

@pytest.mark.parametrize("failure", [TimeoutError("timed out"), URLError(TimeoutError("timed out"))], ids=["read", "connect"])
def test_routing_timeout_without_a_cached_copy_is_a_clear_502(client, providers, failure):
    providers["nominatim.openstreetmap.org"] = failure
    response = client.post("/api/routes/plan", json=ROUTE)
    assert response.status_code == 502
    assert response.json()["detail"] == ("An external routing or search service is unavailable "
                                         "(nominatim.openstreetmap.org did not answer within 15 s).")


@pytest.mark.parametrize("answer", [
    ConnectionResetError("Connection reset by peer"),
    lambda _: __import__("conftest").Answer(error=http.client.IncompleteRead(b'[{"lat"')),
    lambda _: __import__("conftest").Answer(b"<html>502 Bad Gateway</html>"),
], ids=["reset", "cut-off-body", "html-instead-of-json"])
def test_dropped_or_garbled_provider_responses_are_502_not_500(client, providers, answer):
    providers["router.project-osrm.org"] = answer
    response = client.post("/api/routes/plan", json=ROUTE)
    assert response.status_code == 502
    assert "router.project-osrm.org" in response.json()["detail"]


def test_routing_timeout_serves_the_last_good_route_with_its_age(client, providers, monkeypatch):
    first = client.post("/api/routes/plan", json=ROUTE).json()
    providers["router.project-osrm.org"] = TimeoutError("timed out")
    monkeypatch.setattr("app.road_intelligence.ROUTE_CACHE_S", -1)  # force a refresh attempt
    second = client.post("/api/routes/plan", json=ROUTE)
    assert second.status_code == 200
    assert second.json()["routing_fetched_at"] == first["routing_fetched_at"]


def test_page_fetch_timeout_keeps_the_reports_and_records_why(client, tinyfish_network, monkeypatch):
    monkeypatch.setattr("app.collection.time.sleep", lambda _: None)
    tinyfish_network[SEARCH] = {"results": [{"url": "https://example.org/nh6", "title": "NH-6 blocked", "snippet": "NH-6 blocked at Sonapur."}]}
    tinyfish_network[FETCH] = TimeoutError("timed out")
    body = collect(client).json()
    assert (body["status"], body["collected"]) == ("complete", 1)
    report = client.get("/api/incidents").json()[0]
    assert "api.fetch.tinyfish.ai did not answer within 90 s" in report["fetch_error"]
    assert client.get("/api/collection/runs").json()[0]["fetch_failed"] == 1


def test_search_timeouts_are_retried_then_logged_as_a_failed_run(client, tinyfish_network, monkeypatch):
    monkeypatch.setattr("app.collection.time.sleep", lambda _: None)
    tinyfish_network[SEARCH] = TimeoutError("timed out")
    response = collect(client)
    assert response.status_code == 502
    assert sum(host == SEARCH for host, _ in tinyfish_network["calls"]) == 4  # web and news, two attempts each
    assert client.get("/api/collection/runs").json()[0]["status"] == "failed"


# --- Malformed reports and provider data --------------------------------------------------

def test_malformed_search_results_are_skipped_and_nothing_is_invented(client, tinyfish_network):
    tinyfish_network[SEARCH] = {"results": [
        None, "a string", ["a", "list"],
        {"url": 12345, "snippet": "URL is not text"},
        {"url": "https://example.org/list", "snippet": ["not", "text"]},
        {"url": "ftp://example.org/file", "snippet": "Not a web page"},
        {"url": "https://user:secret@example.org/a", "snippet": "Credentials in the URL"},
        {"url": "mailto:desk@example.org", "snippet": "Not a source"},
        {"url": "https://example.org/good", "title": 42, "snippet": "NH-6 blocked near Sonapur.", "date": "sometime soon"},
    ]}
    body = collect(client).json()
    assert body["collected"] == 1
    report = client.get("/api/incidents").json()[0]
    assert report["source_url"] == "https://example.org/good"
    assert report["title"] == "Untitled public source"  # a non-text title is not guessed
    assert report["published_at"] == "sometime soon" and report["published_estimate"] is None
    assert report["freshness"] == "unknown" and report["verification"] == "unverified"


@pytest.mark.parametrize("answer", [{"error": "quota"}, [], {"results": "none"}], ids=["error-object", "list", "results-not-list"])
def test_search_response_without_a_result_list_counts_as_a_failed_search(client, tinyfish_network, monkeypatch, answer):
    monkeypatch.setattr("app.collection.time.sleep", lambda _: None)
    tinyfish_network[SEARCH] = answer
    assert collect(client).status_code == 502
    assert client.get("/api/incidents").json() == []


def test_malformed_fetch_response_does_not_lose_the_collected_reports(client, tinyfish_network):
    tinyfish_network[SEARCH] = {"results": [{"url": "https://example.org/nh6", "title": "NH-6", "snippet": "NH-6 blocked."}]}
    tinyfish_network[FETCH] = {"results": ["junk", None, {"url": 5}, {"url": "https://example.org/other"}], "errors": "not a list"}
    body = collect(client).json()
    assert body["collected"] == 1
    assert client.get("/api/collection/runs").json()[0]["fetched"] == 0


@pytest.mark.parametrize("host, answer", [
    ("nominatim.openstreetmap.org", [{"display_name": "Guwahati", "lat": "not a number", "lon": "91.7"}]),
    ("nominatim.openstreetmap.org", {"error": "Rate limited"}),
    ("router.project-osrm.org", {"code": "Ok", "routes": [{"distance": 1000}]}),
    ("router.project-osrm.org", {"code": "Ok", "routes": [{"distance": 1, "duration": 1, "geometry": {"coordinates": [["a", "b"], [1]]}}]}),
], ids=["geocode-bad-lat", "geocode-error-object", "route-no-geometry", "route-bad-points"])
def test_malformed_provider_data_is_a_502_and_is_never_cached(client, providers, host, answer):
    good = providers[host]
    providers[host] = answer
    response = client.post("/api/routes/plan", json=ROUTE)
    assert response.status_code == 502 and "returned an unexpected response" in response.json()["detail"]
    providers[host] = good
    assert client.post("/api/routes/plan", json=ROUTE).status_code == 200  # the bad answer was not cached


def test_unknown_place_and_no_drivable_route_are_explained(client, providers):
    unknown = client.post("/api/routes/plan", json={**ROUTE, "origin": "Atlantis"})
    assert unknown.status_code == 422 and "Could not find 'Atlantis' in India" in unknown.json()["detail"]
    providers["router.project-osrm.org"] = {"code": "NoRoute", "message": "Impossible route"}
    no_route = client.post("/api/routes/plan", json=ROUTE)
    assert no_route.status_code == 422 and "could not find a drivable route" in no_route.json()["detail"]


@pytest.mark.parametrize("method, url, body", [
    ("post", "/api/routes/plan", {"origin": "G", "destination": "Shillong"}),
    ("post", "/api/routes/plan", {**ROUTE, "vehicle_type": "bicycle"}),
    ("patch", "/api/incidents/r1/review", {"verification": "confirmed", "review_note": "Checked", "latitude": 200, "longitude": 91}),
    ("patch", "/api/incidents/r1/review", {"verification": "closed", "review_note": "Checked"}),
    ("patch", "/api/incidents/r1/review", {"verification": "confirmed", "review_note": "  "}),
    ("post", "/api/incidents/r1/flags", {"reason": "spam"}),
    ("post", "/api/collection/run", {"window_days": -1}),
], ids=["short-origin", "bad-vehicle", "latitude-out-of-range", "bad-status", "blank-note", "bad-flag", "bad-window"])
def test_malformed_requests_are_rejected_before_anything_is_saved(client, add_incident, method, url, body):
    add_incident("r1")
    assert getattr(client, method)(url, json=body).status_code == 422
    report = client.get("/api/incidents/r1").json()
    assert (report["verification"], report["review_history"], report["open_flags"]) == ("unverified", [], [])


# --- Missing coordinates ------------------------------------------------------------------

def test_report_without_coordinates_is_never_placed_on_a_route(client, providers, add_incident):
    add_incident("named", summary="Landslide blocks NH-6 near Sonapur")
    add_incident("vague", summary="Heavy rain across Meghalaya")
    report = client.get("/api/incidents/named").json()
    assert (report["latitude"], report["location_confidence"]) == (None, "road_mentioned")

    route = client.post("/api/routes/plan", json=ROUTE).json()["routes"][0]
    exposure = route["exposure"]
    assert sum(exposure["nearby"].values()) == 0  # never matched by distance
    assert exposure["highway_mentions"] == {"NH-6": ["named"]} and exposure["unlocated_reports"] == 2
    assert route["recommendation"] == "verify_before_dispatch"
    assert any("Where on the road is not known" in reason for reason in route["recommendation_reasons"])
    assert [item["match"] for item in route["impact_reports"]] == ["road"]


def test_located_report_stops_counting_once_its_coordinates_are_removed(client, providers, add_incident):
    add_incident("slide", "confirmed", 25.90, 91.80)
    assert client.post("/api/routes/plan", json=ROUTE).json()["routes"][0]["exposure"]["nearby"]["confirmed"] == 1
    client.patch("/api/incidents/slide/review", json={"verification": "confirmed", "review_note": "Wrong spot", "latitude": None, "longitude": None})
    route = client.post("/api/routes/plan", json=ROUTE).json()["routes"][0]
    assert route["exposure"]["nearby"]["confirmed"] == 0 and route["exposure"]["unlocated_reports"] == 1


# --- Stale incidents ----------------------------------------------------------------------

def test_stale_confirmed_report_is_never_shown_as_a_current_confirmation(client, providers, add_incident):
    add_incident("old", "confirmed", 25.90, 91.80, published_at="Jul 3, 2023")
    report = client.get("/api/incidents/old").json()
    assert (report["freshness"], report["evidence_status"]) == ("stale", "stale")
    route = next(item for item in client.post("/api/routes/plan", json=ROUTE).json()["routes"] if item["exposure"]["nearby"]["confirmed"])
    assert "past the freshness window for its event type; check it is still current" in route["recommendation_reasons"][0]
    assert route["impact_reports"][0]["evidence_status"] == "stale"


def test_old_collection_asks_for_a_new_run(client, providers, add_incident):
    add_incident("aged", collected_at="2026-01-01T00:00:00+00:00")
    reasons = client.post("/api/routes/plan", json=ROUTE).json()["routes"][0]["recommendation_reasons"]
    assert "The newest collected evidence is more than 24 hours old. Run collection again." in reasons


# --- Database failures --------------------------------------------------------------------

DATA_ENDPOINTS = [
    ("get", "/api/incidents", None),
    ("get", "/api/incidents/r1", None),
    ("patch", "/api/incidents/r1/review", {"verification": "confirmed", "review_note": "Checked"}),
    ("post", "/api/incidents/r1/flags", {"reason": "outdated"}),
    ("post", "/api/routes/plan", ROUTE),
    ("post", "/api/collection/run", None),
    ("get", "/api/collection/runs", None),
]


def break_database(monkeypatch, path):
    monkeypatch.setenv("DATABASE_PATH", str(path))
    get_settings.cache_clear()


@pytest.mark.parametrize("damage", ["directory", "corrupt-file", "unwritable-folder"])
def test_every_endpoint_answers_503_with_cors_when_the_database_fails(client, providers, monkeypatch, tmp_path, damage):
    if damage == "directory":
        target = tmp_path  # a folder where the database file should be
    elif damage == "corrupt-file":
        target = tmp_path / "corrupt.sqlite3"
        target.write_bytes(b"this is not a database" * 100)
    else:
        (tmp_path / "file").write_text("x")
        target = tmp_path / "file" / "db.sqlite3"  # its parent is a file, so the folder cannot be created
    break_database(monkeypatch, target)
    origin = {"Origin": "http://localhost:5173"}
    health = client.get("/api/health", headers=origin)
    assert health.status_code == 503 and health.json()["detail"] == DATABASE_UNAVAILABLE
    for method, url, body in DATA_ENDPOINTS:
        response = client.request(method.upper(), url, json=body, headers=origin)
        assert response.status_code == 503, url
        assert response.json()["detail"] == DATABASE_UNAVAILABLE, url
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173", url  # the browser can read the reason


def test_locked_database_asks_to_retry(client, monkeypatch):
    def locked():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(database, "connect", locked)
    response = client.get("/api/incidents")
    assert response.status_code == 503 and response.json()["detail"] == "The database is busy. Try again in a moment."


def test_failed_review_write_is_rolled_back_completely(client, add_incident):
    add_incident("r1")
    with get_connection() as connection:
        connection.execute("CREATE TRIGGER fail_review BEFORE INSERT ON incident_reviews BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END")
    response = client.patch("/api/incidents/r1/review", json={"verification": "confirmed", "review_note": "Checked", "latitude": 25.9, "longitude": 91.8})
    assert response.status_code == 503
    with get_connection() as connection:
        connection.execute("DROP TRIGGER fail_review")
    report = client.get("/api/incidents/r1").json()
    assert (report["verification"], report["latitude"], report["review_history"]) == ("unverified", None, [])


def test_api_starts_and_reports_the_problem_when_the_database_cannot_be_created(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("x")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "file" / "db.sqlite3"))
    monkeypatch.setenv("TINYFISH_API_KEY", "")
    get_settings.cache_clear()
    try:
        with TestClient(app) as broken:
            assert broken.get("/api/health").status_code == 503
            assert broken.get("/api/incidents").json()["detail"] == DATABASE_UNAVAILABLE
    finally:
        get_settings.cache_clear()


def test_database_restored_after_a_failure_works_again(client, monkeypatch, tmp_path, add_incident):
    add_incident("kept")
    good = get_settings().database_path
    break_database(monkeypatch, tmp_path)
    assert client.get("/api/incidents").status_code == 503
    break_database(monkeypatch, good)
    assert [item["id"] for item in client.get("/api/incidents").json()] == ["kept"]
