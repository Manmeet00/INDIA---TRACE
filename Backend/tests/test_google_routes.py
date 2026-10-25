"""Google Routes: used when GOOGLE_MAPS_API_KEY is set, turned into the backend's route shape, OSRM when it fails."""
import json
from urllib.error import HTTPError
from io import BytesIO

import pytest

from app.config import get_settings
from conftest import ROUTE_LINES, encode_polyline

GOOGLE = "routes.googleapis.com"
PLAN = {"origin": "Guwahati", "destination": "Shillong", "vehicle_type": "car", "priority": "fastest"}


def step(maneuver, text, metres, lon, lat):
    return {"distanceMeters": metres, "staticDuration": f"{metres // 10}s",
            "startLocation": {"latLng": {"latitude": lat, "longitude": lon}},
            "navigationInstruction": {"maneuver": maneuver, "instructions": text}}


def google_answer(request):
    return {"routes": [{
        "distanceMeters": 98000, "duration": "10800s", "staticDuration": "9300s",
        "polyline": {"encodedPolyline": encode_polyline(ROUTE_LINES[0], precision=5)},
        "legs": [{"endLocation": {"latLng": {"latitude": 25.58, "longitude": 91.88}}, "steps": [
            step("DEPART", "Head south on GS Rd/NH 6 toward Khanapara\nPass by Big Bazaar (on the left)", 60000, 91.75, 26.18),
            step("TURN_RIGHT", "Turn right onto Mawlai Bypass", 30000, 91.80, 25.90),
            step(None, "At the roundabout, take the 2nd exit onto Police Bazar Rd", 8000, 91.86, 25.60),
        ]}],
    }]}


@pytest.fixture
def google(client, providers, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-google-key")
    get_settings.cache_clear()
    providers[GOOGLE] = google_answer
    yield providers
    get_settings.cache_clear()


def test_with_a_key_routes_and_times_come_from_google_with_traffic(client, google):
    plan = client.post("/api/routes/plan", json=PLAN).json()
    assert plan["routing_provider"] == "google" and plan["traffic"] is True and plan["routing_note"] is None
    assert "Google's estimates for a car with traffic" in plan["data_note"]
    route = plan["routes"][0]
    assert (route["distance_m"], route["duration_s"], route["duration_no_traffic_s"]) == (98000, 10800, 9300)
    assert route["geometry"]["coordinates"][0] == [91.75, 26.18]
    assert route["highways"] == {"NH-6": 60000}
    assert [(s["type"], s["modifier"], s["name"], s["instruction"]) for s in route["steps"][:2]] == [
        ("depart", None, "GS Rd/NH 6", "Head south on GS Rd/NH 6 toward Khanapara"),
        ("turn", "right", "Mawlai Bypass", "Turn right onto Mawlai Bypass")]
    assert route["steps"][2]["exit"] == 2 and route["steps"][2]["name"] == "Police Bazar Rd"
    assert route["steps"][-1]["type"] == "arrive" and route["steps"][-1]["location"] == [91.88, 25.58]

    # The key goes in a header, never into the cache or the answer.
    request = next(request for host, request in google["calls"] if host == GOOGLE)
    assert request.get_header("X-goog-api-key") == "test-google-key"
    assert json.loads(request.data)["routingPreference"] == "TRAFFIC_AWARE"
    assert "test-google-key" not in json.dumps(plan)


def test_without_a_key_osrm_is_used_and_says_it_has_no_traffic(client, providers):
    plan = client.post("/api/routes/plan", json=PLAN).json()
    assert plan["routing_provider"] == "osrm" and plan["traffic"] is False
    assert "without live traffic" in plan["data_note"]
    assert not any(host == GOOGLE for host, _ in providers["calls"])


def test_when_google_refuses_the_key_osrm_is_used_with_googles_reason(client, google):
    body = json.dumps({"error": {"code": 403, "message": "Routes API has not been used in project 123 before or it is disabled."}})
    google[GOOGLE] = lambda request: HTTPError(request.full_url, 403, "Forbidden", {}, BytesIO(body.encode()))
    plan = client.post("/api/routes/plan", json=PLAN).json()
    assert plan["routing_provider"] == "osrm" and plan["traffic"] is False
    assert "Routes API has not been used in project 123" in plan["routing_note"]
    assert plan["routing_note"].endswith("Times are OSRM estimates without traffic.")
    assert plan["routes"][0]["duration_s"] == 4000  # OSRM's, not a guess


def test_old_traffic_times_are_never_served_when_google_fails(client, google, monkeypatch):
    first = client.post("/api/routes/plan", json=PLAN).json()
    assert first["routing_provider"] == "google"
    monkeypatch.setattr("app.google_routes.CACHE_S", -1)  # the cached answer is now too old for traffic
    google[GOOGLE] = TimeoutError("timed out")
    again = client.post("/api/routes/plan", json=PLAN).json()
    assert again["routing_provider"] == "osrm"


def test_a_bike_gets_googles_two_wheeler_routes(client, google):
    plan = client.post("/api/routes/plan", json={**PLAN, "vehicle_type": "bike"}).json()
    request = next(request for host, request in google["calls"] if host == GOOGLE)
    assert json.loads(request.data)["travelMode"] == "TWO_WHEELER"
    assert "for a two-wheeler with traffic" in plan["data_note"] and plan["routing_note"] is None
    car = client.post("/api/routes/plan", json=PLAN).json()  # a different request, so not the bike's cached answer
    assert json.loads([request for host, request in google["calls"] if host == GOOGLE][-1].data)["travelMode"] == "DRIVE"
    assert car["vehicle_type"] == "car"


def test_without_google_a_bike_is_told_it_gets_the_car_route_and_a_truck_that_trucks_are_slower(client, providers):
    bike = client.post("/api/routes/plan", json={**PLAN, "vehicle_type": "bike"}).json()
    assert bike["routing_note"] == "OSRM has no two-wheeler routes, so this is the car route and time; a bike may take other roads."
    truck = client.post("/api/routes/plan", json={**PLAN, "vehicle_type": "truck"}).json()
    assert truck["routing_note"] == "Times are for a car; trucks are usually slower, and truck restrictions are not checked."
    assert client.post("/api/routes/plan", json=PLAN).json()["routing_note"] is None
