# INDIA-TRACE · Team Tech Titans

Road disruption intelligence for essential deliveries in India, with a Northeast India focus.

## Run the end-to-end demo

Requires Python 3.11+ and Node.js 20.19+ or 22.12+ (Vite 8).

Terminal 1:

```sh
cd Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add TINYFISH_API_KEY to Backend/.env if available.
uvicorn app.main:app --reload
```

Terminal 2:

```sh
cd Frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The backend docs are at `http://127.0.0.1:8000/docs`. This local SQLite setup avoids requiring PostgreSQL during the hackathon demo.

## Demo walkthrough

The pilot corridor is **NH-6 / NH-306, Guwahati – Shillong – Silchar – Aizawl**. See [docs/PILOT.md](docs/PILOT.md) for the reasons, the source policy, pre-demo steps and the demo script, and [docs/EVALUATION.md](docs/EVALUATION.md) for the evidence test cases, measured runs and limitations.

1. **Run collection** (Evidence panel). Six corridor searches (web and news) go to TinyFish Search, and TinyFish Fetch then reads each new page for its description, author and publication date. Pick a search window, or open *Targeted search* to search one road, place or event type. Each report keeps the query that found it, and every run is logged. Freshness uses a window per event type (12 hours for accidents up to 30 days for roadworks).
2. **Review a report.** Every report shows one evidence status: *Unverified*, *Corroborated* (an independent publisher agrees), *Confirmed by reviewer*, *Conflicting*, *Stale* (outranks confirmed), *Resolved* (an authoritative update ended it) or *Dismissed*. Duplicates, conflicts, event types and highway or place mentions are automatic hints. Saving a review adds to the report's history instead of overwriting it. Add coordinates only after checking the source.
3. **Plan a route.** Guwahati → Shillong runs on NH-27 and NH-6, and OSRM returns one route; Silchar → Aizawl returns two, so it shows route comparison. Route cards list reports that name a highway the route uses, with their location marked unconfirmed. Below the recommendation, each route lists the reports that may affect it, each with a relevance score and its reasons, plus per-highway coverage ("NH-27 · 0 reports" is a coverage gap, not a clear road). Each route gets a recommendation with reasons:
   - **Consider an alternative**: a reviewer-confirmed report is within 3 km and another route has none.
   - **Verify before dispatch**: reports nearby are unconfirmed, some reports have no location, evidence is over 24 hours old, or nothing has been collected.
   - **Proceed cautiously**: every relevant report is located and none is near the route. This never means the road is clear.

4. **Re-check and follow a report's life.** Each report moves from *New* to *Needs re-check* (half its freshness window has passed since it was published or last checked) to *Stale*; only a reviewer marks it *Resolved*. *Re-check source* reads the page again with TinyFish Fetch, and *Re-check due sources* does it for every report that is due. The **timeline** keeps everything that happened to the report: when it was published, which run and query collected it, every sighting, page read and re-check, every review and flag. A changed page is flagged for review; an unreadable page never counts as a reopened road.
5. **Check coverage and system health.** *Coverage by state* shows reports per state of the region; a state without recent reports is a gap, not a clear road. *Monitoring* (bottom of the page) shows evidence quality, freshness lag, reviewer decisions, collection failures, TinyFish usage against the free daily allowance and route-planning response times. Anything without data says "not measured".

## Current capability and limits

