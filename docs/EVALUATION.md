# Evaluation set and limitations

This page covers the evidence test cases, how the pilot acceptance checks from the project report (sections 13 and 16) are met, the collection runs measured so far, and the system's limits. No accuracy figure is claimed unless it was measured.

## Evidence and status test cases

Each case runs automatically (`cd Backend && pytest`) and can also be shown in the UI.

| # | Case | Expected behaviour | Automated test |
|---|---|---|---|
| 1 | **Stale report.** Source date "Jul 3, 2023" or "3 months ago". | Freshness `stale`. A reviewer-confirmed but stale report is labelled *Stale · confirmed earlier*, never *Confirmed*. | `test_freshness_uses_estimated_publication_time`, `test_stale_outranks_confirmed_and_dismissed_outranks_everything` |
| 2 | **Conflicting reports.** NH-6 "blocked" and NH-6 "restored", published within 72 hours. | Both get `conflict_ids` and status `conflicting`. The same pair two years apart is **not** a conflict. | `test_closure_and_reopening_close_in_time_are_possible_conflict`, `test_coarse_relative_dates_are_never_treated_as_conflicts` |
| 3 | **Duplicate / syndicated text.** | Grouped as possible duplicates and never counted as corroboration. Identical truncated titles over different stories are **not** grouped. | `test_reposted_story_is_grouped_as_duplicate`, `test_same_truncated_title_with_different_stories_is_not_a_duplicate` |
| 4 | **Corroboration.** Two identifiable publishers agree within 72 hours. | Status `corroborated`. Same-publisher posts and unattributable links (Instagram reels, YouTube) do not count. | `test_independent_publishers_corroborate_but_reposts_and_unattributable_links_do_not` |
| 5 | **Unknown time.** The source gives no date. | Freshness `unknown`; the UI says "Time not provided by source". No time is invented. | `test_parse_published_handles_search_result_formats` |
| 6 | **Poorly located report.** Names NH-6 but has no coordinates. | Never matched to a route by distance. Listed as a low-confidence highway mention with "Where on the road is not known." | `test_unlocated_reports_naming_a_route_highway_are_low_confidence_mentions` |
| 7 | **No reports.** | `verify_before_dispatch` with "No reports does not mean the road is clear." | `test_no_reports_is_not_treated_as_clear`, `test_plan_without_reports_requires_verification` |
| 8 | **Confirmed report on a route.** | That route gets `consider_alternative` naming the cleaner route. `cautious` priority ranks the cleaner route first. | `test_confirmed_report_suggests_clean_alternative`, `test_cautious_plan_ranks_route_without_confirmed_reports_first` |
| 9 | **Review history.** | Every status change is kept with its reason; nothing is overwritten. | `test_review_history_keeps_every_status_change` |
| 10 | **Freshness depends on event type.** A report 50 hours old. | A landslide (72 h window) is still fresh; an accident (12 h window) is stale. | `test_freshness_window_depends_on_event_type` |
| 11 | **Route impact explanation.** | Each route lists the reports that may affect it with a score and reasons. A precise nearby report outranks one that only names the highway. | `test_impact_reports_rank_precise_recent_confirmed_above_road_mentions`, `test_plan_lists_reports_that_may_affect_each_route` |
| 12 | **Coverage gap.** A highway on the route has no recent reports. | Shown as a coverage gap, explicitly "not evidence that the road is clear". | `test_coverage_marks_highways_without_recent_reports_as_gaps` |
| 13 | **User correction.** Someone flags a record as outdated. | The flag is visible but does not change the status; the next review closes it. | `test_correction_flags_stay_open_until_a_review_and_never_change_status` |
| 14 | **Resolved disruption.** A reviewer records an authoritative reopening. | Status `resolved`; the report no longer counts against routes. | `test_resolved_reports_no_longer_count_against_a_route`, `test_review_accepts_resolved` |
| 15 | **Collection provenance and failures.** | The query, search type, page fetch result and dates are kept. A repeat collection updates "last seen" instead of duplicating; a failed search is retried once; a run where every search fails is still logged. | `test_targeted_collection_searches_web_and_news_then_fetches_pages`, `test_repeat_collection_records_recheck_instead_of_duplicating`, `test_failed_search_is_retried_once`, `test_all_searches_failing_is_logged_and_reported` |

## End-to-end failure tests

