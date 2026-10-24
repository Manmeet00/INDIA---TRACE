"""Report features beyond the MVP: source categories (7, 9), regional configuration (5, 6.7), lifecycle and
re-checks (6.5, 7.9), traceable runs and the incident timeline (5, 6.3, 7.4), location-based duplicates (6.4),
background collection (11) and monitoring metrics (8, 13)."""
from datetime import datetime, timedelta, timezone
import json
import threading
import time

import pytest

from app.config import get_settings
from app.database import get_connection, initialize_database
from app.evidence import annotate, source_category
from app.road_intelligence import parse_published
from conftest import FETCH, SEARCH

ROUTE = {"origin": "Guwahati", "destination": "Shillong"}


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def report(incident_id, text, published_at=None, **extra):
    estimate, approximate = parse_published(published_at, ago(seconds=0))
    return {"id": incident_id, "title": text, "summary": text, "published_at": published_at, "published_estimate": estimate,
            "published_approximate": approximate, "verification": "unverified", **extra}


def wait_for_run(client, run_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/collection/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


# --- Source categories and source quality -------------------------------------------------

@pytest.mark.parametrize("url, kind, expected", [
    ("https://dimahasao.assam.gov.in/notice", "web", "official"),
    ("https://meghalaya.nic.in/advisory", "web", "official"),
    ("https://www.facebook.com/page/posts/1", "web", "social"),
    ("https://www.sentinelassam.com/story", "web", "news"),
    ("https://unknown-blog.example/story", "news", "news"),
    ("https://en.wikipedia.org/wiki/NH_6", "web", "other"),
    ("https://notgov.in.example.com/x", "web", "other"),
])
def test_source_categories(url, kind, expected):
    assert source_category(url, kind) == expected


def test_official_source_corroborates_but_never_outranks_stale_or_review(client, add_incident):
    add_incident("official", summary="NH-6 closed near Sonapur", source_url="https://eastjaintiahills.gov.in/order")
    add_incident("old", summary="NH-6 closed near Sonapur", source_url="https://eastjaintiahills.gov.in/old", published_at="Jul 3, 2023")
    items = {item["id"]: item for item in client.get("/api/incidents").json()}
    assert (items["official"]["source_category"], items["official"]["evidence_status"]) == ("official", "corroborated")
    assert items["old"]["evidence_status"] == "stale"


def test_collection_keeps_only_the_allowed_source_categories(client, tinyfish_network):
    tinyfish_network[SEARCH] = {"results": [
        {"url": "https://www.facebook.com/page/posts/9", "title": "NH-6", "snippet": "NH-6 blocked, says a post."},
        {"url": "https://www.sentinelassam.com/nh6", "title": "NH-6", "snippet": "NH-6 blocked at Sonapur."},
    ]}
    body = client.post("/api/collection/run", json={"road": "NH-6", "source_categories": ["news", "official"]}).json()
    assert body["collected"] == 1
    assert "2 results from sources outside the allowed categories (official, news) were skipped" in body["message"]
    assert [item["source_url"] for item in client.get("/api/incidents").json()] == ["https://www.sentinelassam.com/nh6"]
    assert client.get("/api/collection/runs").json()[0]["filtered"] == 2  # web and news search both return it
    assert client.post("/api/collection/run", json={"source_categories": ["rumour"]}).status_code == 422


# --- Regional configuration ---------------------------------------------------------------

def test_region_names_districts_aliases_and_scripts():
    items = {item["id"]: item for item in annotate([
        report("alias", "Traffic halted on GS Road and the Guwahati–Shillong road near Cherrapunji"),
        report("district", "Slide in West Jaintia Hills near Jowai"),
        report("script", "শিলং-গুৱাহাটী পথত ভূমিস্খলন NH-6"),
        report("arunachal", "Road cut off in Arunachal"),
    ])}
    assert items["alias"]["mentions"] == {"highways": ["NH-6"], "places": ["Guwahati", "Shillong", "Sohra"]}
    assert items["alias"]["districts"] == ["Kamrup Metropolitan", "East Khasi Hills"]
    assert items["district"]["regions"] == ["Meghalaya"]  # "West" in a district name is not West Bengal
    assert items["district"]["districts"] == ["West Jaintia Hills"]
    assert items["script"]["scripts"] == ["Bengali-Assamese", "Latin"]
    assert items["arunachal"]["regions"] == ["Arunachal Pradesh"]


def test_region_endpoint_shows_configuration_and_coverage_gaps(client, add_incident):
    add_incident("shillong", summary="Landslide near Shillong", published_at=ago(hours=2))
    body = client.get("/api/region").json()
    assert body["id"] == "northeast" and body["corridor"].startswith("NH-6 / NH-306")
    assert body["source_categories"] == ["official", "news", "social", "other"]
    coverage = {row["state"]: row for row in body["coverage"]}
    assert (coverage["Meghalaya"]["reports"], coverage["Meghalaya"]["fresh"]) == (1, 1)
    assert coverage["Mizoram"]["reports"] == 0 and "coverage gap" in body["coverage_note"]


def test_unknown_region_is_refused(monkeypatch):
    monkeypatch.setenv("REGION", "atlantis")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="Unknown REGION 'atlantis'"):
            annotate([report("a", "x")])
    finally:
        get_settings.cache_clear()


