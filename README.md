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
3. **Plan a route.** The planner starts on **Fastest**, like a maps app; Balanced, Shortest and Cautious order the routes differently, and each route card says why the first route is first ("Route 1 · Shortest"), marks the fastest and the shortest route, and says how each alternative compares ("13 min faster · 5 km longer"). Guwahati → Shillong runs on NH-27 and NH-6, and OSRM returns one route; Silchar → Aizawl returns two, so it shows route comparison. Route cards list reports that name a highway the route uses, with their location marked unconfirmed. The evidence desk then switches to **This route**: the route's reports, most relevant first, each saying why it matched ("Names NH-6, which this route uses. Where on NH-6 is not known"); **All reports** shows the rest. Pages that describe no disruption (a taxi fare, a tour package) are marked *No disruption described* and never match a route, and the search engine's "Missing: … | Show results with:" note is removed from summaries. Below the recommendation, each route lists the reports that may affect it, each with a relevance score and its reasons, plus per-highway coverage ("NH-27 · 0 reports" is a coverage gap, not a clear road). Each route gets a recommendation with reasons:
   - **Consider an alternative**: a reviewer-confirmed report is within 3 km and another route has none.
   - **Verify before dispatch**: reports nearby are unconfirmed, some reports have no location, evidence is over 24 hours old, or nothing has been collected.
   - **Proceed cautiously**: every relevant report is located and none is near the route. This never means the road is clear.

4. **Re-check and follow a report's life.** Each report moves from *New* to *Needs re-check* (half its freshness window has passed since it was published or last checked) to *Stale*; only a reviewer marks it *Resolved*. *Re-check source* reads the page again with TinyFish Fetch, and *Re-check due sources* does it for every report that is due. The **timeline** keeps everything that happened to the report: when it was published, which run and query collected it, every sighting, page read and re-check, every review and flag. A changed page is flagged for review; an unreadable page never counts as a reopened road.
5. **Check coverage and system health.** *Coverage by state* shows reports per state of the region; a state without recent reports is a gap, not a clear road. *Monitoring* (bottom of the page) shows evidence quality, freshness lag, reviewer decisions, collection failures, TinyFish usage against the free daily allowance and route-planning response times. Anything without data says "not measured".

## Current capability and limits

