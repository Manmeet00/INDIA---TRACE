# Pilot corridor: NH-6 / NH-306, Guwahati – Shillong – Silchar – Aizawl

INDIA-TRACE is scoped to one corridor for the hackathon, as the project report (sections 11 and 16) and the PPT ("one corridor pilot") recommend. Nationwide coverage is not claimed.

## Why this corridor

- NH-6 and NH-306 carry essential supplies from Guwahati to Meghalaya, Assam's Barak Valley and Mizoram. Landslides at points such as Sonapur and Ratacherra regularly block them.
- Its Guwahati–Shillong leg is the route in the dashboard mockup.
- Collected public reports mention these highways often: in the 24 Oct 2026 pilot collection, 19 of 34 reports named NH-6 and 7 named NH-306.

## Segments

Measured against the public OSRM server on 24 Oct 2026. Durations are OSRM estimates without live traffic.

| Segment | Routes returned | Distance / time | National highways used (≥ 2 km) |
|---|---|---|---|
| Guwahati → Shillong | 1 | 97 km / 72 min | NH-27, NH-6 |
| Shillong → Silchar | 1 | 204 km / 156 min | NH-6 |
| Silchar → Aizawl | 2 | 173 km / 124 min and 179 km / 130 min | NH-6, NH-306 |
| Guwahati → Silchar (whole Assam–Meghalaya leg) | 1 | 300 km / 222 min | NH-27, NH-6 |

Silchar → Aizawl is the segment that demonstrates route comparison; OSRM returns a single route for the others.

## Source policy

- **Ingestion path:** TinyFish **Search** and **Fetch**, called only from the backend with `TINYFISH_API_KEY`. Both are free within TinyFish's daily limits (12,000 searches and 1,000 fetched URLs per day). Six searches run per collection (`PILOT_SEARCHES` in [collection.py](../Backend/app/collection.py)):
  1. web: `NH-6 Guwahati Shillong road closure landslide update`
  2. web: `NH-6 Shillong Silchar Sonapur Ratacherra landslide traffic`
  3. web: `NH-306 Silchar Aizawl road blocked landslide`
  4. web: `Meghalaya Mizoram Barak Valley highway closure latest`
  5. news: `Meghalaya landslide highway`
  6. news: `Mizoram Barak Valley road landslide`

  News searches return a publisher and a date. Narrow highway queries return nothing on news search, which is why those two stay broad. A search window (24 hours to 1 year, default 30 days) limits results by recency. Reviewers can also run a **targeted search** for a road, place or event type.
- **Fetch:** each new result's page is read with TinyFish Fetch, 10 URLs per request. The app keeps the page description, an excerpt, the author and the page's `published_date`; a page date fills in a missing search date and is labelled "from the page". Only the page description feeds the automatic hints, because full page text includes navigation and unrelated stories.
- **Stored per result:** title, snippet, source URL (normalised), publisher or site, the source's own date text, the query and search type that found it, when we collected it, and when a later search last saw it again.
- **Every run is logged** (`GET /api/collection/runs`): searches, results, new reports, re-seen reports, pages read, failures and duration. Each failed search is retried once.
- **Scheduled collection** is off by default. Set `COLLECTION_INTERVAL_MINUTES` in `Backend/.env` to turn it on.
- **Not done:** coordinates are never inferred from text, and no sample or seeded incidents are inserted.
- **Sources observed** in the 24 Oct 2026 pilot collection (search results, not a curated or endorsed list): facebook.com (14), instagram.com (5), timesofindia.indiatimes.com (2), barakbulletin.com (2), indiatodayne.in (2), youtube.com (2), morungexpress.com, sentinelassam.com, assamtribune.com, hindustantimes.com, reddit.com, en.wikipedia.org (1 each). Social posts dominate, which is why reviewer checks and the dismiss action matter.

## Before the demo

1. Start the backend while online and plan Guwahati → Shillong, Shillong → Silchar and Silchar → Aizawl once. Geocodes are cached for 30 days and routes for 24 hours, and a cached copy is served if OSRM later fails or is slow. Each response shows when it was fetched.
2. Run collection once. In October most reports are months old, so expect **Stale** labels and no reports in the last 24 hours. That is the correct result, not a fault: no recent reports does not mean the road is clear.
3. Review a few reports: dismiss off-topic hits, and add coordinates only for reports whose source gives a precise location.

## Demo sequence (report section 16)

1. **Open the map** on the pilot corridor (Guwahati → Shillong).
2. **Show a sourced record.** Open a report, then point out its source link, its source time (for example "≈ 26 Jul 2026 ('3 months ago' at collection)") and its collection time.
3. **Show duplicate and stale handling.** Filter by **Stale**, then open an NH-306 report flagged *Possible duplicate · not counted as confirmation*.
4. **Plan a route.** The route card reads "via NH-27 · NH-6" and lists reports that name NH-6, with their location marked unconfirmed.
5. **Show a precise warning.** Confirm a report with coordinates from its source. Then plan Silchar → Aizawl: the route near it changes to *Consider an alternative*, and the other route is named.
6. **Explain the uncertainty.** The dispatch banner lists every reason, and the vehicle restrictions are always shown as unchecked.
