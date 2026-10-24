from datetime import datetime, timedelta, timezone

from app.evidence import freshness
from app.road_intelligence import _route_highways, impact_reports, parse_published, recommend, route_coverage, route_exposure

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


def test_parse_published_handles_search_result_formats():
    collected = "2026-10-24T12:00:00+00:00"
    exact, approximate = parse_published("2026-10-24T08:30:00Z", collected)
    assert exact == datetime(2026, 10, 24, 8, 30, tzinfo=timezone.utc) and not approximate
    assert parse_published("3 months ago", collected) == (datetime(2026, 7, 26, 12, tzinfo=timezone.utc), True)
    assert parse_published("an hour ago", collected)[0] == datetime(2026, 10, 24, 11, tzinfo=timezone.utc)
    assert parse_published("Jul 3, 2023", collected) == (datetime(2023, 7, 3, tzinfo=timezone.utc), True)
    assert parse_published("2024-05-29", collected) == (datetime(2024, 5, 29, tzinfo=timezone.utc), True)
    assert parse_published("sometime last monsoon", collected) == (None, False)
    assert parse_published(None, collected) == (None, False)


def test_freshness_uses_estimated_publication_time():
    now = datetime.now(timezone.utc)
    assert freshness(now - timedelta(hours=2), False) == "fresh"
    assert freshness(now - timedelta(days=90), True) == "stale"
    assert freshness(now + timedelta(hours=5), True) == "fresh"   # date-only value in a timezone ahead of UTC
    assert freshness(now + timedelta(hours=5), False) == "unknown"
    assert freshness(None, False) == "unknown"


def test_route_highways_sums_distance_and_ignores_short_crossings():
    route = {"legs": [{"steps": [
        {"ref": "NH27", "distance": 1500}, {"ref": "NH6;NH27", "distance": 40000},
        {"ref": "NH 6", "distance": 30000}, {"ref": "MDR32", "distance": 9000}, {"ref": "NH715", "distance": 300},
    ]}]}
    assert _route_highways(route) == {"NH-27": 41500, "NH-6": 70000}


def test_unlocated_reports_naming_a_route_highway_are_low_confidence_mentions():
    on_nh6 = {**incident("nh6", freshness="stale"), "mentions": {"highways": ["NH-6"], "places": []}}
    elsewhere = {**incident("nh37"), "mentions": {"highways": ["NH-37"], "places": []}}
    located_nh6 = {**incident("located", "unverified", 26.5, 91.2), "mentions": {"highways": ["NH-6"], "places": []}}
    exposure = route_exposure(SOUTH, [on_nh6, elsewhere, located_nh6], {"NH-6": 70000})
    assert exposure["highway_mentions"] == {"NH-6": ["nh6"]}
    assert exposure["highway_mentions_stale"] == 1
    routes = [{"priority_rank": 1, "duration_s": 60, "exposure": exposure}]
    code, reasons = recommend(routes[0], routes, NOW)
    assert code == "verify_before_dispatch"
    assert reasons[0] == "1 report without a confirmed location mentions NH-6, which this route uses (1 past their freshness window). Where on the road is not known."
    assert reasons[1].startswith("1 other report has no reviewer-confirmed location")


def test_impact_reports_rank_precise_recent_confirmed_above_road_mentions():
    near = {**incident("near", "confirmed", 26.005, 91.2, "fresh"), "event_type": "landslide", "freshness_window_h": 72,
            "corroborating_ids": [], "conflict_ids": [], "evidence_status": "confirmed", "title": "Slide", "source_name": "A",
            "source_url": "https://a.example", "published_at": None, "mentions": {"highways": [], "places": []}}
    named = {**incident("named", freshness="stale"), "event_type": "closure", "freshness_window_h": 48, "corroborating_ids": [],
             "conflict_ids": [], "evidence_status": "stale", "title": "NH-6 closed", "source_name": "B",
             "source_url": "https://b.example", "published_at": "2 years ago", "mentions": {"highways": ["NH-6"], "places": []}}
    exposure = route_exposure(SOUTH, [near, named], {"NH-6": 50000})
    reports = impact_reports(exposure, {"near": near, "named": named})
    assert [report["id"] for report in reports] == ["near", "named"]
    assert reports[0]["match"] == "precise" and reports[0]["factors"][0].endswith("(reviewer-confirmed location)")
    assert reports[1]["factors"][0] == "Names NH-6, which this route uses; where on the road is not known"
    assert reports[1]["factors"][1].startswith("Published more than 48 h ago")
    assert reports[0]["score"] > reports[1]["score"]


def test_coverage_marks_highways_without_recent_reports_as_gaps():
    reports = [{"verification": "unverified", "freshness": "stale", "mentions": {"highways": ["NH-6"]}},
               {"verification": "dismissed", "freshness": "fresh", "mentions": {"highways": ["NH-27"]}}]
    coverage = route_coverage({"NH-27": 6000, "NH-6": 80000}, reports)
    assert coverage["highways"] == [{"highway": "NH-27", "km": 6, "reports": 0, "fresh": 0}, {"highway": "NH-6", "km": 80, "reports": 1, "fresh": 0}]
    assert coverage["note"].startswith("No reports within their freshness window for NH-27 (6 km), NH-6 (80 km)")
    assert "not evidence that the road is clear" in coverage["note"]


def test_resolved_reports_no_longer_count_against_a_route():
    exposure = route_exposure(SOUTH, [incident("reopened", "resolved", 26.0, 91.2)])
    assert exposure["nearby"]["confirmed"] == 0 and exposure["located_reports"] == 0
