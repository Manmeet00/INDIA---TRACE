from app.evidence import annotate, normalize_source_url
from app.road_intelligence import parse_published

COLLECTED = "2026-10-24T12:00:00+00:00"


def report(incident_id, title, summary, published_at=None):
    estimate, _ = parse_published(published_at, COLLECTED)
    return {"id": incident_id, "title": title, "summary": summary, "published_at": published_at, "published_estimate": estimate}


def by_id(incidents):
    return {item["id"]: item for item in annotate(incidents)}


def test_same_truncated_title_with_different_stories_is_not_a_duplicate():
    title = "Continuous heavy rainfall has triggered multiple landslides that ..."
    items = by_id([
        report("a", title, "National Highway 10 was temporarily closed to vehicular movement at Bardang, 20th Mile, following a severe morning mudslide."),
        report("b", title, "Landslides have severely damaged sections of the Jeypore-Deomali National Highway (NH-315A) in Arunachal."),
    ])
    assert items["a"]["duplicate_ids"] == []


def test_reposted_story_is_grouped_as_duplicate():
    text = "Traffic movement along National Highway-2 at Khisama has come to a severe standstill following recurring landslide disruptions near Kohima."
    items = by_id([report("a", "Khisama standstill", text), report("b", "Khisama standstill", text + " Updated."), report("c", "Unrelated", "Bridge repairs finished in Agartala city centre without any delay today.")])
    assert items["a"]["duplicate_ids"] == ["b"]
    assert items["c"]["duplicate_ids"] == []


def test_mentions_extract_highway_formats_and_places():
    items = by_id([report("a", "NH06 closed", "National Highway (NH-315A), NH-37 on the Imphal- Silchar route, Highway No. 306 near Aizawl, National Highway 6 at Mao.")])
    assert items["a"]["mentions"] == {"highways": ["NH-6", "NH-37", "NH-306", "NH-315A"], "places": ["Imphal", "Silchar", "Aizawl", "Mao"]}


def test_closure_and_reopening_close_in_time_are_possible_conflict():
    items = by_id([
        report("closed", "NH-6 blocked", "NH-6 blocked by landslide near Sonapur.", "2026-10-22T08:00:00Z"),
        report("open", "Traffic restored", "Traffic on National Highway 6 has been restored.", "2026-10-23T10:00:00Z"),
        report("old", "NH-6 restored", "Traffic on NH-6 restored.", "May 29, 2024"),
    ])
    assert items["closed"]["conflict_ids"] == ["open"]
    assert items["open"]["conflict_ids"] == ["closed"]
    assert items["old"]["conflict_ids"] == []
    assert sorted(items["old"]["related_ids"]) == ["closed", "open"]


def test_coarse_relative_dates_are_never_treated_as_conflicts():
    items = by_id([
        report("a", "NH-2 closed", "NH-2 closed by mudslide.", "3 months ago"),
        report("b", "NH-2 reopened", "NH-2 reopened for traffic.", "3 months ago"),
    ])
    assert items["a"]["conflict_ids"] == []


def test_normalize_source_url_strips_tracking_and_fragments():
    assert normalize_source_url("https://WWW.Instagram.com/reel/DZ4UTPCiJki/?hl=en&utm_source=x#top") == "https://www.instagram.com/reel/DZ4UTPCiJki"
    assert normalize_source_url("https://example.org/news?id=7&fbclid=abc") == "https://example.org/news?id=7"
    assert normalize_source_url("https://example.org/") == "https://example.org"


def test_event_types_are_tagged_with_a_primary_type():
    items = by_id([
        report("slide", "NH-37 Blocked by Landslides", "Continuous rainfall has triggered multiple landslides."),
        report("bridge", "Paka Bridge Collapses", "Traffic disrupted on the Trans Arunachal Highway."),
        report("flood", "Assam Flood", "Waterlogging in Guwahati after heavy rain."),
        report("none", "Tension eases", "Tribal body meets State police."),
    ])
    assert items["slide"]["event_type"] == "landslide" and "closure" in items["slide"]["event_types"]
    assert items["bridge"]["event_type"] == "bridge"
    assert items["flood"]["event_types"] == ["flood", "weather"]
    assert items["none"]["event_type"] == "other"


def sourced(incident_id, url, summary, published_at, verification="unverified", freshness="unknown"):
    return {**report(incident_id, incident_id, summary, published_at), "source_url": url,
            "verification": verification, "freshness": freshness}


def test_independent_publishers_corroborate_but_reposts_and_unattributable_links_do_not():
    items = by_id([
        sourced("news", "https://assamtribune.com/nh6-closed", "NH-6 blocked by landslide at Sonapur.", "2026-10-22T08:00:00Z"),
        sourced("page", "https://www.facebook.com/nemediahub/posts/1", "Traffic on National Highway 6 closed near Sonapur.", "2026-10-22T11:00:00Z"),
        sourced("same", "https://assamtribune.com/nh6-update", "NH-6 remains closed at Sonapur.", "2026-10-22T12:00:00Z"),
        sourced("reel", "https://www.instagram.com/reel/abc", "NH-6 blocked, watch.", "2026-10-22T09:00:00Z"),
    ])
    assert items["news"]["corroborating_ids"] == ["page"]
    assert items["news"]["evidence_status"] == "corroborated"
    assert items["reel"]["corroborating_ids"] == []
    assert sorted(items["same"]["corroborating_ids"]) == ["page"]


def test_stale_outranks_confirmed_and_dismissed_outranks_everything():
    items = by_id([
        sourced("old", "https://a.example/1", "Bridge damaged.", "Jul 3, 2023", "confirmed", "stale"),
        sourced("current", "https://b.example/1", "Bridge damaged.", None, "confirmed", "fresh"),
        sourced("gone", "https://c.example/1", "Unrelated.", None, "dismissed", "stale"),
    ])
    assert (items["old"]["evidence_status"], items["current"]["evidence_status"], items["gone"]["evidence_status"]) == ("stale", "confirmed", "dismissed")
