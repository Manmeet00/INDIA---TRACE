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

## Current capability and limits

- Route planning resolves place names with OpenStreetMap Nominatim and gets route geometry, distance, and time estimates from OSRM's public car profile. Vehicle type is recorded but vehicle restrictions are not checked.
- No seed or fake incidents are inserted. Reports with no source time are marked freshness `unknown`; collection does not infer incident coordinates from text.
- Event types, duplicates, conflicts, corroboration, regions and mentions are text heuristics and never change a reviewer's decision. Anyone can flag a record as outdated or wrong; flags wait for a reviewer and don't change the status.
- Scheduled collection is off by default (`COLLECTION_INTERVAL_MINUTES` in `Backend/.env`).
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