The project plan's end-to-end milestone asks for tests of no results, timeouts, malformed reports, missing coordinates, stale incidents and database failures. Each case runs through the HTTP API in `Backend/tests/test_failures.py`, with external services faked at the network layer. The browser column is `Backend/tests/test_browser.py`, which drives the built dashboard in Chrome against the real API.

| Failure | Expected behaviour | API test | Browser test |
|---|---|---|---|
| **No results** | An empty search is logged as a complete run, and the message says no reports does not mean the road is clear. A route with no evidence is *Verify before dispatch*, and its highways show as coverage gaps. | `test_search_with_no_results_is_logged_and_says_absence_is_not_clear`, `test_route_with_no_evidence_is_never_called_clear` | `test_empty_workspace_and_empty_collection_never_suggest_a_clear_road` |
| **Provider timeout** | 502 naming the host and the wait. The last good route is served, with its fetch time, when one is cached. A page-fetch timeout keeps the reports and records why. Search timeouts are retried once, then the run is logged as failed. | `test_routing_timeout_without_a_cached_copy_is_a_clear_502`, `test_routing_timeout_serves_the_last_good_route_with_its_age`, `test_page_fetch_timeout_keeps_the_reports_and_records_why`, `test_search_timeouts_are_retried_then_logged_as_a_failed_run` | `test_routing_provider_timeout_is_explained`, `test_routing_timeout_on_the_demo_route_falls_back_to_a_labelled_snapshot` |
| **Hung API** | The dashboard stops waiting after 20 s (60 s for routes, 5 min for collection) and says so. | — | `test_hung_api_request_times_out_in_the_browser` |
| **Dropped connection or garbled body** | 502, not a crash. | `test_dropped_or_garbled_provider_responses_are_502_not_500` | — |
| **Malformed reports** | Results without a web URL or text, with credentials in the URL, or with non-text fields are skipped. Nothing is guessed: a non-text title becomes "Untitled public source", and an unreadable date gives unknown freshness. A search response without a result list counts as a failed search. A malformed Fetch response keeps the reports. | `test_malformed_search_results_are_skipped_and_nothing_is_invented`, `test_search_response_without_a_result_list_counts_as_a_failed_search`, `test_malformed_fetch_response_does_not_lose_the_collected_reports` | `test_collect_review_locate_and_replan` |
| **Malformed provider data** | A geocode or route without usable coordinates is a 502 and is not cached. An unknown place and an undrivable route are explained. | `test_malformed_provider_data_is_a_502_and_is_never_cached`, `test_unknown_place_and_no_drivable_route_are_explained` | — |
| **Malformed requests** | 422 with nothing saved. | `test_malformed_requests_are_rejected_before_anything_is_saved` | — |
| **Missing coordinates** | Never matched to a route by distance. Listed as a highway mention, "Where on the road is not known." Adding a reviewer's coordinates puts the report on the map and in the advice. Removing them takes it out again. | `test_report_without_coordinates_is_never_placed_on_a_route`, `test_located_report_stops_counting_once_its_coordinates_are_removed` | `test_collect_review_locate_and_replan` |
| **Stale incidents** | A stale report confirmed by a reviewer is labelled *Stale*, never *Confirmed*. Route advice says it is past its freshness window. Old collections ask for a new run. | `test_stale_confirmed_report_is_never_shown_as_a_current_confirmation`, `test_old_collection_asks_for_a_new_run` | `test_collect_review_locate_and_replan` |
| **Stopped API** | *API unavailable*, collection disabled, and route errors say the API is not reachable. | — | `test_stopped_api_is_reported_as_unavailable` |
| **Database failure** | A missing folder, corrupt file, unwritable path or locked database gives a 503 with a plain reason on every endpoint, with CORS headers. A failed review write is fully rolled back. The API starts and reports the problem, then works again once the database is back. The dashboard shows *API error · Running, but data is unavailable* and keeps the last loaded evidence. | `test_every_endpoint_answers_503_with_cors_when_the_database_fails`, `test_locked_database_asks_to_retry`, `test_failed_review_write_is_rolled_back_completely`, `test_api_starts_and_reports_the_problem_when_the_database_cannot_be_created`, `test_database_restored_after_a_failure_works_again` | `test_database_failure_is_shown_and_recovers` |

Before these fixes, 19 of the API failure tests failed on the old code. The problems were:
- crashes (500s) on dropped connections and malformed provider data;
- malformed routes being cached;
- one malformed Fetch item aborting the whole collection run;
- 500s without CORS headers on database errors;
- an API that would not start when the database could not be opened.