- The base map is **Mappls (MapmyIndia)** when `MAPPLS_STATIC_KEY` is set in `Backend/.env`, and OpenStreetMap otherwise. The Mappls Web SDK runs in the browser and needs the key there, so the dashboard gets it from `/api/map-config`; restrict the key to your domains in the Mappls console (auth.mappls.com/console). If Mappls cannot load (no internet, a rejected key), the map falls back to OpenStreetMap and says so. Routes and evidence are drawn the same way on both maps. Only India is shown: everything outside India's official boundary (as per the Survey of India, from [datameet/maps](https://github.com/datameet/maps) `india-composite.geojson`, CC0, simplified to about 500 m in `Frontend/public/india-boundary.geojson`) is covered, the boundary is outlined, and the OpenStreetMap view cannot be panned outside India.
- Route planning resolves place names with OpenStreetMap Nominatim. With `GOOGLE_MAPS_API_KEY` set in `Backend/.env` (the Routes API enabled for that Google Cloud project), routes, distances and times come from Google's Routes API with live traffic, the same estimates Google Maps shows for a car; they are cached for 5 minutes and an older copy is never served. Without the key, or when Google fails (the reason is shown above the route cards), they come from OSRM's public car profile, which has no traffic and runs far too fast on hill roads (it gives Guwahati–Shillong as 1 h 12 min, an average of 81 km/h). Every route time says which it is: *Google · live traffic* or *OSRM · no traffic*. The vehicle is Car, Bike or Truck. Bike uses Google's two-wheeler routes for India (without Google it gets the car route, and a note above the route cards says so); Car and Truck use car routes, and for a truck the note says trucks are usually slower. Vehicle restrictions (weight, height, ghat roads) are not checked.
- No seed, sample or random incidents exist anywhere in the app: every report is a real public source found by TinyFish, with its real link. Reports with no source time are marked freshness `unknown`.
- **Live.** With `COLLECTION_INTERVAL_MINUTES` set (30 on the demo laptop), the API collects, re-checks due sources and places newly named towns on its own; the dashboard reloads every minute, shows "Live · updated …" and when the next collection runs, and announces new reports.
- **Map on your location.** The map opens on the device's position (a blue dot with its accuracy ring, kept up to date); the button above the zoom control returns to it. With a route planned the map fits the route instead. If location is refused or outside India, the map shows Northeast India and says why.
- **Map layers** (the Layers button on the map), like a maps app. *Map type:* Default (OpenStreetMap), Satellite (Esri World Imagery, with roads drawn over it in the style of Google Maps' satellite view: thin white streets, yellow highways, road names along the roads and national highway numbers in small boxes, plus place names; roads and names come from OpenStreetMap) and Terrain (OpenTopoMap). Place names cover all of India (states, cities, towns, suburbs, villages and neighbourhoods) from OpenStreetMap via OpenFreeMap's vector tiles (free, no key; only their roads and place names are read). Only names inside India's official boundary are shown, and no third-party boundary lines are drawn. *Map details:* Rainfall (NASA IMERG, the latest half hour available, a few hours behind), Wildfires (NASA VIIRS fire detections, today), Railways (OpenRailwayMap), Cycling (CyclOSM), Air quality (Open-Meteo US AQI at your position and the route's ends) and Traffic (Mappls live traffic, with the Mappls key). The choice is remembered in the browser and each layer's source is credited under the map. Street View and 3D buildings are not offered: there is no free source for this region.
- **Road report symbols**: reports are drawn as Google Maps-style incident symbols by type: accident (red, crash), road closed (red, no entry), roadworks (orange cone), landslide, flooding, bridge, heavy rain and a general hazard (yellow !). Reviewer-confirmed coordinates are drawn where they are; a report that names a town is drawn at that town with a dashed ring, because its spot on the road is unknown (one symbol per town and type, no counts). Stale reports are faded. Each type can be switched off under Show on map.
- **Toll plazas**: each route card counts the NHAI toll plazas on the route, the chosen route lists them in driving order (name, state, km from the start) and the map marks them. They come from NHAI's published plaza list (a CSV you download; see Backend/README.md). Prices are not in that list and are never estimated: each plaza says "Price not available". Without the list, tolls show as unknown.
- **Start (turn-by-turn navigation)**: once routes are found from Your location, Start (in the planner, and on the map) follows the chosen route laid out like Google Maps' navigation. A green banner shows the next turn (arrow and distance, the action above the road name in large type, "Then" when another turn follows within 1 km); a white sheet at the bottom shows the time and distance left and the arrival time (Google's estimate with traffic when the route was planned, or OSRM's without traffic), with ✕ to exit and a route overview button. The map fills the screen and follows a blue arrow that sits on the route and points along it; the route ahead is blue, the part driven grey. Dragging the map stops following until Re-centre. Directions are spoken ("In 400 metres, turn left onto GS Road") with a mute button, remembered in the browser. Off the route for two position updates in a row, a new route is found from there (at most every 20 s; a Re-route button is also offered). Start guides live whenever the device is within 1 km of the route's start, whether that is Your location or a typed place. From anywhere else the same button is Preview: the same view steps through every turn with ‹ › ("Turn 4 of 26", distance and time from there), with no voice and no re-routing, like a maps app's route preview. The map is not tilted or rotated (Leaflet draws north up); the arrow turns instead.
- **Map search bar**: "Search destination" at the top of the map suggests places like the route planner does; the place chosen becomes the planner's destination and routes are found from its starting point (usually your location). Without a known start it only fills the destination.
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

## Deploy for free (Vercel + Render)

The dashboard is a static site; the API is a small Python service. Both deploy from this GitHub repository.

1. **Backend on Render.** On render.com choose *New → Blueprint* and pick this repository; `render.yaml` sets it up.
   Enter `TINYFISH_API_KEY` when asked (and `GOOGLE_MAPS_API_KEY` for live-traffic times, optional). Leave
   `CORS_ORIGINS` for step 3. Render generates `ADMIN_TOKEN`: that is the reviewer key. When the service is live,
   `https://<service>.onrender.com/api/health` answers `"status": "ok"`.
2. **Dashboard on Vercel.** On vercel.com choose *Add New → Project*, import this repository and set
   *Root Directory* to `Frontend` (Vite is detected). Add the environment variable
   `VITE_API_URL=https://<service>.onrender.com`, then deploy.
3. **Connect them.** In Render, set `CORS_ORIGINS` to the Vercel address (for example `https://india-trace.vercel.app`,
   no trailing slash) and save; Render restarts the API.

On the public site anyone can view reports and plan routes. Collecting, re-checking and reviewing need the
reviewer key (sidebar → *Reviewer sign-in*), so visitors never spend the team's TinyFish searches.

Free-plan limits: the Render service sleeps after 15 minutes without visitors (the next visit takes about a minute
to wake it, and no collection runs while it sleeps), and its disk is not kept, so reports are collected afresh after
each deploy or restart.

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
# INDIA---TRACE
# INDIA---TRACE
