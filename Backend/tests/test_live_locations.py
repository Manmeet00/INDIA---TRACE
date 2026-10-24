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
