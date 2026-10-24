# INDIA-TRACE frontend

React, Vite, Leaflet and React Leaflet operations dashboard.

```sh
cd Frontend
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). The backend normally runs at `http://127.0.0.1:8000`; set `VITE_API_URL` in a local `.env` file to override that base URL. Route planning uses the backend's live Nominatim/OSRM adapters. Evidence collection needs a TinyFish API key configured only on the backend. No mock incidents are generated. If the API/routing services are offline, the exact Guwahati–Shillong example can load a saved, timestamped OSRM route snapshot. The UI labels it historical and not for dispatch; other route queries remain unavailable offline.

`npm run build` creates the production frontend in `dist/`.