The browser tests also found a Leaflet script error (`_leaflet_pos`) when a route was planned again while the map was still zooming. It is fixed by fitting the map to the route without animation.

## Report features beyond the MVP

`Backend/tests/test_report_features.py` and the last browser test cover these.

| # | Feature (report section) | Expected behaviour | Tests |
|---|---|---|---|
| 16 | Source categories and allowed sources (7, 9) | Government domains are *official*, and an official report reads *Corroborated* unless it is stale or conflicting. A run can keep only some categories; skipped results are counted and reported. | `test_source_categories`, `test_official_source_corroborates_but_never_outranks_stale_or_review`, `test_collection_keeps_only_the_allowed_source_categories` |
| 17 | Regional configuration (5, 6.7) | Places resolve to one name, district and state ("Cherrapunji" → Sohra, East Khasi Hills). Road names ("GS Road") map to their highway. The writing script is recorded. "West Jaintia Hills" is not read as West Bengal. An unknown region is refused. | `test_region_names_districts_aliases_and_scripts`, `test_unknown_region_is_refused` |
| 18 | Coverage by state (5, 11) | Reports and recent reports per state; a state without recent reports is shown as a gap. | `test_region_endpoint_shows_configuration_and_coverage_gaps` |
| 19 | Lifecycle (6.5) | New → needs re-check (half the freshness window since publication or the last check) → stale. A check never makes a stale report fresh, and only a reviewer resolves one. | `test_lifecycle` |
| 20 | Re-checks (6.5, 7.9) | A re-read page is recorded as unchanged, changed or unreadable. Statuses never change, and an unreadable page is not a reopening. Without ids, only reports that are due are read. | `test_recheck_records_changed_unchanged_and_unreadable_pages_without_changing_status`, `test_recheck_without_ids_reads_only_reports_that_are_due`, `test_single_report_recheck` |
| 21 | Traceable runs and timeline (5, 6.3, 7.4) | Every report keeps the run that collected it. Its timeline lists publication, collection, sightings (one per run), page reads, reviews and flags, newest first. | `test_timeline_keeps_every_step_newest_first`, `test_a_page_found_by_several_searches_is_one_sighting_per_run` |
| 22 | Location-based duplicates (6.4) | Reviewer-located reports of the same event type within 1 km and 72 hours are grouped. | `test_reviewer_located_reports_at_the_same_spot_and_time_are_grouped` |
| 23 | Background collection (11) | A run returns at once, reports its progress and allows one run at a time (409 otherwise). A run cut off by a restart is marked interrupted. | `test_background_collection_reports_progress_and_allows_one_run_at_a_time`, `test_runs_left_running_by_a_restart_are_marked_interrupted` |
| 24 | Monitoring (8, 13) | Usage, cache hits, failures, latency, freshness lag and reviewer decisions come only from what was logged; empty figures are null. | `test_metrics_count_only_what_was_measured` |

## Pilot acceptance checks (report section 13)

| Check | How it is met |
|---|---|
| Every displayed incident has a traceable source | Collection drops results without a valid http(s) URL; every card links to its source. |
| Publication time is not fabricated; retrieval time is stored separately | `published_at` keeps the source's own text, `published_estimate` is derived from it and marked approximate, and `collected_at` is our time. |
| Conflicting reports are visible in test cases | Cases 2 and 9. |
| Old reports are not shown as confirmed current incidents | Case 1. Stale outranks confirmed in `evidence_status`, and route reasons state when a nearby confirmed report is over 24 hours old. |
| Poorly located incidents do not create precise route warnings | Case 6. Only reviewer-entered coordinates are matched by distance. |
| Routing results are labelled with their data limitations | Every plan shows when the route was fetched, that OSRM has no live traffic, and that vehicle restrictions are unchecked. |
| No live incident or accuracy claim is made without measurement | This page reports counts only, and the precision table below stays empty until the manual review is done. |

## Collection runs measured

Both runs on 24 Oct 2026, live TinyFish Search.

| Run | Queries | Results stored | Same-URL duplicates skipped | Freshness | Notes |
|---|---|---|---|---|---|
| 1 | 3 general Northeast queries (before the pilot) | 30 | 0 | 19 stale, 11 unknown, 0 fresh | Off-topic hits included a Uttarakhand video and a border-tension story; this led to the dismiss state. |
| 2 | 4 pilot-corridor queries | 34 | 1 | 27 stale, 7 unknown, 0 fresh | 19 mention NH-6 and 7 mention NH-306. One syndicated NH-306 pair was grouped as duplicates, and one independent NH-6 (Sonapur, May 2022) pair was corroborated. |
| 3 | Targeted: NH-6 landslide, last 30 days, web + news, then Fetch | 10 | 0 | — | All 10 pages read by Fetch in 15.1 s with no errors; 4 gained an exact publication time from the page. The search engine also matched NH-10 (Sikkim) reports, which a reviewer would dismiss. |

