// Every request from the dashboard to the INDIA-TRACE backend goes through this file.
// Service keys (TinyFish) stay on the backend; the browser only knows the API's base URL.
export const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

// FastAPI returns validation errors as a list of objects, and some failures are not JSON at all.
async function readJson(response, fallback) {
  const payload = await response.json().catch(() => null)
  if (response.ok && payload) return payload
  const detail = payload?.detail
  const message = Array.isArray(detail) ? detail.map((item) => String(item.msg || '').replace(/^Value error, /, '')).join(' ') : detail
  throw new Error(message || `${fallback} (HTTP ${response.status})`)
}

async function request(path, fallback, { method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch(`${API_URL}${path}`, body === undefined ? { method } : {
      method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
  } catch {
    // fetch only rejects when the request never reached a server.
    throw new Error(`${fallback} The API at ${API_URL} is not reachable. Check that the backend is running.`)
  }
  return readJson(response, fallback)
}

export const getHealth = () => request('/api/health', 'API health check failed.')

export const listIncidents = () => request('/api/incidents', 'Could not load evidence records.')

export const getLatestCollectionRun = () => request('/api/collection/runs?limit=1', 'Could not load the collection log.')
  .then((runs) => runs[0] || null)

/** @param {{origin: string, destination: string, vehicle_type: string, priority: string}} plan */
export const planRoute = (plan) => request('/api/routes/plan', 'Could not plan this route.', { method: 'POST', body: plan })

/** No road, place or event_type runs the pilot-corridor searches; any of them runs a targeted search. */
export const runCollection = (options) => request('/api/collection/run', 'Collection could not run.', { method: 'POST', body: options })

export const reviewIncident = (id, review) => request(`/api/incidents/${id}/review`, 'Could not save evidence review.', { method: 'PATCH', body: review })

export const flagIncident = (id, flag) => request(`/api/incidents/${id}/flags`, 'Could not send the flag.', { method: 'POST', body: flag })

/** Health and evidence load together; the dashboard counts as online only when both answer. */
export async function loadWorkspace() {
  const [health, incidents] = await Promise.allSettled([getHealth(), listIncidents()])
  return {
    online: health.status === 'fulfilled' && incidents.status === 'fulfilled',
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