# --- Lifecycle ----------------------------------------------------------------------------

@pytest.mark.parametrize("published, checked, verification, expected", [
    (2, 2, "unverified", "new"),                 # landslide, 72 h window: well inside
    (40, 40, "unverified", "needs_recheck"),     # past half the window and not checked since
    (40, 1, "unverified", "new"),                # checked an hour ago
    (100, 1, "unverified", "stale"),             # past the window: a check does not make it fresh
    (40, 40, "resolved", "resolved"),
    (None, 30, "unverified", "needs_recheck"),   # no source time, last checked over a day ago
    (None, 2, "unverified", "new"),
])
def test_lifecycle(client, add_incident, published, checked, verification, expected):
    add_incident("r", verification, summary="Landslide on NH-6", published_at=ago(hours=published) if published else None,
                 last_checked_at=ago(hours=checked))
    assert client.get("/api/incidents/r").json()["lifecycle"] == expected


# --- Re-checks, traceable runs and the timeline -------------------------------------------

def test_recheck_records_changed_unchanged_and_unreadable_pages_without_changing_status(client, tinyfish_network):
    pages = {"https://example.org/a": "First text", "https://example.org/b": "Same text"}
    tinyfish_network[SEARCH] = {"results": [{"url": url, "title": "NH-6", "snippet": "NH-6 blocked."} for url in [*pages, "https://example.org/c"]]}
    tinyfish_network[FETCH] = lambda request: {
        "results": [{"url": url, "text": pages[url]} for url in json.loads(request.data)["urls"] if url in pages],
        "errors": [{"url": url, "error": "404"} for url in json.loads(request.data)["urls"] if url not in pages]}
    run_id = client.post("/api/collection/run", json={"road": "NH-6"}).json()["run_id"]
    ids = {item["source_url"]: item["id"] for item in client.get("/api/incidents").json()}
    client.patch(f"/api/incidents/{ids['https://example.org/a']}/review", json={"verification": "confirmed", "review_note": "Checked"})

    pages["https://example.org/a"] = "Road reopened"
    body = client.post("/api/recheck", json={"incident_ids": list(ids.values())}).json()
    assert (body["checked"], body["fetched"], body["failed"], body["changed"]) == (3, 2, 1, 1)
    assert "An unreadable page does not mean the road has reopened." in body["message"]

    items = {item["source_url"]: item for item in client.get("/api/incidents").json()}
    changed, same, gone = items["https://example.org/a"], items["https://example.org/b"], items["https://example.org/c"]
    assert changed["verification"] == "confirmed"  # a re-check never changes the status
    assert changed["timeline"][0]["kind"] == "page_changed" and same["timeline"][0]["kind"] == "page_unchanged"
    assert gone["timeline"][0]["text"] == "Page could not be read. This does not mean the road has reopened: 404"
    assert gone["last_checked_at"] < same["last_checked_at"]  # only a successful read counts as a check
    assert changed["collection_run_id"] == run_id
    assert f"run {run_id.removeprefix('run_')[:8]}" in changed["timeline"][-1]["text"]


def test_recheck_without_ids_reads_only_reports_that_are_due(client, tinyfish_network, add_incident):
    add_incident("due", summary="Landslide on NH-6", published_at=ago(hours=40), last_checked_at=ago(hours=40))
    add_incident("recent", summary="Landslide on NH-6", published_at=ago(hours=2))
    add_incident("stale", summary="Landslide on NH-6", published_at=ago(days=10))
    body = client.post("/api/recheck").json()
    assert body["checked"] == 1
    fetched = [json.loads(request.data)["urls"] for host, request in tinyfish_network["calls"] if host == FETCH]
    assert fetched == [["https://example.org/due"]]
    assert client.get("/api/incidents/due").json()["lifecycle"] == "new"


def test_single_report_recheck(client, tinyfish_network, add_incident):
    add_incident("one")
    body = client.post("/api/incidents/one/recheck").json()
    assert body["timeline"][0]["kind"] == "page_read"
    assert client.post("/api/incidents/missing/recheck").status_code == 404


def test_timeline_keeps_every_step_newest_first(client, add_incident):
    add_incident("t", published_at="2026-10-01T06:00:00Z", collected_at="2026-10-02T00:00:00+00:00")
    client.post("/api/incidents/t/flags", json={"reason": "outdated", "note": "Reopened"})
    client.patch("/api/incidents/t/review", json={"verification": "resolved", "review_note": "District order"})
    kinds = [event["kind"] for event in client.get("/api/incidents/t").json()["timeline"]]
    assert kinds[:3] in (["review", "flag_closed", "flagged"], ["flag_closed", "review", "flagged"])
    assert kinds[-2:] == ["collected", "published"]


# --- Location-based duplicates ------------------------------------------------------------

