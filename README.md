# INDIA-TRACE · Team Tech Titans

Road disruption intelligence for essential deliveries in India, with a Northeast India focus.

## Run the end-to-end demo

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

## Current capability and limits

- Route planning resolves place names with OpenStreetMap Nominatim and gets route geometry, distance, and time estimates from OSRM.
- TinyFish collection stores actual search result URLs and snippets as unverified evidence candidates. No seed/fake incidents are inserted.
- Reports with no source timestamp are marked freshness `unknown`; collection does not infer incident coordinates from vague text.
- A human reviewer can save a verification state and note. Coordinates can be entered only after checking the linked source; the app then tests proximity to candidate routes.
- Dispatch advice stays at `verify_before_dispatch` until disruption evidence and vehicle restrictions are independently verified.
- The exact Guwahati–Shillong example has a historical OSRM snapshot fallback for offline presentation; it is marked not for dispatch. Other routes need live geocoding and OSRM. Map tiles and TinyFish collection also require internet.
- The original shipment trace/event API is preserved under `/api/v1/*`.

See [Backend setup and API details](Backend/README.md) and [Frontend details](Frontend/README.md).
