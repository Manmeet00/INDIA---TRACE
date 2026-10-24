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

## Metrics still to measure manually (report section 13)

Fill these in after the team reviews a sample by hand. Until then they are **not measured**.

| Metric | Procedure | Result |
|---|---|---|
| Extraction precision | For 30 collected reports, count those that really describe a road disruption on the pilot corridor. | not measured |
| Duplicate rate | Count events that appear as more than one ungrouped record. | not measured |
| Route-match precision | For reviewer-located reports, check that every flagged route really passes within 3 km. | not measured |
| Freshness lag | Compare source dates with `collected_at` for reports that have exact dates. | not measured |

## Limitations

- **Coverage.** One corridor, four search queries, and only what TinyFish Search returns. Many results are social posts. No reports does not mean the road is clear.
- **Freshness windows** (accident 12 h, weather 24 h, flood and closure 48 h, landslide 72 h, bridge 14 days, construction 30 days) are reasonable defaults, not measured values.
- **Relevance score** (location 50, freshness 20, evidence 20, severity 10) orders reports for review. It is not a probability that a road is blocked.
- **Location.** Coordinates come only from a reviewer. Highway mentions show that a report may be relevant, but not where on the road it is.
- **Text heuristics.** Event types, duplicates, conflicts and corroboration are keyword and similarity rules, shown as hints. They can miss or misjudge reports, and they never change a reviewer's decision.
- **Routing.** The public OSRM car profile: no live traffic and no truck restrictions, so vehicle suitability is always "unknown". The public server can be slow or rate-limited; cached routes are labelled with their fetch time.
- **Storage.** SQLite, not PostgreSQL + PostGIS. Distances use a planar approximation that is accurate at a few kilometres. PostGIS is the scale-up path in the report.
- **Not a safety system.** INDIA-TRACE organises evidence for a human dispatcher. It never declares a road clear or safe, and it doesn't replace official advisories.
