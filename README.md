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

1. **Run collection** (Evidence panel). TinyFish search hits are stored as unverified evidence with source links. Freshness is estimated from the source's date text ("3 months ago", "Jul 3, 2023").
2. **Review a report.** Open it, check the linked source, and save a status and note. Mentions (NH numbers, places), possible duplicates and possible conflicts are shown as hints only. Mark irrelevant search hits **Dismissed**. Add coordinates only after checking the source.
3. **Plan a route.** Guwahati → Tezpur returns two OSRM routes, so it shows route comparison well; Guwahati → Shillong returns one. Each route gets a recommendation with reasons:
   - **Consider an alternative**: a reviewer-confirmed report is within 3 km and another route has none.
   - **Verify before dispatch**: reports nearby are unconfirmed, some reports have no location, evidence is over 24 hours old, or nothing has been collected.
   - **Proceed cautiously**: every relevant report is located and none is near the route. This never means the road is clear.

## Current capability and limits

- Route planning resolves place names with OpenStreetMap Nominatim and gets route geometry, distance, and time estimates from OSRM's public car profile. Vehicle type is recorded but vehicle restrictions are not checked.
- No seed or fake incidents are inserted. Reports with no source time are marked freshness `unknown`; collection does not infer incident coordinates from text.
- Duplicate, conflict and mention hints are text heuristics and never change a report's verification state.
- The exact Guwahati–Shillong example has a historical OSRM snapshot fallback for offline presentation; it is marked not for dispatch. Map tiles, routing, geocoding and TinyFish collection need internet.
- The original shipment trace/event API is preserved under `/api/v1/*`.

## Tests

```sh
cd Backend
pip install -r requirements-dev.txt
pytest
```

```sh
cd Frontend
npm run lint
npm run build
```

See [Backend setup and API details](Backend/README.md) and [Frontend details](Frontend/README.md).
