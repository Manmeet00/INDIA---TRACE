// Every request from the dashboard to the INDIA-TRACE backend goes through this file.
// Service keys (TinyFish) stay on the backend; the browser only knows the API's base URL.
export const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

// Errors carry the HTTP status (absent when no server answered), so callers can tell a stopped API from a failing one.
function apiError(message, status) {
  return Object.assign(new Error(message), { status })
}

// FastAPI returns validation errors as a list of objects, and some failures are not JSON at all.
async function readJson(response, fallback) {
  const payload = await response.json().catch(() => null)
  if (response.ok && payload) return payload
  const detail = payload?.detail
  const message = Array.isArray(detail) ? detail.map((item) => String(item.msg || '').replace(/^Value error, /, '')).join(' ') : detail
  throw apiError(message || `${fallback} (HTTP ${response.status})`, response.status)
}

// Longer than the backend's own provider timeouts, so a slow provider reports its own error first.
const TIMEOUT_MS = { read: 20000, plan: 60000 }

async function request(path, fallback, { method = 'GET', body, timeoutMs = TIMEOUT_MS.read } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let response
  try {
    response = await fetch(`${API_URL}${path}`, {
      method, signal: controller.signal,
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    })
    return await readJson(response, fallback)
  } catch (error) {
    if (controller.signal.aborted) throw apiError(`${fallback} The API did not answer within ${timeoutMs / 1000} seconds. Refresh to see whether it finished.`)
    if (response) throw error
    // fetch only rejects without a response when the request never reached a server.
    throw apiError(`${fallback} The API at ${API_URL} is not reachable. Check that the backend is running.`)
  } finally { clearTimeout(timer) }
}

export const getHealth = () => request('/api/health', 'API health check failed.')

// The API's maximum; the default page of 100 would silently leave older reports out.
export const listIncidents = () => request('/api/incidents?limit=500', 'Could not load evidence records.')

export const getLatestCollectionRun = () => request('/api/collection/runs?limit=1', 'Could not load the collection log.')
  .then((runs) => runs[0] || null)

/** @param {{origin: string, destination: string, vehicle_type: string, priority: string}} plan */
export const planRoute = (plan) => request('/api/routes/plan', 'Could not plan this route.', { method: 'POST', body: plan, timeoutMs: TIMEOUT_MS.plan })

/**
 * Starts a background collection: no road, place or event_type runs the region's corridor searches, any of them
 * a targeted search. Resolves to { status: 'running', run_id } or { status: 'not_configured', message }.
 */
export const startCollection = (options) => request('/api/collection/jobs', 'Collection could not start.', { method: 'POST', body: options })

/** Starts a background re-check of report pages; without ids, of the reports that are due. */
export const startRecheck = (ids) => request('/api/recheck/jobs', 'Re-check could not start.', { method: 'POST', body: ids ? { incident_ids: ids } : {} })

export const getRun = (id) => request(`/api/collection/runs/${id}`, 'Could not follow the run.')

/** Polls a background run until it finishes, passing each in-progress state to onProgress. */
export async function followRun(id, onProgress, intervalMs = 1500) {
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    const run = await getRun(id)
    if (run.status !== 'running') return run
    onProgress(run)
  }
}

/** Reads one report's page again now; resolves to the updated report. */
export const recheckIncident = (id) => request(`/api/incidents/${id}/recheck`, 'Could not re-check this source.', { method: 'POST', timeoutMs: TIMEOUT_MS.plan })

/** Type-ahead suggestions for the route form: [{ label, detail, value, source }]. */
export const suggestPlaces = (text) => request(`/api/places/suggest?q=${encodeURIComponent(text)}`, 'Could not load place suggestions.')

/** Current US AQI at a point in India: { us_aqi, band, pm2_5, pm10, time }. */
export const getAirQuality = (latitude, longitude) => request(`/api/air-quality?lat=${latitude.toFixed(4)}&lon=${longitude.toFixed(4)}`, 'Air quality is unavailable.')

/** Place names (OpenStreetMap) for a map view: { labels: [{ name, kind, latitude, longitude }], status }. */
export const getMapLabels = ({ south, west, north, east }, zoom) =>
  request(`/api/map-labels?south=${south.toFixed(3)}&west=${west.toFixed(3)}&north=${north.toFixed(3)}&east=${east.toFixed(3)}&zoom=${zoom}`, 'Place names are unavailable.')

export const getRegion = () => request('/api/region', 'Could not load the region.')

/** { provider: 'mappls' | 'osm', mappls_key }: the base map to draw. */
export const getMapConfig = () => request('/api/map-config', 'Could not load the map settings.')

export const getMetrics = () => request('/api/metrics', 'Could not load monitoring figures.')

export const reviewIncident = (id, review) => request(`/api/incidents/${id}/review`, 'Could not save evidence review.', { method: 'PATCH', body: review })

export const flagIncident = (id, flag) => request(`/api/incidents/${id}/flags`, 'Could not send the flag.', { method: 'POST', body: flag })

/**
 * Health and evidence load together. Status is online when both answer, offline when no server answered,
 * and degraded when the API answered with an error (for example a 503 because the database failed).
 */
export async function loadWorkspace() {
  const [health, incidents] = await Promise.allSettled([getHealth(), listIncidents()])
  const failure = [health, incidents].find((result) => result.status === 'rejected')?.reason
  return {
    status: !failure ? 'online' : failure.status ? 'degraded' : 'offline',
    problem: failure?.message || '',
    health: health.status === 'fulfilled' ? health.value : null,
    incidents: incidents.status === 'fulfilled' ? incidents.value : null,
  }
}

// A timestamped OSRM response saved with the frontend, served from its own origin rather than the API.
const OFFLINE_ROUTE = { origin: 'guwahati', destination: 'shillong' }

export function hasOfflineRoute({ origin, destination }) {
  return origin.trim().toLowerCase().startsWith(OFFLINE_ROUTE.origin) && destination.trim().toLowerCase().startsWith(OFFLINE_ROUTE.destination)
}

export async function loadOfflineRoute() {
  const response = await fetch(`${import.meta.env.BASE_URL}offline-demo-route.json`)
  if (!response.ok) throw new Error('Saved route snapshot is unavailable.')
  return response.json()
}

// India's land boundary, served with the frontend: the official boundary as per the Survey of India,
// from datameet/maps (CC0), simplified to about 500 m. Resolves to the outer ring of each land part, as [lng, lat].
export async function loadIndiaBoundary() {
  const response = await fetch(`${import.meta.env.BASE_URL}india-boundary.geojson`)
  if (!response.ok) throw new Error('India boundary is unavailable.')
  const data = await response.json()
  return data.features[0].geometry.coordinates.map((polygon) => polygon[0])
}
