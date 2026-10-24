from app import road_intelligence

PLACES = {"Guwahati": (26.18, 91.75), "Shillong": (25.58, 91.88)}
# OSRM order: fastest first, but it passes a confirmed report; the second route avoids it.
OSRM = {"code": "Ok", "routes": [
    {"distance": 100000, "duration": 4000, "geometry": {"type": "LineString", "coordinates": [[91.75, 26.18], [91.80, 25.90], [91.88, 25.58]]}},
    {"distance": 120000, "duration": 4600, "geometry": {"type": "LineString", "coordinates": [[91.75, 26.18], [92.10, 25.90], [91.88, 25.58]]}},
]}


def fake_request_json(url, headers=None):
    if "nominatim" in url:
        name = next(place for place in PLACES if place in url)
        latitude, longitude = PLACES[name]
        return [{"display_name": name, "lat": str(latitude), "lon": str(longitude)}]
    if "project-osrm" in url:
        return OSRM
    raise AssertionError(f"Unexpected external request: {url}")


def plan(client, monkeypatch, priority):
    monkeypatch.setattr(road_intelligence, "_request_json", fake_request_json)
    response = client.post("/api/routes/plan", json={"origin": "Guwahati", "destination": "Shillong", "priority": priority})
    assert response.status_code == 200
    return response.json()


def test_cautious_plan_ranks_route_without_confirmed_reports_first(client, monkeypatch, add_incident):
    add_incident("slide", "confirmed", 25.90, 91.80)
    body = plan(client, monkeypatch, "cautious")
    assert [route["distance_m"] for route in body["routes"]] == [120000, 100000]
    assert body["recommendation"] == "proceed_cautiously"
    assert body["routes"][1]["recommendation"] == "consider_alternative"
    assert body["routes"][1]["exposure"]["nearby_ids"] == ["slide"]


def test_fastest_plan_keeps_fastest_route_and_explains_alternative(client, monkeypatch, add_incident):
    add_incident("slide", "confirmed", 25.90, 91.80)
    body = plan(client, monkeypatch, "fastest")
    assert body["routes"][0]["duration_s"] == 4000
    assert body["recommendation"] == "consider_alternative"
    assert "Route 2" in body["recommendation_reason"]


def test_plan_without_reports_requires_verification(client, monkeypatch):
    body = plan(client, monkeypatch, "balanced")
    assert body["recommendation"] == "verify_before_dispatch"


def test_review_sets_keeps_and_clears_location(client, add_incident):
    add_incident("r1")
    url = "/api/incidents/r1/review"
    located = client.patch(url, json={"verification": "confirmed", "review_note": "Checked source", "location_text": "Nongpoh", "latitude": 25.9, "longitude": 91.88})
    assert located.status_code == 200
    assert (located.json()["latitude"], located.json()["location_text"]) == (25.9, "Nongpoh")

    kept = client.patch(url, json={"verification": "confirmed", "review_note": "Status unchanged"})
    assert (kept.json()["latitude"], kept.json()["location_text"]) == (25.9, "Nongpoh")

    cleared = client.patch(url, json={"verification": "unknown", "review_note": "Wrong place", "location_text": None, "latitude": None, "longitude": None})
    assert cleared.json()["latitude"] is None and cleared.json()["location_text"] is None


def test_review_rejects_half_a_coordinate_pair(client, add_incident):
    add_incident("r2")
    response = client.patch("/api/incidents/r2/review", json={"verification": "confirmed", "review_note": "Checked", "latitude": 25.9})
    assert response.status_code == 422


def test_review_accepts_dismissed(client, add_incident):
    add_incident("r3")
    response = client.patch("/api/incidents/r3/review", json={"verification": "dismissed", "review_note": "Not a road report"})
    assert response.json()["verification"] == "dismissed"


def test_collection_without_key_does_not_invent_reports(client):
    body = client.post("/api/collection/run").json()
    assert body["status"] == "not_configured"
    assert body["incidents"] == []
    assert client.get("/api/incidents").json() == []


def test_provider_responses_are_cached_and_served_when_provider_fails(client, monkeypatch):
    calls = []
    def counting(url, headers=None):
        calls.append(url)
        return fake_request_json(url, headers)
    monkeypatch.setattr(road_intelligence, "_request_json", counting)
    first = client.post("/api/routes/plan", json={"origin": "Guwahati", "destination": "Shillong"}).json()
    assert len(calls) == 3
    client.post("/api/routes/plan", json={"origin": "Guwahati", "destination": "Shillong"})
    assert len(calls) == 3  # geocodes and route served from cache

    def failing(url, headers=None):
        raise road_intelligence.HTTPException(status_code=502, detail="down")
    monkeypatch.setattr(road_intelligence, "_request_json", failing)
    monkeypatch.setattr(road_intelligence, "ROUTE_CACHE_S", -1)  # force a refresh attempt
    fallback = client.post("/api/routes/plan", json={"origin": "Guwahati", "destination": "Shillong"}).json()
    assert fallback["routing_fetched_at"] == first["routing_fetched_at"]