def test_reviewer_located_reports_at_the_same_spot_and_time_are_grouped():
    base = {"published_at": "2026-10-22T08:00:00Z"}
    items = {item["id"]: item for item in annotate([
        report("a", "Landslide near the tunnel", latitude=25.2000, longitude=92.3500, **base),
        report("b", "Slip blocks the highway: landslide", latitude=25.2040, longitude=92.3510, **base),
        report("far", "Another landslide", latitude=25.2500, longitude=92.3500, **base),
    ])}
    assert items["a"]["duplicate_ids"] == ["b"]
    assert items["far"]["duplicate_ids"] == []


# --- Background collection ----------------------------------------------------------------

def test_background_collection_reports_progress_and_allows_one_run_at_a_time(client, tinyfish_network):
    release = threading.Event()

    def slow_search(request):
        release.wait(5)
        return {"results": [{"url": "https://example.org/bg", "title": "NH-6", "snippet": "NH-6 blocked."}]}
    tinyfish_network[SEARCH] = slow_search

    started = client.post("/api/collection/jobs", json={"road": "NH-6"})
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    running = client.get(f"/api/collection/runs/{run_id}").json()
    assert (running["status"], running["phase"], running["searches_done"]) == ("running", "searching", 0)
    assert client.post("/api/collection/jobs").status_code == 409
    assert client.post("/api/collection/run").status_code == 409

    release.set()
    run = wait_for_run(client, run_id)
    assert (run["status"], run["searches_done"], run["stored"]) == ("complete", 2, 1)
    assert run["message"].startswith("1 new reports from 2 searches")
    again = client.post("/api/collection/jobs")  # the lock is released
    assert again.status_code == 202
    wait_for_run(client, again.json()["run_id"])


def test_background_job_without_a_key_says_so(client):
    body = client.post("/api/collection/jobs")
    assert body.status_code == 200 and body.json()["status"] == "not_configured"


def test_runs_left_running_by_a_restart_are_marked_interrupted(client):
    with get_connection() as connection:
        connection.execute("""INSERT INTO collection_runs (id, trigger, started_at, finished_at, searches, results, stored,
            duplicates, failed_searches, fetched, fetch_failed, duration_ms, status) VALUES
            ('run_x', 'manual', '2026-10-24T00:00:00+00:00', '2026-10-24T00:00:00+00:00', '[]', 0, 0, 0, 0, 0, 0, 0, 'running')""")
    initialize_database()
    assert client.get("/api/collection/runs/run_x").json()["status"] == "interrupted"


# --- Monitoring ---------------------------------------------------------------------------

def test_metrics_count_only_what_was_measured(client, providers, tinyfish_network, add_incident):
    empty = client.get("/api/metrics").json()
    assert empty["evidence"]["freshness_lag_hours"] == {"n": 0, "median": None, "p90": None}
    assert empty["evidence"]["reviewer_kept_share"] == {"n": 0, "value": None}
    assert empty["routing"]["p50_s"] is None

    client.post("/api/routes/plan", json=ROUTE)
    client.post("/api/routes/plan", json=ROUTE)  # geocodes and route now come from the cache
    client.post("/api/routes/plan", json={**ROUTE, "origin": "Atlantis"})
    tinyfish_network[SEARCH] = {"results": [{"url": "https://example.org/m", "title": "NH-6", "snippet": "NH-6 blocked."}]}
    client.post("/api/collection/run", json={"road": "NH-6"})
    add_incident("kept", published_at="2026-10-20T00:00:00Z", collected_at="2026-10-21T00:00:00+00:00")
    add_incident("noise")
    client.patch("/api/incidents/kept/review", json={"verification": "confirmed", "review_note": "Real slide"})
    client.patch("/api/incidents/noise/review", json={"verification": "dismissed", "review_note": "Off corridor"})

    body = client.get("/api/metrics").json()
    providers_today = body["providers_today"]
    assert providers_today["osrm"]["by_outcome"] == {"ok": 1, "cache": 1}
    assert providers_today["tinyfish_search"]["units"] == 2 and providers_today["tinyfish_fetch"]["units"] == 1
    assert providers_today["tinyfish_fetch"]["free_daily_limit"] == 1000
    assert (body["routing"]["plans_7d"], body["routing"]["failed_7d"]) == (3, 1)
    assert body["evidence"]["freshness_lag_hours"] == {"n": 1, "median": 24.0, "p90": 24.0}
    assert body["evidence"]["reviewer_kept_share"] == {"n": 2, "value": 0.5}
    assert body["collection"]["runs_30d"] == 1


def test_a_page_found_by_several_searches_is_one_sighting_per_run(client, tinyfish_network):
    tinyfish_network[SEARCH] = {"results": [{"url": "https://example.org/x", "title": "NH-6", "snippet": "NH-6 blocked."}]}
    client.post("/api/collection/run", json={"road": "NH-6"})  # web and news both return it: found once
    client.post("/api/collection/run", json={"road": "NH-6"})  # a later run: seen again once
    kinds = [event["kind"] for event in client.get("/api/incidents").json()[0]["timeline"]]
    assert kinds.count("seen_again") == 1 and kinds.count("collected") == 1
