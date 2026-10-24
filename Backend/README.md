# INDIA-TRACE API

FastAPI service for route planning and road disruption evidence. SQLite is used for local persistence so the demo can run without PostgreSQL/PostGIS. TinyFish search results are stored as **unverified evidence candidates**; source URLs and source-provided timestamps are preserved, and location is unknown unless coordinates are explicitly available.

## Run locally

```sh
cd Backend
python3 -m venv .venv  # Python 3.11+
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Optional: add TINYFISH_API_KEY to .env for collection.
uvicorn app.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Interactive docs are at `/docs`. SQLite data defaults to `Backend/data/indiatrace.sqlite3` when started from `Backend/`.

## INDIA-TRACE endpoints

- `GET /api/health` — service/database health.
- `POST /api/routes/plan` — geocodes Indian place names with Nominatim, retrieves candidate driving routes from OSRM, and returns provider-sourced distances, durations, route geometry, `highways` (national highways used for at least 2 km, with metres), `routing_fetched_at`, `impact_reports` (reports that may affect the route, each with a relevance `score` and `factors`), `coverage` (reports per highway and a coverage-gap note), and per-route `exposure` (reviewer-located reports within 3 km by verification state; `highway_mentions` for reports without a location that name one of the route's highways; the count of other unlocated reports) with a `recommendation` (`proceed_cautiously`, `consider_alternative`, `verify_before_dispatch`) and `recommendation_reasons`. Body: `{"origin":"Guwahati","destination":"Shillong","vehicle_type":"truck","priority":"balanced"}`. Supported vehicles: `truck`, `van`, `ambulance`; priorities: `balanced`, `fastest`, `shortest`, `cautious`.
- `GET /api/incidents` — stored evidence candidates, including freshness (from `published_estimate`, parsed from the source's date text), verification labels, `evidence_status` (`unverified`, `corroborated`, `confirmed`, `conflicting`, `stale`, `unknown`, `dismissed`; stale outranks confirmed), `review_history`, and reviewer hints: `event_type`/`event_types`, `mentions`, `duplicate_ids`, `related_ids` (same highway), `conflict_ids` (closure vs reopening on the same highway within 72 hours), `corroborating_ids` (a different identifiable publisher agreeing within 72 hours; duplicates never count).
- `GET /api/incidents/{id}` — one evidence record.
- `GET /api/collection/runs` — the collection log: searches, results, new and re-seen reports, pages fetched, failures, duration.
- `POST /api/incidents/{id}/flags` — anyone flags a record (`outdated`, `wrong_location`, `duplicate`, `not_relevant`, `other`) with an optional note. Flags never change the status and close on the next review.
- `PATCH /api/incidents/{id}/review` — save a verification state (`unverified`, `confirmed`, `conflicting`, `unknown`, `resolved`, `dismissed`) and review note. Each review is also appended to `incident_reviews` with the previous state. Location fields left out are kept; fields sent as `null` are cleared. Latitude and longitude must be sent together.
- `POST /api/collection/run` — runs the pilot-corridor TinyFish web and news searches (`PILOT_SEARCHES`, see [docs/PILOT.md](../docs/PILOT.md)), or a targeted search when the optional body names a `road`, `place` or `event_type`; `window_days` limits results by recency. New pages are read with TinyFish Fetch. Each run is logged. Results are deduplicated by normalised source URL and stored as unverified. Without `TINYFISH_API_KEY`, returns `not_configured` and does not invent fallback reports.

Recommendations never state that a road is clear: `proceed_cautiously` requires every non-dismissed report to have a reviewer-confirmed location with none near the route, and vehicle restrictions are always reported as unchecked. An unknown location is not matched to a route, and no reports do not imply that a road is clear. OSRM's public routing service and OpenStreetMap Nominatim require internet access. Successful responses are cached in the `provider_cache` table (geocodes 30 days, routes 24 hours), which respects their usage policies, and a cached copy is served if a provider fails.

## Existing tracking API

The original shipment trace API remains available at `/health` and `/api/v1/*` (summary, traces, trace events). It uses the same SQLite database.

## Configuration

Set app name, API prefix, SQLite path, CORS origins, `TINYFISH_API_KEY`, and geocoder User-Agent in `.env`. Never put service keys in frontend environment variables.

## Tests

```sh
pip install -r requirements-dev.txt
pytest
```

Tests use a temporary SQLite database and replace Nominatim, OSRM and TinyFish with fakes, so they run offline. `tests/test_failures.py` fakes those services at the network layer, so the real request, timeout and parsing code runs. `tests/test_browser.py` runs the built dashboard in Chrome against the API (`pytest -m e2e`; skipped without npm or Chrome).

## Failure behaviour

- **Provider timeout or dropped connection:** 502 naming the slow host, for example "router.project-osrm.org did not answer within 15 s". A cached route or geocode is served instead when one exists.
- **Malformed provider data:** a geocode or route without usable coordinates is a 502 and is never cached. Malformed TinyFish results are skipped one by one and never invented or repaired.
- **Database failure** (missing, corrupt, unwritable or locked): every endpoint answers 503 with a plain reason and CORS headers, so the dashboard can show it. A failed write is rolled back completely. The API still starts when the database cannot be opened, and `/api/health` reports the problem.
