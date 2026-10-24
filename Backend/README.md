# INDIA-TRACE API

FastAPI service for route planning and road disruption evidence. SQLite is used for local persistence so the demo can run without PostgreSQL/PostGIS. TinyFish search results are stored as **unverified evidence candidates**; source URLs and source-provided timestamps are preserved, and location is unknown unless coordinates are explicitly available.

## Run locally

```sh
cd Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Optional: add TINYFISH_API_KEY to .env for collection.
uvicorn app.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Interactive docs are at `/docs`. SQLite data defaults to `Backend/data/indiatrace.sqlite3` when started from `Backend/`.

## INDIA-TRACE endpoints

- `GET /api/health` — service/database health.
- `POST /api/routes/plan` — geocodes Indian place names with Nominatim, retrieves candidate driving routes from OSRM, and returns provider-sourced distances, durations, and route geometry. Body: `{"origin":"Guwahati","destination":"Shillong","vehicle_type":"truck","priority":"balanced"}`. Supported vehicles: `truck`, `van`, `ambulance`; priorities: `balanced`, `fastest`, `shortest`, `cautious`.
- `GET /api/incidents` — stored evidence candidates, including freshness and verification labels.
- `GET /api/incidents/{id}` — one evidence record.
- `PATCH /api/incidents/{id}/review` — save a human verification state and review note. Optional location name and coordinates are stored only when supplied by the reviewer.
- `POST /api/collection/run` — searches TinyFish for Northeast India disruption reports, deduplicates by source URL, and stores search hits as unverified. Without `TINYFISH_API_KEY`, returns `not_configured` and does not invent fallback reports.

Route results always include a `verify_before_dispatch` recommendation while disruption and vehicle restriction data remain unverified. An unknown location is not matched to a route, and no reports do not imply that a road is clear. OSRM's public routing service and OpenStreetMap Nominatim require internet access; respect their usage policies and use an offline/local routing provider for disconnected operation.

## Existing tracking API

The original shipment trace API remains available at `/health` and `/api/v1/*` (summary, traces, trace events). It uses the same SQLite database.

## Configuration

Set app name, API prefix, SQLite path, CORS origins, `TINYFISH_API_KEY`, and geocoder User-Agent in `.env`. Never put service keys in frontend environment variables.
