from datetime import datetime, timedelta, timezone

from app.road_intelligence import recommend, route_exposure

# Two east-west routes about 55 km apart.
SOUTH = {"coordinates": [[91.0, 26.0], [91.25, 26.0], [91.5, 26.0]]}
NORTH = {"coordinates": [[91.0, 26.5], [91.5, 26.5]]}
NOW = datetime.now(timezone.utc).isoformat()


def incident(incident_id, verification="unverified", latitude=None, longitude=None, freshness="unknown"):
    return {"id": incident_id, "verification": verification, "latitude": latitude,
            "longitude": longitude, "freshness": freshness}


def route(rank, geometry, incidents, duration_s=3600):
    return {"priority_rank": rank, "duration_s": duration_s, "exposure": route_exposure(geometry, incidents)}


def test_exposure_counts_nearby_reports_by_state():
    incidents = [
        incident("near-confirmed", "confirmed", 26.01, 91.2),   # ~1.1 km from SOUTH
        incident("near-stale", "unverified", 25.99, 91.4, "stale"),
        incident("far", "confirmed", 26.5, 91.2),               # on NORTH, ~55 km away
        incident("no-location"),
        incident("dismissed", "dismissed", 26.0, 91.3),
    ]
    exposure = route_exposure(SOUTH, incidents)
    assert exposure["nearby"] == {"confirmed": 1, "unverified": 1, "conflicting": 0, "unknown": 0}
    assert exposure["nearby_stale"] == 1
    assert sorted(exposure["nearby_ids"]) == ["near-confirmed", "near-stale"]
    assert exposure["located_reports"] == 3
    assert exposure["unlocated_reports"] == 1


def test_one_unlocated_report_does_not_hide_located_matches():
    exposure = route_exposure(SOUTH, [incident("near", "confirmed", 26.0, 91.1), incident("no-location")])
    assert exposure["nearby"]["confirmed"] == 1


def test_report_beyond_route_end_is_not_matched():
    exposure = route_exposure(SOUTH, [incident("east", "confirmed", 26.0, 91.6)])  # ~10 km past the end
    assert exposure["nearby"]["confirmed"] == 0


def test_confirmed_report_suggests_clean_alternative():
    incidents = [incident("blocked", "confirmed", 26.0, 91.2)]
    routes = [route(1, SOUTH, incidents), route(2, NORTH, incidents)]
    code, reasons = recommend(routes[0], routes, NOW)
    assert code == "consider_alternative"
    assert any("Route 2" in reason for reason in reasons)
    assert recommend(routes[1], routes, NOW)[0] == "proceed_cautiously"


def test_confirmed_reports_on_every_route_require_verification():
    incidents = [incident("a", "confirmed", 26.0, 91.2), incident("b", "confirmed", 26.5, 91.2)]
    routes = [route(1, SOUTH, incidents), route(2, NORTH, incidents)]
    assert recommend(routes[0], routes, NOW)[0] == "verify_before_dispatch"


def test_no_reports_is_not_treated_as_clear():
    routes = [route(1, SOUTH, [])]
    code, reasons = recommend(routes[0], routes, None)
    assert code == "verify_before_dispatch"
    assert any("does not mean the road is clear" in reason for reason in reasons)


def test_unlocated_or_unconfirmed_reports_require_verification():
    unlocated = [route(1, SOUTH, [incident("x")])]
    assert recommend(unlocated[0], unlocated, NOW)[0] == "verify_before_dispatch"
    nearby_unverified = [route(1, SOUTH, [incident("y", "unverified", 26.0, 91.2)])]
    assert recommend(nearby_unverified[0], nearby_unverified, NOW)[0] == "verify_before_dispatch"


def test_old_evidence_requires_verification():
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    routes = [route(1, SOUTH, [incident("far", "confirmed", 26.5, 91.2)])]
    assert recommend(routes[0], routes, old)[0] == "verify_before_dispatch"
    assert recommend(routes[0], routes, NOW)[0] == "proceed_cautiously"


def test_proceed_cautiously_never_claims_road_is_clear():
    routes = [route(1, SOUTH, [incident("dismissed", "dismissed")])]
    code, reasons = recommend(routes[0], routes, NOW)
    assert code == "proceed_cautiously"
    assert any("not confirmation that the road is clear" in reason for reason in reasons)
