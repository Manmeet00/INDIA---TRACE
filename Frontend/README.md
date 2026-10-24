# INDIA-TRACE frontend

React, Vite, Leaflet and React Leaflet operations dashboard.

```sh
cd Frontend
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). The backend normally runs at `http://127.0.0.1:8000`; set `VITE_API_URL` in a local `.env` file to override that base URL. Route planning uses the backend's live Nominatim/OSRM adapters. Evidence collection needs a TinyFish API key configured only on the backend. No mock incidents are generated. If the API/routing services are offline, the exact Guwahati–Shillong example can load a saved, timestamped OSRM route snapshot. The UI labels it historical and not for dispatch; other route queries remain unavailable offline.

`npm run build` creates the production frontend in `dist/`.

## Code layout

| Path | What it owns |
|---|---|
| `src/services/api.js` | The service layer. Every backend request goes through it, along with error messages and the offline route snapshot. Components never call `fetch` directly. |
| `src/hooks/useWorkspace.js` | API status, stored evidence and the latest collection run. |
| `src/hooks/useEvidenceFilters.js` | Search text and the evidence-list filters. |
| `src/components/RoutePlanner.jsx` | The route form: origin, destination, vehicle and priority. |
| `src/components/RouteMap.jsx` | Chooses the base map (Mappls with a key, OpenStreetMap otherwise or as fallback), the Leaflet map, and the map layer toggles (`MapLayers`). |
| `src/components/MapplsMap.jsx`, `src/lib/mappls.js` | The Mappls Web SDK v3 map: loads the SDK once and draws routes and evidence on it. |
| `src/components/RouteComparison.jsx` | Route cards, dispatch guidance, and reports that may affect the route. |
| `src/components/EvidenceDesk.jsx` | The selected report: provenance, hints, review and correction flags. |
| `src/components/EvidenceList.jsx` | Collection controls, targeted search, filters and the report list. |
| `src/lib/format.js` | Labels for API codes, plus date, distance and duration formatting. |
| `src/App.jsx` | Page layout and the state shared between panels. |