## Metrics measured automatically

The dashboard's *Monitoring* panel and `GET /api/metrics` compute these from logs and stored reports. A figure without data is reported as not measured.

| Metric | How it is computed | Result |
|---|---|---|
| Freshness lag | Hours from an exact source publication time to `collected_at`. Approximate dates ("3 months ago") are excluded. | **Median 672 h (28 days), p90 696 h (29 days), n = 4** (live data, 24 Oct 2026). The sample is small, and these four were a backlog found by the first pilot collection, so the figure says nothing yet about steady-state delay. |
| Stale share, unknown-time share, located share, duplicate-group share | Shares of active (or all) reports. | 75% stale, 25% no source time, 0% located, 5% in a duplicate group (44 reports, 24 Oct 2026). |
| Kept after review | Share of reviewed reports a reviewer did not dismiss as irrelevant. It stands in for extraction precision only on what reviewers chose to look at, so it is not a random sample. | not measured (no reviews yet) |
| Collection reliability, usage and latency | Failed searches, unreadable pages, run time, TinyFish calls against the free daily allowance, route-planning p50/p95. | Logged from 24 Oct 2026 onwards. |

## Metrics still to measure manually (report section 13)

Fill these in after the team reviews a sample by hand. Until then they are **not measured**.

| Metric | Procedure | Result |
|---|---|---|
| Extraction precision | For 30 collected reports, count those that really describe a road disruption on the pilot corridor. | not measured |
| Duplicate rate | Count events that appear as more than one ungrouped record. | not measured |
| Route-match precision | For reviewer-located reports, check that every flagged route really passes within 3 km. | not measured |
| Extraction recall | Compare collected reports against a hand-made list of relevant reports for the same days. | not measured |

## Limitations

- **Coverage.** One corridor, six search queries, and only what TinyFish Search returns. Many results are social posts. No reports does not mean the road is clear.
- **Freshness windows** (accident 12 h, weather 24 h, flood and closure 48 h, landslide 72 h, bridge 14 days, construction 30 days) are reasonable defaults, not measured values.
- **Relevance score** (location 50, freshness 20, evidence 20, severity 10) orders reports for review. It is not a probability that a road is blocked.
- **Source categories** come from the domain: government domains are official, and a list of social and news sites covers the rest. A news site missing from the list counts as *other* unless TinyFish news search found it.
- **Re-check timing** (half the freshness window, or a day for reports without a time) is a default, not a measured value. Re-checks read the page again; they do not search for newer reports.
- **Regions.** Only Northeast India is configured. Districts are listed only for corridor places we are sure of, and road aliases only where OSRM's highway refs back them. The interface is in English.
- **Approximate locations** are the coordinates of the town a report names, chosen by a text rule (the only town named, or one after "at", "near", "in", "from", "between"). A dateline town ("SHILLONG:") can be picked when the incident is elsewhere, so these locations say which town a report is about, never the exact spot (they are not drawn on the map), and never make a route "consider an alternative".
- **Evidence media** is the source's own: an embed of the original post or video, or the picture the page publishes for link previews. A preview picture can be a file or stock photo, a removed or private post shows nothing, and some publishers refuse their pictures to other sites (those are left out).
- **Location.** Exact coordinates come only from a reviewer. Highway mentions show that a report may be relevant, but not where on the road it is.
- **Text heuristics.** Event types, duplicates, conflicts and corroboration are keyword and similarity rules, shown as hints. They can miss or misjudge reports, and they never change a reviewer's decision.
- **Routing.** The public OSRM car profile: no live traffic and no truck restrictions, so vehicle suitability is always "unknown". The public server can be slow or rate-limited; cached routes are labelled with their fetch time.
- **Storage.** SQLite, not PostgreSQL + PostGIS. Distances use a planar approximation that is accurate at a few kilometres. PostGIS is the scale-up path in the report.
- **Not a safety system.** INDIA-TRACE organises evidence for a human dispatcher. It never declares a road clear or safe, and it doesn't replace official advisories.
