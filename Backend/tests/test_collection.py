import pytest

from app import collection
from app.config import get_settings

# Shapes copied from live TinyFish responses (24 Oct 2026): web results have no date,
# news results add "publisher" and "date", Fetch adds "description", "text" and "published_date".
WEB = [
    {"url": "https://www.facebook.com/NortheastToday/posts/1/", "title": "Landslide on NH-6", "snippet": "NH-6 blocked at Kuliang.", "site_name": "www.facebook.com"},
    {"url": "https://example.org/a?utm_source=x", "title": "NH-306 closed", "snippet": "NH-306 closed near Aizawl.", "site_name": "example.org"},
    {"url": "javascript:alert(1)", "title": "Unsafe", "snippet": "Not stored."},
    {"url": "https://example.org/empty", "title": "No snippet", "snippet": ""},
]
NEWS = [{"url": "https://www.ndtv.com/landslide", "title": "Landslide hits fuel station", "snippet": "Jorabat landslide.",
         "site_name": "www.ndtv.com", "publisher": "NDTV", "date": "3 weeks ago"}]


@pytest.fixture
def tinyfish(client, monkeypatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")
    get_settings.cache_clear()
    calls = []

    def fake(url, headers=None, body=None, timeout=15):
        calls.append(url)
        assert headers == {"X-API-Key": "test-key"}
        if url.startswith(collection.SEARCH_URL):
            return {"results": NEWS if "domain_type=news" in url else WEB}
        assert url == collection.FETCH_URL and len(body["urls"]) <= collection.FETCH_BATCH
        return {
            "results": [{"url": u, "description": "Landslide at 10th Mile along National Highway-27", "text": "Page text",
                         "author": None, "published_date": "2026-10-20T03:00:00Z" if "facebook" in u else None}
                        for u in body["urls"] if "example.org" not in u],
            "errors": [{"url": u, "error": "blocked"} for u in body["urls"] if "example.org" in u],
        }
    monkeypatch.setattr(collection, "_request_json", fake)
    return calls


def incidents_by_url(client):
    return {item["source_url"]: item for item in client.get("/api/incidents").json()}


def test_targeted_collection_searches_web_and_news_then_fetches_pages(client, tinyfish):
    body = client.post("/api/collection/run", json={"road": "NH-6", "place": "Sonapur", "event_type": "landslide", "window_days": 7}).json()
    assert body["collected"] == 3
    searches = [url for url in tinyfish if url.startswith(collection.SEARCH_URL)]
    assert len(searches) == 2 and "domain_type=news" in searches[1]
    assert all("NH-6+Sonapur+landslide+road+update" in url and "recency_minutes=10080" in url for url in searches)

    items = incidents_by_url(client)
    facebook = items["https://www.facebook.com/NortheastToday/posts/1"]
    assert (facebook["published_at"], facebook["published_source"]) == ("2026-10-20T03:00:00Z", "page")
    assert "NH-27" in facebook["mentions"]["highways"]  # from the fetched page description
    assert facebook["search_kind"] == "web" and facebook["search_query"].startswith("NH-6 Sonapur")
    news = items["https://www.ndtv.com/landslide"]
    assert (news["source_name"], news["published_at"], news["published_source"]) == ("NDTV", "3 weeks ago", "search")
    assert items["https://example.org/a"]["fetch_error"] == "blocked"

    run = client.get("/api/collection/runs").json()[0]
    assert (run["trigger"], run["stored"], run["fetched"], run["fetch_failed"], run["recency_minutes"], run["status"]) == ("targeted", 3, 2, 1, 10080, "complete")


def test_repeat_collection_records_recheck_instead_of_duplicating(client, tinyfish):
    client.post("/api/collection/run", json={"road": "NH-6"})
    first_seen = incidents_by_url(client)["https://www.ndtv.com/landslide"]["last_seen_at"]
    body = client.post("/api/collection/run", json={"road": "NH-6"}).json()
    assert (body["collected"], body["duplicates"]) == (0, 3)
    assert incidents_by_url(client)["https://www.ndtv.com/landslide"]["last_seen_at"] > first_seen
    assert len(client.get("/api/incidents").json()) == 3


def test_failed_search_is_retried_once(client, tinyfish, monkeypatch):
    fake = collection._request_json
    failures = []

    def flaky(url, headers=None, body=None, timeout=15):
        if url.startswith(collection.SEARCH_URL) and not failures:
            failures.append(url)
            raise collection.HTTPException(status_code=502, detail="timeout")
        return fake(url, headers, body, timeout)
    monkeypatch.setattr(collection, "_request_json", flaky)
    monkeypatch.setattr(collection.time, "sleep", lambda seconds: None)
    assert client.post("/api/collection/run", json={"road": "NH-6"}).json()["status"] == "complete"


def test_all_searches_failing_is_logged_and_reported(client, tinyfish, monkeypatch):
    def down(url, headers=None, body=None, timeout=15):
        raise collection.HTTPException(status_code=502, detail="down")
    monkeypatch.setattr(collection, "_request_json", down)
    monkeypatch.setattr(collection.time, "sleep", lambda seconds: None)
    assert client.post("/api/collection/run").status_code == 502
    run = client.get("/api/collection/runs").json()[0]
    assert (run["status"], run["failed_searches"], run["stored"]) == ("failed", len(collection.PILOT_SEARCHES), 0)


def test_targeted_search_rejects_unknown_event_type(client):
    assert client.post("/api/collection/run", json={"event_type": "earthquake"}).status_code == 422