- The base map is **Mappls (MapmyIndia)** when `MAPPLS_STATIC_KEY` is set in `Backend/.env`, and OpenStreetMap otherwise. The Mappls Web SDK runs in the browser and needs the key there, so the dashboard gets it from `/api/map-config`; restrict the key to your domains in the Mappls console (auth.mappls.com/console). If Mappls cannot load (no internet, a rejected key), the map falls back to OpenStreetMap and says so. Routes and evidence are drawn the same way on both maps. Only India is shown: everything outside India's official boundary (as per the Survey of India, from [datameet/maps](https://github.com/datameet/maps) `india-composite.geojson`, CC0, simplified to about 500 m in `Frontend/public/india-boundary.geojson`) is covered, the boundary is outlined, and the OpenStreetMap view cannot be panned outside India.
- Route planning resolves place names with OpenStreetMap Nominatim and gets route geometry, distance, and time estimates from OSRM's public car profile. Vehicle type is recorded but vehicle restrictions are not checked.
- No seed, sample or random incidents exist anywhere in the app: every report is a real public source found by TinyFish, with its real link. Reports with no source time are marked freshness `unknown`.
- **Live.** With `COLLECTION_INTERVAL_MINUTES` set (30 on the demo laptop), the API collects, re-checks due sources and places newly named towns on its own; the dashboard reloads every minute, shows "Live · updated …" and when the next collection runs, and announces new reports.
- **Map on your location.** The map opens on the device's position (a blue dot with its accuracy ring, kept up to date); the button above the zoom control returns to it. With a route planned the map fits the route instead. If location is refused or outside India, the map shows Northeast India and says why.
- **Map layers** (the Layers button on the map), like a maps app. *Map type:* Default (OpenStreetMap), Satellite (Esri World Imagery, with roads drawn over it in the style of Google Maps' satellite view: thin white streets, yellow highways, road names along the roads and national highway numbers in small boxes, plus place names; roads and names come from OpenStreetMap) and Terrain (OpenTopoMap). Place names cover all of India (states, cities, towns, suburbs, villages and neighbourhoods) from OpenStreetMap via OpenFreeMap's vector tiles (free, no key; only their roads and place names are read). Only names inside India's official boundary are shown, and no third-party boundary lines are drawn. *Map details:* Rainfall (NASA IMERG, the latest half hour available, a few hours behind), Wildfires (NASA VIIRS fire detections, today), Railways (OpenRailwayMap), Cycling (CyclOSM), Air quality (Open-Meteo US AQI at your position and the route's ends) and Traffic (Mappls live traffic, with the Mappls key). The choice is remembered in the browser and each layer's source is credited under the map. Street View and 3D buildings are not offered: there is no free source for this region.
- **Full screen**: the button above the location button fills the screen with the map, its controls and legend; the map credits fold behind an "i" button there (the browser's full screen, or the whole window where the browser has none, such as iPhone Safari). Esc or the same button leaves it.
- **Route form.** The start fills itself with the device's position ("Your location", sent as coordinates and used as given inside India); if location is refused, the start is left for you to type. The destination is chosen with suggestions as you type.
- **The source's own picture or video.** YouTube, Instagram and Facebook reports show the post or video with each site's official embed player, loaded only when you click "Show the … post/video". News reports show the picture the page publishes for link previews (its `og:image`), read from the page header and kept only if it loads in a browser; it is captioned as possibly a file photo. Reports with media are marked "photo", "video" or "… post" in the list.
- **Real locations.** A report that names one town (or a town after "at", "near", "in", "from") is given that town's real coordinates from OpenStreetMap Nominatim as an **approximate** location (shown on the report, not drawn on the map). Districts, valleys and names used in two states (Sonapur) are never placed. Town-placed reports within 5 km of a route are listed as "names a town on this route" and always ask for verification. Only reviewer-entered coordinates are exact, and only they can make a route "consider an alternative".
- Event types, duplicates, conflicts, corroboration, regions and mentions are text heuristics and never change a reviewer's decision. Anyone can flag a record as outdated or wrong; flags wait for a reviewer and don't change the status.
- Collection and re-checks run as background jobs on the API, one at a time; the dashboard follows each run's progress. Scheduled collection, followed by a re-check of due reports, is off by default (`COLLECTION_INTERVAL_MINUTES` in `Backend/.env`).
- Sources are categorised as official (gov.in and nic.in domains), news, social or other. A collection can be limited to some categories, and an official source counts as corroboration (report section 9), never as a reviewer's confirmation.
- The region (`REGION` in `Backend/.env`, defined in `Backend/app/regions.py`) sets the places with districts and alternate spellings, road names such as "GS Road" for NH-6, the searches, the allowed source categories and the freshness windows. Only Northeast India is configured; adding a region is a configuration entry. Reports keep their original text, and the writing script is recorded; the interface is not translated.
- Geocodes and routes are cached in SQLite and served from the cache if OSRM is slow or down, labelled with when they were fetched. The exact Guwahati–Shillong example also has a historical snapshot in the frontend, marked not for dispatch. Map tiles and TinyFish collection need internet.
- SQLite instead of the PostgreSQL + PostGIS in the proposal: it needs no setup on the demo laptop. PostGIS is the scale-up path.
- The original shipment trace/event API is preserved under `/api/v1/*`.

## Tests

```sh
cd Backend
pip install -r requirements-dev.txt
pytest                 # everything, including the browser tests
pytest -m "not e2e"    # backend only, no browser
```

The browser tests in `Backend/tests/test_browser.py` build the frontend and drive it in Chrome against the real API on a temporary database. They need `npm install` in `Frontend/` and Google Chrome; set `E2E_BROWSER_CHANNEL=chromium` after `playwright install chromium` to use Playwright's own browser. They are skipped when either is missing. External services are faked, so no test touches the internet or your data. The failure cases they cover are listed in [docs/EVALUATION.md](docs/EVALUATION.md#end-to-end-failure-tests).

```sh
cd Frontend
npm run lint
npm run build
```

See [Backend setup and API details](Backend/README.md) and [Frontend details](Frontend/README.md).
