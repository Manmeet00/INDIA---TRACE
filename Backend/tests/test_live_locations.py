"""Real, approximate locations from the towns reports name (app/places.py) and the live collection schedule."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import get_settings
from app.database import get_connection
from app.evidence import annotate
from app.regions import NORTHEAST
from test_report_features import ago, report

# Test coordinates: "Jorabat" sits 1 km from the fake Guwahati–Shillong route in conftest.
POINTS = {"Jorabat": (26.0, 91.787), "Shillong": (25.574, 91.881), "Guwahati": (26.18, 91.75)}
ROUTE = {"origin": "Guwahati", "destination": "Shillong"}


@pytest.mark.parametrize("text, expected", [
    ("Landslide on NH-6 at Jorabat", "Jorabat"),                               # one town
    ("Guwahati-Shillong road blocked near Jorabat", "Jorabat"),                # several towns, one after "near"
    ("Traffic from Guwahati to Shillong is slow", "Guwahati"),                 # "from" names the first
    ("Guwahati and Shillong traffic update", None),                            # several towns, no cue: ambiguous
    ("Slide at Sonapur tunnel", None),                                         # Sonapur is in two states: never placed
    ("Floods across Barak Valley and Cachar", None),                           # areas, not towns
    ("Road cut near Cherrapunji", "Sohra"),                                    # alternate spelling, placed as the town
])
def test_the_town_a_report_is_about(text, expected):
    item = annotate([report("a", text)], {**POINTS, "Sohra": (25.27, 91.73)})[0]
    assert (item["approximate_location"] or {}).get("place") == expected
    assert item["location_confidence"] == ("approximate" if expected else item["location_confidence"])


def test_a_town_without_looked_up_coordinates_is_not_placed():
    item = annotate([report("a", "Landslide at Jorabat")], {})[0]
    assert item["approximate_location"] is None


def test_place_lookup_stores_results_and_respects_the_rate_limit(client, providers, add_incident, monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.places.time.sleep", sleeps.append)
    queries = []

    def nominatim(request):
        query = parse_qs(urlsplit(request.full_url).query)["q"][0]
        queries.append(query)
        name = query.split(",")[0]
        return [{"lat": str(POINTS[name][0]), "lon": str(POINTS[name][1]), "display_name": query}] if name in POINTS else []
    providers["nominatim.openstreetmap.org"] = nominatim
    add_incident("j", summary="Landslide on NH-6 at Jorabat")
    add_incident("k", summary="Slide near Kolasib")             # Nominatim finds nothing: recorded, not placed
    add_incident("s", summary="Slide at Sonapur tunnel")        # never looked up
    body = client.post("/api/places/locate").json()
    assert body == {"looked_up": 2, "found": 1, "not_found": 1, "failed": 0}
    assert sorted(queries) == ["Jorabat, Assam, India", "Kolasib, Kolasib, Mizoram, India"]
    assert sleeps == [1.1]  # one request per second
    items = {item["id"]: item for item in client.get("/api/incidents").json()}
    assert items["j"]["approximate_location"] == {"place": "Jorabat", "latitude": 26.0, "longitude": 91.787}
    assert items["j"]["location_confidence"] == "approximate"
    assert items["k"]["approximate_location"] is None
    assert client.post("/api/places/locate").json()["looked_up"] == 0  # nothing is looked up twice


def place(name):
    with get_connection() as connection:
        connection.execute("INSERT INTO place_locations (name, latitude, longitude, geocoded_at) VALUES (?, ?, ?, ?)",
                           (name, *POINTS[name], ago(seconds=0)))


def test_town_placed_reports_count_for_a_route_but_never_as_confirmed(client, providers, add_incident):
    place("Jorabat")
    add_incident("j", "confirmed", summary="NH-6 blocked by a landslide at Jorabat", published_at=ago(hours=2))
    route = client.post("/api/routes/plan", json=ROUTE).json()["routes"][0]
    exposure = route["exposure"]
    assert exposure["nearby"]["confirmed"] == 0  # a town is not a reviewer-confirmed spot
    assert exposure["place_matches"] == {"Jorabat": ["j"]} and exposure["highway_mentions"] == {}
    assert route["recommendation"] == "verify_before_dispatch"
    assert any("names a town on this route (Jorabat)" in reason and "not the exact spot" in reason for reason in route["recommendation_reasons"])
    impact = route["impact_reports"][0]
    assert impact["match"] == "place" and "approximate: the town, not the exact spot" in impact["factors"][0]


def test_a_town_far_from_the_route_does_not_match(client, providers, add_incident):
    with get_connection() as connection:
        connection.execute("INSERT INTO place_locations (name, latitude, longitude, geocoded_at) VALUES ('Aizawl', 23.73, 92.72, ?)", (ago(seconds=0),))
    add_incident("a", summary="Landslide at Aizawl")
    exposure = client.post("/api/routes/plan", json=ROUTE).json()["routes"][0]["exposure"]
    assert exposure["place_matches"] == {} and exposure["unlocated_reports"] == 1


def test_route_plans_keep_the_names_people_typed(client, providers):
    body = client.post("/api/routes/plan", json={"origin": "  Guwahati ", "destination": "Shillong"}).json()
    assert (body["origin"]["query"], body["destination"]["query"]) == ("Guwahati", "Shillong")
    assert body["origin"]["name"] == "Guwahati, India"  # the geocoder's own name is kept too


def test_health_reports_the_collection_schedule(client, monkeypatch):
    assert client.get("/api/health").json()["collection_interval_minutes"] == 0
    monkeypatch.setenv("COLLECTION_INTERVAL_MINUTES", "30")
    get_settings.cache_clear()
    body = client.get("/api/health").json()
    assert body["collection_interval_minutes"] == 30 and "next_collection_at" in body


def test_collection_places_the_towns_new_reports_name(client, tinyfish_network):
    tinyfish_network[SEARCH_HOST] = {"results": [{"url": "https://example.org/jorabat", "title": "NH-6", "snippet": "NH-6 blocked at Jorabat."}]}
    tinyfish_network["nominatim.openstreetmap.org"] = lambda request: [{"lat": "26.106", "lon": "91.866", "display_name": "Jorabat"}]
    body = client.post("/api/collection/run", json={"road": "NH-6"}).json()
    assert "1 newly named towns placed on the map (approximate)." in body["message"]
    assert client.get("/api/incidents").json()[0]["approximate_location"]["place"] == "Jorabat"


SEARCH_HOST = "api.search.tinyfish.ai"


def test_a_restart_waits_for_the_next_due_collection(client):
    from app.main import _seconds_until_due
    assert _seconds_until_due(30) == 0  # nothing collected yet: collect now
    with get_connection() as connection:
        connection.execute("""INSERT INTO collection_runs (id, trigger, started_at, finished_at, searches, results, stored,
            duplicates, failed_searches, fetched, fetch_failed, duration_ms, status) VALUES
            ('run_recent', 'scheduled', ?, ?, '[]', 0, 0, 0, 0, 0, 0, 0, 'complete')""", (ago(minutes=10), ago(minutes=10)))
    assert 1190 <= _seconds_until_due(30) <= 1200  # 20 minutes left



def test_suggestions_put_region_towns_first_and_keep_only_places_in_india(client, providers):
    providers["photon.komoot.io"] = {"features": [
        {"properties": {"name": "Tezpur University", "city": "Tezpur", "state": "Assam", "countrycode": "IN"}},
        {"properties": {"name": "Tezpur", "state": "Assam", "countrycode": "IN"}},                 # same as the region town
        {"properties": {"name": "Tezpur Street", "state": "Somewhere", "countrycode": "US"}},
        "not a feature", {"properties": {"name": 5, "countrycode": "IN"}},
    ]}
    body = client.get("/api/places/suggest?q=Tezpu").json()
    assert [(item["label"], item["value"], item["source"]) for item in body] == [
        ("Tezpur", "Tezpur, Assam", "region"), ("Tezpur University", "Tezpur University, Assam", "search")]
    assert client.get("/api/places/suggest?q=T").status_code == 422


def test_a_chosen_suggestion_is_routed_from_its_own_coordinates(client, providers):
    providers["photon.komoot.io"] = {"features": [
        {"properties": {"name": "Shillong Peak", "state": "Meghalaya", "countrycode": "IN"},
         "geometry": {"type": "Point", "coordinates": [91.8806, 25.5455]}},
        {"properties": {"name": "Shillong Road", "state": "Nowhere", "countrycode": "IN"},
         "geometry": {"type": "Point", "coordinates": [-0.12, 51.5]}},  # not in India: never used as a position
    ]}
    assert [item["value"] for item in client.get("/api/places/suggest?q=Shillong").json()] == [
        "Shillong, Meghalaya", "Shillong Peak, Meghalaya", "Shillong Road, Nowhere"]
    assert "point" not in client.get("/api/places/suggest?q=Shillong").json()[1]
    body = client.post("/api/routes/plan", json={"origin": "26.18000, 91.75000", "destination": "shillong peak, Meghalaya"}).json()
    assert (body["destination"]["latitude"], body["destination"]["longitude"]) == (25.5455, 91.8806)
    assert body["destination"]["name"] == "shillong peak, Meghalaya, India"
    assert not any(host == "nominatim.openstreetmap.org" for host, _ in providers["calls"])  # no second lookup by name
    client.post("/api/routes/plan", json={"origin": "26.18000, 91.75000", "destination": "Shillong Road, Nowhere"})
    assert any(host == "nominatim.openstreetmap.org" for host, _ in providers["calls"])  # its point was outside India


def test_a_town_is_routed_to_the_town_not_the_middle_of_its_district(client, providers):
    # OpenStreetMap's best match for "Patiala, Punjab" is the district, whose centre is 13 km south of the city.
    district = {"category": "boundary", "type": "administrative", "display_name": "Patiala, Punjab, India", "lat": "30.2092778", "lon": "76.3397231"}
    city = {"category": "place", "type": "city", "display_name": "Patiala, Patiala Tahsil, Punjab, India", "lat": "30.3301995", "lon": "76.4007656"}
    providers["nominatim.openstreetmap.org"] = lambda request: [district, city] if "Patiala" in request.full_url else [
        {"category": "boundary", "type": "national_park", "display_name": "Kaziranga National Park, Assam, India", "lat": "26.6581", "lon": "93.3927"}]
    body = client.post("/api/routes/plan", json={"origin": "26.18000, 91.75000", "destination": "Patiala, Punjab"}).json()
    assert (body["destination"]["latitude"], body["destination"]["longitude"]) == (30.3301995, 76.4007656)
    assert "limit=5" in next(request.full_url for host, request in providers["calls"] if host == "nominatim.openstreetmap.org")
    park = client.post("/api/routes/plan", json={"origin": "26.18000, 91.75000", "destination": "Kaziranga National Park"}).json()
    assert park["destination"]["latitude"] == 26.6581  # no settlement of that name: the place itself

    providers["photon.komoot.io"] = {"features": [
        {"properties": {"name": "Patiala", "state": "Punjab", "countrycode": "IN", "osm_key": "boundary", "osm_value": "administrative"},
         "geometry": {"type": "Point", "coordinates": [76.3397231, 30.2092778]}},
        {"properties": {"name": "Patiala", "state": "Punjab", "countrycode": "IN", "osm_key": "place", "osm_value": "city"},
         "geometry": {"type": "Point", "coordinates": [76.4007656, 30.3301995]}},
    ]}
    assert [item["value"] for item in client.get("/api/places/suggest?q=Patiala").json()] == ["Patiala, Punjab"]
    providers["nominatim.openstreetmap.org"] = lambda request: []  # the suggestion's own point is used
    chosen = client.post("/api/routes/plan", json={"origin": "26.18000, 91.75000", "destination": "Patiala, Punjab"}).json()
    assert (chosen["destination"]["latitude"], chosen["destination"]["longitude"]) == (30.3301995, 76.4007656)


def test_routes_carry_turn_by_turn_steps_for_navigation(client, providers):
    from conftest import osrm

    def with_steps(request):
        answer = osrm(request)
        answer["routes"][0]["legs"] = [{"steps": [
            {"name": "", "distance": 120.4, "duration": 20, "maneuver": {"type": "depart", "modifier": "right", "bearing_after": 198, "location": [91.75, 26.18]}},
            {"name": "GS Road", "ref": "NH6", "distance": 90000, "duration": 4000, "maneuver": {"type": "turn", "modifier": "left", "location": [91.76, 26.17]}},
            {"name": "", "distance": 300, "duration": 30, "maneuver": {"type": "roundabout", "modifier": "right", "exit": 2, "location": [91.87, 25.6]}},
            {"name": "Broken", "distance": 10, "maneuver": {"type": "turn", "location": ["x", 1]}},  # no usable point: left out
            {"name": "", "distance": 0, "duration": 0, "maneuver": {"type": "arrive", "location": [91.88, 25.58]}},
        ]}]
        return answer
    providers["router.project-osrm.org"] = with_steps
    body = client.post("/api/routes/plan", json={"origin": "26.18000, 91.75000", "destination": "Shillong", "priority": "balanced"}).json()
    steps = body["routes"][0]["steps"]
    assert [step["type"] for step in steps] == ["depart", "turn", "roundabout", "arrive"]
    assert steps[1] == {"type": "turn", "modifier": "left", "exit": None, "bearing_after": None, "name": "GS Road", "ref": "NH6",
                        "distance_m": 90000.0, "duration_s": 4000.0, "location": [91.76, 26.17]}
    assert steps[2]["exit"] == 2 and steps[0]["bearing_after"] == 198
    assert body["routes"][1]["steps"] == []  # OSRM sent no maneuvers for it: nothing is made up


TOLL_LIST = """data_as_on,state,toll_plaza_code,toll_plaza_name,toll_plaza_type,project_implementation_unit,regional_office,latitude,longitude
03-08-2026,Meghalaya,TP2,Umiam,Public Funded,PIU Shillong,RO Shillong,25.75,91.8395
03-08-2026,Assam,TP1,Jorabat,BOT,PIU Guwahati,RO Guwahati,26.0993,91.7643
03-08-2026,Assam,TP3,Far Away,BOT,PIU Guwahati,RO Guwahati,26.10,91.95
03-08-2026,Assam,TP4,No Position,BOT,PIU Guwahati,RO Guwahati,,
"""


def test_routes_list_the_nhai_toll_plazas_they_pass_without_prices(client, providers, tmp_path):
    body = client.post("/api/routes/plan", json={"origin": "Guwahati", "destination": "Shillong", "priority": "balanced"}).json()
    assert body["routes"][0]["tolls"]["status"] == "unknown"  # no list: unknown, never "no tolls"
    assert body["routes"][0]["tolls"]["plazas"] == []

    (tmp_path / "toll_plazas.csv").write_text(TOLL_LIST, encoding="utf-8")
    body = client.post("/api/routes/plan", json={"origin": "Guwahati", "destination": "Shillong", "priority": "balanced"}).json()
    tolls = next(route for route in body["routes"] if route["id"] == "route-1")["tolls"]
    assert tolls["status"] == "listed" and tolls["as_of"] == "03-08-2026"
    assert [plaza["name"] for plaza in tolls["plazas"]] == ["Jorabat", "Umiam"]  # in driving order; Far Away is 15 km off
    jorabat = tolls["plazas"][0]
    assert jorabat["code"] == "TP1" and jorabat["metres_from_route"] <= 400 and 0 < jorabat["km_from_start"] < tolls["plazas"][1]["km_from_start"]
    assert not any("price" in key or "fee" in key or "rate" in key for plaza in tolls["plazas"] for key in plaza)  # never guessed
    assert "prices are not in this list" in tolls["note"]


def test_suggestions_still_offer_region_towns_when_photon_is_down(client, providers):
    providers["photon.komoot.io"] = TimeoutError("timed out")
    assert [item["label"] for item in client.get("/api/places/suggest?q=Shil").json()] == ["Shillong"]


def test_a_device_position_plans_from_your_location_and_must_be_in_india(client, providers):
    body = client.post("/api/routes/plan", json={"origin": "26.18000, 91.75000", "destination": "Shillong"}).json()
    assert body["origin"] == {"name": "Your location", "latitude": 26.18, "longitude": 91.75, "query": "Your location"}
    assert not any("nominatim" in host and "26.18" in request.full_url for host, request in providers["calls"])  # never looked up
    outside = client.post("/api/routes/plan", json={"origin": "51.5, -0.12", "destination": "Shillong"})
    assert outside.status_code == 422 and outside.json()["detail"] == "That position is outside India."


def test_air_quality_at_a_point_is_banded_and_cached(client, providers):
    body = client.get("/api/air-quality?lat=26.1445&lon=91.7362").json()
    assert (body["us_aqi"], body["band"], body["pm2_5"]) == (97, "Moderate", 26.8)
    client.get("/api/air-quality?lat=26.1449&lon=91.7358")  # within about 1 km: the cached answer
    assert sum(host == "air-quality-api.open-meteo.com" for host, _ in providers["calls"]) == 1
    assert client.get("/api/air-quality?lat=51.5&lon=-0.12").json()["detail"] == "Air quality is shown for places in India only."
    providers["air-quality-api.open-meteo.com"] = {"current": {"us_aqi": None}}
    missing = client.get("/api/air-quality?lat=25.57&lon=91.88")
    assert missing.status_code == 502 and "no air quality value" in missing.json()["detail"]
