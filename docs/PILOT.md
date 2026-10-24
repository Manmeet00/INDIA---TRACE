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

- **Ingestion path:** TinyFish Search, called only from the backend with `TINYFISH_API_KEY`. Four queries run per collection (in `PILOT_QUERIES`, [road_intelligence.py](../Backend/app/road_intelligence.py)):
  1. `NH-6 Guwahati Shillong road closure landslide update`
  2. `NH-6 Shillong Silchar Sonapur Ratacherra landslide traffic`
  3. `NH-306 Silchar Aizawl road blocked landslide`
  4. `Meghalaya Mizoram Barak Valley highway closure latest`
- **Stored per result:** title, snippet, source URL (normalised), source name, the source's own date text, and our collection time. Nothing else is inferred.
- **Not done:** pages are not fetched or scraped; coordinates are never inferred from text; no sample or seeded incidents are inserted.
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
