import { useCallback, useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, ZoomControl, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import './App.css'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

function Icon({ name, size = 18 }) {
  const paths = {
    home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1Z"/><path d="M9 21v-6h6v6"/></>,
    route: <><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.5 18H12a3 3 0 0 0 3-3v-3a3 3 0 0 1 3-3"/></>,
    alert: <><path d="m12 3 9 16H3l9-16Z"/><path d="M12 9v4m0 3h.01"/></>,
    layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></>,
    search: <><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/></>,
    pin: <><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    arrow: <><path d="M5 12h14m-6-6 6 6-6 6"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.5 9a7 7 0 0 1 12-2L20 12M4 12l2.5 5a7 7 0 0 0 12-2"/></>,
    check: <><path d="m5 12 4 4L19 6"/></>,
    truck: <><path d="M3 6h11v11H3zM14 10h4l3 3v4h-7z"/><circle cx="7.5" cy="18" r="1.5"/><circle cx="17.5" cy="18" r="1.5"/></>,
    close: <><path d="m6 6 12 12M18 6 6 18"/></>,
    mountain: <><path d="m3 20 6.5-12 4 7 2.5-4L21 20Z"/></>,
    water: <><path d="M3 8c2 0 2-1.5 4.5-1.5S9.5 8 12 8s2-1.5 4.5-1.5S19 8 21 8M3 13c2 0 2-1.5 4.5-1.5S9.5 13 12 13s2-1.5 4.5-1.5S19 13 21 13M3 18c2 0 2-1.5 4.5-1.5S9.5 18 12 18s2-1.5 4.5-1.5S19 18 21 18"/></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function formatDistance(meters) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${meters} m`
}

function formatDuration(seconds) {
  const mins = Math.round(seconds / 60)
  const hours = Math.floor(mins / 60)
  const rest = mins % 60
  return hours ? `${hours} hr ${rest} min` : `${rest} min`
}

function formatTime(value) {
  if (!value) return 'Time not provided by source'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? 'Time not provided by source' : new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

// published_estimate is parsed by the API; approximate values came from a date or relative text like "3 months ago".
function formatPublished(incident) {
  if (!incident.published_estimate) return incident.published_at ? `Source time unclear: “${incident.published_at}”` : 'Time not provided by source'
  if (!incident.published_approximate) return formatTime(incident.published_estimate)
  const day = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium' }).format(new Date(incident.published_estimate))
  return /ago$/i.test(incident.published_at) ? `≈ ${day} (“${incident.published_at}” at collection)` : day
}

function formatHours(hours) {
  return hours >= 48 ? `${Math.round(hours / 24)} days` : `${hours} h`
}

// Freshness windows differ by event type (API: freshness_window_h), e.g. 12 h for accidents, 72 h for landslides.
function freshnessLabel(item) {
  const window = formatHours(item.freshness_window_h || 24)
  return item.freshness === 'fresh' ? `Within ${window} window` : item.freshness === 'stale' ? `Older than ${window} window` : 'Source time unknown'
}

const LOCATION_LABELS = { precise: 'Reviewer-confirmed coordinates', road_mentioned: 'Road named · exact spot unknown', place_mentioned: 'Place named · exact spot unknown', none: 'No location in source' }
const FLAG_REASONS = { outdated: 'Outdated', wrong_location: 'Wrong location', duplicate: 'Duplicate', not_relevant: 'Not relevant', other: 'Other' }
const TIME_WINDOWS = [['1', 'Last 24 hours'], ['7', 'Last 7 days'], ['30', 'Last 30 days'], ['365', 'Last year']]
const INACTIVE_STATES = ['dismissed', 'resolved']
const PILOT_ROADS = ['NH-6', 'NH-306', 'NH-27', 'NH-37', 'NH-2', 'NH-10']

const RECOMMENDATIONS = {
  proceed_cautiously: { label: 'Proceed cautiously', pill: 'Proceed with care', tone: 'proceed' },
  consider_alternative: { label: 'Consider an alternative', pill: 'Alternative advised', tone: 'alternative' },
  verify_before_dispatch: { label: 'Verify before dispatch', pill: 'Verify first', tone: 'verify' },
}

// Event types are keyword tags from the API. The map groups the less common ones under "other".
const EVENT_LABELS = { closure: 'Closure', landslide: 'Landslide', flood: 'Flood', bridge: 'Bridge', weather: 'Weather', accident: 'Accident', construction: 'Works', other: 'Other' }
const MAP_CATEGORIES = [['closure', 'Road closures'], ['landslide', 'Landslides'], ['flood', 'Floods'], ['bridge', 'Bridge damage'], ['other', 'Other reports']]

// evidence_status comes from the API: stale outranks a reviewer's confirmation so old reports never read as current.
const STATUS_LABELS = { confirmed: 'Confirmed by reviewer', corroborated: 'Corroborated', unverified: 'Unverified', conflicting: 'Conflicting', stale: 'Stale', unknown: 'Unknown', resolved: 'Resolved', dismissed: 'Dismissed' }

function statusLabel(item) {
  return item.evidence_status === 'stale' && item.verification === 'confirmed' ? 'Stale · confirmed earlier' : STATUS_LABELS[item.evidence_status] || item.verification
}

function mapCategory(item) {
  return MAP_CATEGORIES.some(([key]) => key === item.event_type) ? item.event_type : 'other'
}

function adviceFor(code) {
  return RECOMMENDATIONS[code] || RECOMMENDATIONS.verify_before_dispatch
}

function exposureSummary(exposure) {
  if (!exposure) return 'Disruption exposure not assessed'
  const km = `${exposure.tolerance_m / 1000} km`
  const nearby = Object.values(exposure.nearby).reduce((total, count) => total + count, 0)
  const parts = [nearby ? `${nearby} report${nearby === 1 ? '' : 's'} within ${km}${exposure.nearby.confirmed ? ` (${exposure.nearby.confirmed} confirmed)` : ''}` : `No located reports within ${km}`]
  const mentioned = exposure.highway_mention_ids?.length || 0
  if (mentioned) parts.push(`${mentioned} name${mentioned === 1 ? 's' : ''} ${Object.keys(exposure.highway_mentions).join(', ')} (location unconfirmed)`)
  if (exposure.unlocated_reports - mentioned > 0) parts.push(`${exposure.unlocated_reports - mentioned} unlocated`)
  return parts.join(' · ')
}

// FastAPI returns validation errors as a list of objects, and some failures are not JSON at all.
async function readJson(response, fallback) {
  const payload = await response.json().catch(() => null)
  if (response.ok && payload) return payload
  const detail = payload?.detail
  const message = Array.isArray(detail) ? detail.map((item) => String(item.msg || '').replace(/^Value error, /, '')).join(' ') : detail
  throw new Error(message || `${fallback} (HTTP ${response.status})`)
}

// Duplicate, conflict and mention hints come from text heuristics in the API, never from verification.
function ReportHints({ incident, incidents, onSelect }) {
  const byId = new Map(incidents.map((item) => [item.id, item]))
  const conflicts = incident.conflict_ids || []
  const corroborating = incident.corroborating_ids || []
  const duplicates = incident.duplicate_ids || []
  const listed = [...conflicts, ...corroborating, ...duplicates]
  const links = [
    ...conflicts.map((id) => ['conflict', 'Possible conflict', id]),
    ...corroborating.map((id) => ['corroborating', 'Independent source agrees', id]),
    ...duplicates.map((id) => ['duplicate', 'Possible duplicate · not counted as confirmation', id]),
    ...(incident.related_ids || []).filter((id) => !listed.includes(id)).map((id) => ['related', 'Same highway', id]),
  ].filter(([, , id]) => byId.has(id)).slice(0, 5)
  const mentions = [...(incident.mentions?.highways || []), ...(incident.mentions?.places || [])]
  if (!links.length && !mentions.length) return null
  return <div className="report-hints">
    {mentions.length > 0 && <div className="mention-row"><small>Mentions</small>{mentions.map((mention) => <span className="mention-chip" key={mention}>{mention}</span>)}</div>}
    {links.map(([kind, label, id]) => <button type="button" key={`${kind}-${id}`} className={`report-link ${kind}`} onClick={() => onSelect(id)}><b>{label}</b><span>{byId.get(id).title}</span></button>)}
    <small className="hint-note">Automatic text hints. Check the sources before acting on them.</small>
  </div>
}

// Which reports may affect the selected route and why (report 6.6), plus per-highway coverage gaps.
function RouteImpact({ route, note, onSelect }) {
  if (!route?.impact_reports && !route?.coverage) return null
  return <div className="route-impact">
    <div className="impact-heading"><b>Reports that may affect Route {route.priority_rank}</b>{note && <small>{note}</small>}</div>
    {route.coverage && <div className="coverage">
      <div className="coverage-chips">{route.coverage.highways.map((row) => <span key={row.highway} className={`coverage-chip ${row.fresh ? 'covered' : 'gap'}`}>{row.highway} · {row.km} km · {row.reports} report{row.reports === 1 ? '' : 's'}{row.fresh ? ` · ${row.fresh} recent` : ' · none recent'}</span>)}</div>
      <p>{route.coverage.note}</p>
    </div>}
    {route.impact_reports?.length
      ? route.impact_reports.map((report) => <button type="button" className="impact-row" key={report.id} onClick={() => onSelect(report.id)}>
        <span className="impact-score" title="Relevance score out of 100">{report.score}</span>
        <span className="impact-copy"><b>{report.title}</b><small>{report.source_name} · {STATUS_LABELS[report.evidence_status] || report.evidence_status}</small><span className="impact-factors">{report.factors.slice(0, 2).join(' · ')}</span></span>
      </button>)
      : <p className="impact-empty">No collected report is located near this route or names one of its highways.</p>}
  </div>
}

// Where a report came from: the TinyFish query, the page TinyFish Fetch read, and every timestamp kept separately.
function Provenance({ incident }) {
  const fetched = incident.fetched_at ? (incident.fetch_error ? `Could not read page: ${incident.fetch_error}` : `TinyFish Fetch · ${formatTime(incident.fetched_at)}`) : 'Not fetched'
  const dateSource = incident.published_source === 'page' ? ' (from the page)' : incident.published_source === 'search' ? ' (from the search result)' : ''
  return <details className="provenance"><summary>Provenance · how this report was found</summary>
    <dl>
      <dt>Found by</dt><dd>TinyFish {incident.search_kind === 'news' ? 'news' : 'web'} search{incident.search_query ? ` · “${incident.search_query}”` : ' · query not recorded'}</dd>
      <dt>Published</dt><dd>{formatPublished(incident)}{dateSource}</dd>
      <dt>Collected</dt><dd>{formatTime(incident.collected_at)}</dd>
      <dt>Last seen</dt><dd>{incident.last_seen_at ? formatTime(incident.last_seen_at) : 'Not re-checked yet'}</dd>
      <dt>Page</dt><dd>{fetched}</dd>
      {incident.page_author && <><dt>Author</dt><dd>{incident.page_author}</dd></>}
    </dl>
    {incident.page_description && <p className="page-description">“{incident.page_description}”</p>}
  </details>
}

function DashboardMap({ plan, incidents, selectedRoute, selectedIncident, onSelectIncident, hiddenTypes }) {
  const route = plan?.routes?.find((item) => item.id === selectedRoute) || plan?.routes?.[0]
  const center = plan?.origin ? [plan.origin.latitude, plan.origin.longitude] : [26.2, 92.4]
  return <MapContainer key={`${plan?.origin?.latitude || 'default'}-${plan?.destination?.latitude || 'default'}`} center={center} zoom={plan ? 7 : 6} zoomControl={false} className="map-canvas">
    {route && <MapBounds geometry={route.geometry} />}
    <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    <ZoomControl position="bottomright" />
    {plan?.routes && [...plan.routes].sort((a, b) => (a.id === route?.id) - (b.id === route?.id)).map((item) => <Polyline key={item.id} positions={item.geometry.coordinates.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: item.id === route?.id ? '#0878e8' : '#64748b', opacity: item.id === route?.id ? 0.95 : 0.55, weight: item.id === route?.id ? 5 : 3, dashArray: item.id === route?.id ? undefined : '8 9' }} />)}
    {plan?.origin && <CircleMarker center={[plan.origin.latitude, plan.origin.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#079352', fillOpacity: 1 }}><Tooltip>Origin · {plan.origin.name}</Tooltip></CircleMarker>}
    {plan?.destination && <CircleMarker center={[plan.destination.latitude, plan.destination.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#e44a58', fillOpacity: 1 }}><Tooltip>Destination · {plan.destination.name}</Tooltip></CircleMarker>}
    {incidents.filter((item) => !INACTIVE_STATES.includes(item.verification) && !hiddenTypes.includes(mapCategory(item)) && item.latitude != null && item.longitude != null).map((item) => <CircleMarker key={item.id} center={[item.latitude, item.longitude]} radius={selectedIncident?.id === item.id ? 9 : 7} eventHandlers={{ click: () => onSelectIncident(item.id) }} pathOptions={{ color: '#fff', weight: 2, fillColor: item.evidence_status === 'confirmed' ? '#df3946' : item.evidence_status === 'stale' ? '#9ba8b8' : '#e99b28', fillOpacity: 0.95 }}><Tooltip>{item.title} · {statusLabel(item)}</Tooltip></CircleMarker>)}
  </MapContainer>
}

function MapBounds({ geometry }) {
  const map = useMap()
  useEffect(() => {
    const points = geometry.coordinates.map(([longitude, latitude]) => [latitude, longitude])
    if (points.length > 1) map.fitBounds(points, { padding: [36, 36], maxZoom: 10 })
  }, [geometry, map])
  return null
}

function App() {
  const [origin, setOrigin] = useState('Guwahati, Assam')
  const [destination, setDestination] = useState('Shillong, Meghalaya')
  const [vehicle, setVehicle] = useState('truck')
  const [priority, setPriority] = useState('cautious')
  const [plan, setPlan] = useState(null)
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [incidents, setIncidents] = useState([])
  const [selectedIncidentId, setSelectedIncidentId] = useState(null)
  const [search, setSearch] = useState('')
  const [routeLoading, setRouteLoading] = useState(false)
  const [collectionLoading, setCollectionLoading] = useState(false)
  const [routeError, setRouteError] = useState('')
  const [collectionMessage, setCollectionMessage] = useState('')
  const [reviewNotes, setReviewNotes] = useState({})
  const [reviewStatuses, setReviewStatuses] = useState({})
  const [reviewLocations, setReviewLocations] = useState({})
  const [reviewBusyId, setReviewBusyId] = useState(null)
  const [apiStatus, setApiStatus] = useState('checking')
  const [hiddenTypes, setHiddenTypes] = useState([])
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [regionFilter, setRegionFilter] = useState('all')
  const [roadFilter, setRoadFilter] = useState('all')
  const [timeFilter, setTimeFilter] = useState('all')
  const [publishedAfter, setPublishedAfter] = useState(null)
  const [sourceFilter, setSourceFilter] = useState('all')
  const [refreshing, setRefreshing] = useState(false)
  const [lastRun, setLastRun] = useState(null)
  const [collectWindow, setCollectWindow] = useState('30')
  const [target, setTarget] = useState({ road: '', place: '', event_type: '' })
  const [flagDrafts, setFlagDrafts] = useState({})
  const [flagBusyId, setFlagBusyId] = useState(null)

  const loadLastRun = useCallback(() => fetch(`${API}/api/collection/runs?limit=1`)
    .then((response) => (response.ok ? response.json() : []))
    .then((runs) => setLastRun(runs[0] || null))
    .catch(() => { /* The run log is informational; the evidence list still loads without it. */ }), [])

  const refreshWorkspace = useCallback(async () => {
    const [healthResult, evidenceResult] = await Promise.allSettled([fetch(`${API}/api/health`), fetch(`${API}/api/incidents`)])
    const healthOk = healthResult.status === 'fulfilled' && healthResult.value.ok
    const evidenceOk = evidenceResult.status === 'fulfilled' && evidenceResult.value.ok
    setApiStatus(healthOk && evidenceOk ? 'online' : 'offline')
    if (evidenceOk) setIncidents(await evidenceResult.value.json())
    if (!evidenceOk) throw new Error('Could not load evidence records. Check that the API is running.')
    loadLastRun()
  }, [loadLastRun])

  useEffect(() => {
    let active = true
    Promise.allSettled([fetch(`${API}/api/health`), fetch(`${API}/api/incidents`)]).then(async ([healthResult, evidenceResult]) => {
      if (!active) return
      const healthOk = healthResult.status === 'fulfilled' && healthResult.value.ok
      const evidenceOk = evidenceResult.status === 'fulfilled' && evidenceResult.value.ok
      setApiStatus(healthOk && evidenceOk ? 'online' : 'offline')
      if (evidenceOk) setIncidents(await evidenceResult.value.json())
      loadLastRun()
    })
    return () => { active = false }
  }, [loadLastRun])

  const planRoute = async (event) => {
    event.preventDefault()
    setRouteLoading(true)
    setRouteError('')
    setPlan(null)
    setSelectedRoute(null)
    try {
      const response = await fetch(`${API}/api/routes/plan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin, destination, vehicle_type: vehicle, priority }),
      })
      const payload = await readJson(response, 'Could not plan this route.')
      setPlan(payload)
      setSelectedRoute(payload.routes[0]?.id || null)
    } catch (error) {
      if (origin.trim().toLowerCase().startsWith('guwahati') && destination.trim().toLowerCase().startsWith('shillong')) {
        try {
          const snapshotResponse = await fetch('/offline-demo-route.json')
          if (snapshotResponse.ok) {
            const snapshot = await snapshotResponse.json()
            setPlan(snapshot)
            setSelectedRoute(snapshot.routes[0]?.id || null)
            setRouteError(`Live services unavailable. Showing a saved OSRM snapshot from ${formatTime(snapshot.captured_at)}. This historical route is not for dispatch.`)
            return
          }
        } catch { /* Keep the original service error if the saved demo asset is unavailable. */ }
      }
      setRouteError(error.message || 'Route planning failed. Check the API and routing connection.')
    } finally { setRouteLoading(false) }
  }

  // No target runs the pilot-corridor searches; a road, place or event type runs a targeted search.
  const collect = async (targeted = {}) => {
    setCollectionLoading(true)
    setCollectionMessage('')
    try {
      const body = { window_days: Number(collectWindow) || null, ...Object.fromEntries(Object.entries(targeted).map(([key, value]) => [key, value || null])) }
      const response = await fetch(`${API}/api/collection/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const payload = await readJson(response, 'Collection could not run.')
      setCollectionMessage(payload.message)
      await refreshWorkspace()
    } catch (error) { setCollectionMessage(error.message || 'Collection failed.') }
    finally { setCollectionLoading(false) }
  }

  const refresh = async () => {
    setRefreshing(true)
    setCollectionMessage('')
    try {
      await refreshWorkspace()
      setCollectionMessage('Evidence and service status are up to date.')
    } catch (error) { setCollectionMessage(error.message) }
    finally { setRefreshing(false) }
  }

  const reviewIncident = async (incident) => {
    const note = (reviewNotes[incident.id] || '').trim()
    if (note.length < 3) {
      setCollectionMessage('Add a short review note before saving an evidence decision.')
      return
    }
    setReviewBusyId(incident.id)
    try {
      // Send only the location fields the reviewer touched: omitted fields are kept, empty ones are cleared.
      const location = reviewLocations[incident.id] || {}
      const body = { verification: reviewStatuses[incident.id] || incident.verification, review_note: note }
      if ('name' in location) body.location_text = location.name
      if ('latitude' in location || 'longitude' in location) {
        const latitude = location.latitude ?? incident.latitude ?? ''
        const longitude = location.longitude ?? incident.longitude ?? ''
        body.latitude = latitude === '' ? null : Number(latitude)
        body.longitude = longitude === '' ? null : Number(longitude)
      }
      const response = await fetch(`${API}/api/incidents/${incident.id}/review`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      await readJson(response, 'Could not save evidence review.')
      setCollectionMessage('Evidence review saved.')
      await refreshWorkspace()
      setReviewNotes((notes) => ({ ...notes, [incident.id]: '' }))
      setReviewLocations((locations) => ({ ...locations, [incident.id]: {} }))
    } catch (error) { setCollectionMessage(error.message || 'Could not save evidence review.') }
    finally { setReviewBusyId(null) }
  }

  const flagIncident = async (incident) => {
    const draft = flagDrafts[incident.id] || {}
    setFlagBusyId(incident.id)
    try {
      const response = await fetch(`${API}/api/incidents/${incident.id}/flags`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: draft.reason || 'outdated', note: draft.note?.trim() || null }),
      })
      await readJson(response, 'Could not send the flag.')
      setCollectionMessage('Flag sent for review. It does not change the report’s status.')
      setFlagDrafts((drafts) => ({ ...drafts, [incident.id]: {} }))
      await refreshWorkspace()
    } catch (error) { setCollectionMessage(error.message || 'Could not send the flag.') }
    finally { setFlagBusyId(null) }
  }

  const filterOptions = useMemo(() => ({
    regions: [...new Set(incidents.flatMap((item) => item.regions || []))].sort(),
    roads: [...new Set(incidents.flatMap((item) => item.mentions?.highways || []))].sort((a, b) => a.length - b.length || a.localeCompare(b)),
    sources: [...new Set(incidents.map((item) => item.source_name))].sort(),
  }), [incidents])
  const visibleIncidents = useMemo(() => {
    return incidents.filter((item) => `${item.title} ${item.summary} ${item.source_name}`.toLowerCase().includes(search.trim().toLowerCase())
      && (typeFilter === 'all' || (typeFilter === 'other' ? item.event_type === 'other' : item.event_types?.includes(typeFilter)))
      && (statusFilter === 'all' || item.evidence_status === statusFilter)
      && (regionFilter === 'all' || item.regions?.includes(regionFilter))
      && (roadFilter === 'all' || item.mentions?.highways?.includes(roadFilter))
      && (sourceFilter === 'all' || item.source_name === sourceFilter)
      && (publishedAfter === null || (item.published_estimate && new Date(item.published_estimate).valueOf() >= publishedAfter)))
  }, [incidents, search, typeFilter, statusFilter, regionFilter, roadFilter, sourceFilter, publishedAfter])
  const activeIncident = visibleIncidents.find((item) => item.id === selectedIncidentId) || visibleIncidents[0] || null
  const relevantIncidents = incidents.filter((item) => !INACTIVE_STATES.includes(item.verification))
  const typeSummary = (type) => {
    const matching = relevantIncidents.filter((item) => item.event_types?.includes(type))
    return `${matching.filter((item) => item.verification === 'confirmed').length} confirmed · ${matching.filter((item) => item.freshness === 'fresh').length} recent`
  }
  const typeCount = (type) => relevantIncidents.filter((item) => item.event_types?.includes(type)).length
  const locatedCount = (category) => relevantIncidents.filter((item) => item.latitude != null && mapCategory(item) === category).length
  const unknownLocationCount = relevantIncidents.filter((item) => item.latitude == null || item.longitude == null).length
  const sourceCount = new Set(incidents.map((item) => item.source_name)).size
  const chosenRoute = plan?.routes?.find((item) => item.id === selectedRoute)
  const advice = adviceFor(chosenRoute?.recommendation || plan?.recommendation)
  const adviceReasons = chosenRoute?.recommendation_reasons || (plan ? [plan.recommendation_reason] : [])

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#overview" aria-label="INDIA-TRACE home"><span className="brand-mark"><span /><span /><span /></span><span className="brand-copy"><b>INDIA-TRACE</b><small>Safer routes. Better decisions.</small></span></a>
      <nav className="side-nav" aria-label="Main navigation">
        <a className="nav-item active" href="#overview"><Icon name="home"/> <span>Overview</span></a>
        <a className="nav-item" href="#route-planning"><Icon name="route"/> <span>Plan route</span></a>
        <a className="nav-item" href="#evidence"><Icon name="alert"/> <span>Live evidence</span>{incidents.length > 0 && <span className="nav-count">{incidents.length}</span>}</a>
        <a className="nav-item" href="#map-section"><Icon name="layers"/> <span>Map view</span></a>
      </nav>
      <div className="sidebar-bottom">
        <div className="offline-card"><span className={`status-dot ${apiStatus}`} /><span><b>{apiStatus === 'online' ? 'API connected' : apiStatus === 'checking' ? 'Connecting…' : 'API unavailable'}</b><small>{apiStatus === 'online' ? 'Local intelligence service' : 'Start backend on port 8000'}</small></span></div>
        <div className="sidebar-note"><span className="sidebar-landscape" aria-hidden="true">⌁</span><p>Road intelligence for essential deliveries across Northeast India.</p></div>
        <div className="team-card"><div className="team-avatar">TT</div><div><b>Team Tech Titans</b><small>INDIA-TRACE workspace</small></div></div>
      </div>
    </aside>

    <main className="main-area" id="overview">
      <header className="topbar"><div className="topbar-brand"><span className="brand-mark small"><span /><span /><span /></span><span><b>INDIA-TRACE</b><small>Road risk dashboard</small></span></div><label className="global-search"><Icon name="search" size={19}/><input aria-label="Search evidence" placeholder="Search locations, roads, sources or reports…" value={search} onChange={(event) => setSearch(event.target.value)}/></label><div className="top-actions"><span className={`connection-label ${apiStatus}`}><i/>{apiStatus === 'online' ? 'API connected' : apiStatus === 'checking' ? 'Connecting' : 'API offline'}</span><div className="profile-avatar">TT</div><span className="profile-name">Tech Titans</span></div></header>

      <div className="page-content">
        <section className="summary-grid" aria-label="Workspace summary">
          <article className="summary-card red"><span className="summary-icon"><Icon name="alert" size={20}/></span><div><b>{typeCount('closure')}</b><span>Closure reports</span><small>{typeSummary('closure')}</small></div></article>
          <article className="summary-card amber"><span className="summary-icon"><Icon name="mountain" size={20}/></span><div><b>{typeCount('landslide')}</b><span>Landslide reports</span><small>{typeSummary('landslide')}</small></div></article>
          <article className="summary-card blue"><span className="summary-icon"><Icon name="water" size={20}/></span><div><b>{typeCount('flood')}</b><span>Flood / waterlogging</span><small>{typeSummary('flood')}</small></div></article>
          <article className="summary-card violet"><span className="summary-icon"><Icon name="pin" size={20}/></span><div><b>{unknownLocationCount}</b><span>Location unresolved</span><small>Cannot be placed on the map</small></div></article>
          <article className="summary-card green"><span className="summary-icon"><Icon name="check" size={20}/></span><div><b>{incidents.length}</b><span>Reports processed</span><small>{sourceCount} sources · {relevantIncidents.filter((item) => item.freshness === 'fresh').length} within freshness window</small></div></article>
        </section>

        <section className="workspace-grid">
          <div className="left-column">
            <article className="panel route-panel" id="route-planning">
              <div className="panel-heading"><div><span className="section-kicker">ROUTE PLANNER</span><h1>Plan your route</h1></div><span className="step-indicator">01 <i>/ 03</i></span></div>
              <form onSubmit={planRoute}>
                <label className="field-label" htmlFor="origin">FROM</label><div className="place-input"><Icon name="pin" size={17}/><input id="origin" value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="City or location" required minLength="2"/></div>
                <div className="field-label-row field-spaced"><label className="field-label" htmlFor="destination">TO</label><button type="button" className="swap-button" onClick={() => { setOrigin(destination); setDestination(origin) }} aria-label="Swap origin and destination" title="Swap origin and destination">⇅ Swap</button></div><div className="place-input"><Icon name="pin" size={17}/><input id="destination" value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="City or location" required minLength="2"/></div>
                <label className="field-label field-spaced" htmlFor="vehicle">VEHICLE TYPE</label><div className="select-wrap"><Icon name="truck" size={17}/><select id="vehicle" value={vehicle} onChange={(event) => setVehicle(event.target.value)}><option value="truck">Delivery truck</option><option value="van">Delivery van</option><option value="ambulance">Ambulance</option></select></div>
                <label className="field-label field-spaced" htmlFor="priority">ROUTE PRIORITY</label><div className="select-wrap"><Icon name="layers" size={17}/><select id="priority" value={priority} onChange={(event) => setPriority(event.target.value)}><option value="cautious">Cautious</option><option value="balanced">Balanced</option><option value="fastest">Fastest</option><option value="shortest">Shortest</option></select></div>
                <button className="primary-button" type="submit" disabled={routeLoading}>{routeLoading ? 'Finding routes…' : <><Icon name="search" size={17}/> Find candidate routes</>}</button>
                {routeError && <div className={plan?.offline_demo ? 'inline-demo-note' : 'inline-error'} role="status">{routeError}</div>}
              </form>
              <div className="route-disclaimer"><span>i</span><p>Route estimates do not confirm current road conditions or vehicle restrictions.</p></div>
            </article>

            <article className="panel map-options"><div className="panel-heading compact"><div><span className="section-kicker">MAP CONTENT</span><h2>Show on map</h2></div></div><label className="toggle-row"><span className="legend-swatch route-swatch"/>Routes<span className="toggle-note">{plan ? plan.routes.length : 0}</span></label>{MAP_CATEGORIES.map(([key, label]) => <label className="toggle-row" key={key}><span className="legend-swatch evidence-swatch"/>{label}<span className="toggle-note">{locatedCount(key)} on map</span><input type="checkbox" checked={!hiddenTypes.includes(key)} onChange={(event) => setHiddenTypes((types) => event.target.checked ? types.filter((type) => type !== key) : [...types, key])}/><span className="switch" aria-hidden="true"/></label>)}<p className="map-hint">Reports without reviewer-confirmed coordinates cannot be placed on the map.</p></article>
          </div>

          <div className="center-column" id="map-section">
            <article className="panel map-panel"><div className="map-heading"><div><span className="section-kicker">NORTHEAST INDIA · NETWORK VIEW</span><h2>{plan ? `${plan.origin.name.split(',')[0]} to ${plan.destination.name.split(',')[0]}` : 'Regional road intelligence'}</h2></div><span className={`map-status ${plan?.offline_demo ? 'demo' : ''}`}><i/>{plan?.offline_demo ? 'Historical snapshot' : plan ? `Routing fetched ${formatTime(plan.routing_fetched_at)}` : 'Map ready'}</span></div><div className="map-wrap"><DashboardMap plan={plan} incidents={incidents} selectedRoute={selectedRoute} selectedIncident={activeIncident} onSelectIncident={setSelectedIncidentId} hiddenTypes={hiddenTypes}/>{!plan && <div className="map-empty"><span className="map-empty-icon"><Icon name="route" size={22}/></span><b>Your route will appear here</b><span>Enter locations to compare candidate driving routes.</span></div>}<div className="map-legend"><span><i className="legend-route"/> Selected route</span><span><i className="legend-candidate"/> Other candidates</span><span><i className="legend-incident"/> Geolocated evidence</span></div></div><div className="map-foot"><span><Icon name="pin" size={14}/>{plan ? `${plan.origin.name.split(',')[0]} → ${plan.destination.name.split(',')[0]}` : 'Assam · Meghalaya · Northeast India'}</span><span>Map tiles © OpenStreetMap contributors</span></div></article>

            <section className="route-results"><div className="results-heading"><div><span className="section-kicker">ROUTE COMPARISON</span><h2>{plan ? `${plan.routes.length} candidate route${plan.routes.length === 1 ? '' : 's'}` : 'Compare your options'}</h2></div>{plan && <span className="results-provider">{plan.offline_demo ? 'Saved demo' : 'OSRM estimates'}</span>}</div>
              {plan?.routes?.length ? <div className="route-card-list">{plan.routes.map((route, index) => <button className={`route-card ${selectedRoute === route.id ? 'selected' : ''}`} key={route.id} onClick={() => setSelectedRoute(route.id)} aria-pressed={selectedRoute === route.id}><span className="route-radio"/><span className="route-main"><b>Route {index + 1} · {index === 0 ? 'Top estimate' : 'Alternative'}</b><small>{exposureSummary(route.exposure)} · vehicle fit unknown</small><span className="route-facts"><span><Icon name="clock" size={14}/>{formatDuration(route.duration_s)}</span><span><Icon name="route" size={14}/>{formatDistance(route.distance_m)}</span><span><Icon name="layers" size={14}/>{route.highways && Object.keys(route.highways).length ? `via ${Object.keys(route.highways).join(' · ')}` : plan.offline_demo ? 'Historical' : 'OSRM'}</span></span></span><span className={`risk-pill ${adviceFor(route.recommendation || plan.recommendation).tone}`}>{adviceFor(route.recommendation || plan.recommendation).pill}</span></button>)}</div> : <div className="route-empty"><div className="route-empty-icon"><Icon name="route" size={19}/></div><div><b>No route comparison yet</b><span>Plan a route to fetch provider distance and time estimates.</span></div></div>}
              {plan && <div className={`action-banner ${advice.tone}`} role="status"><span className="action-symbol">!</span><div><b>{advice.label}{chosenRoute ? ` · Route ${chosenRoute.priority_rank}` : ''}</b>{adviceReasons.map((reason) => <span key={reason}>{reason}</span>)}<span className="official-note">Follow official advisories from the district administration, the state disaster management authority and the road agency (NHIDCL / PWD).</span></div><small>DISPATCH GUIDANCE</small></div>}
              {plan && <RouteImpact route={chosenRoute} note={plan.impact_note} onSelect={(id) => { setSearch(''); setSelectedIncidentId(id) }}/>}
            </section>
          </div>

          <aside className="right-column" id="evidence">
            <article className="panel incident-panel"><div className="incident-panel-heading"><div><span className="section-kicker">ROAD DISRUPTION MONITOR</span><h2>Evidence desk <span className="evidence-count">{visibleIncidents.length}</span></h2></div><button className="icon-button" onClick={refresh} disabled={refreshing} aria-label="Refresh evidence and API status"><Icon name="refresh" size={17}/></button></div>
              {collectionMessage && <div className="collection-message" role="status">{collectionMessage}</div>}
              {activeIncident ? <><div className="selected-incident"><div className="incident-top"><span className="hint-badge">{EVENT_LABELS[activeIncident.event_type] || 'Other'}</span><span className={`verification-badge ${activeIncident.evidence_status}`}>{statusLabel(activeIncident)}</span><span className={`freshness-badge ${activeIncident.freshness}`}>{freshnessLabel(activeIncident)}</span>{activeIncident.open_flags?.length > 0 && <span className="hint-badge conflict">Flagged</span>}{activeIncident.conflict_ids?.length > 0 && <span className="hint-badge conflict">Possible conflict</span>}{activeIncident.duplicate_ids?.length > 0 && <span className="hint-badge">Possible duplicate</span>}</div><h3>{activeIncident.title}</h3><div className="incident-meta"><span><Icon name="pin" size={15}/>{activeIncident.location_text ? `${activeIncident.location_text} · reviewer-confirmed` : LOCATION_LABELS[activeIncident.location_confidence] || 'Location unknown'}</span><span><Icon name="layers" size={15}/>{activeIncident.regions?.length ? activeIncident.regions.join(', ') : 'Region not named in source'}</span><span><Icon name="clock" size={15}/>{formatPublished(activeIncident)}</span></div><p className="incident-summary">{activeIncident.summary || 'No source summary provided.'}</p><ReportHints incident={activeIncident} incidents={incidents} onSelect={(id) => { setSearch(''); setSelectedIncidentId(id) }}/><div className="source-link"><span className="source-avatar">{activeIncident.source_name.slice(0, 1).toUpperCase()}</span><span><b>{activeIncident.source_name}</b><small>Collected {formatTime(activeIncident.collected_at)}</small></span><a href={activeIncident.source_url} target="_blank" rel="noreferrer" aria-label={`Open source: ${activeIncident.source_name}`}><Icon name="arrow" size={16}/></a></div><div className="safety-callout"><span>!</span><p>The report is evidence to review. Current road status and impact are not confirmed.</p></div><Provenance incident={activeIncident}/>
                <details className="verified-location"><summary>Add reviewer-confirmed map location</summary><input aria-label={`Location name for ${activeIncident.title}`} placeholder="Location from source" value={reviewLocations[activeIncident.id]?.name ?? (activeIncident.location_text || '')} onChange={(event) => setReviewLocations((locations) => ({ ...locations, [activeIncident.id]: { ...locations[activeIncident.id], name: event.target.value } }))}/><div><input aria-label={`Latitude for ${activeIncident.title}`} type="number" min="-90" max="90" step="any" placeholder="Latitude" value={reviewLocations[activeIncident.id]?.latitude ?? (activeIncident.latitude ?? '')} onChange={(event) => setReviewLocations((locations) => ({ ...locations, [activeIncident.id]: { ...locations[activeIncident.id], latitude: event.target.value } }))}/><input aria-label={`Longitude for ${activeIncident.title}`} type="number" min="-180" max="180" step="any" placeholder="Longitude" value={reviewLocations[activeIncident.id]?.longitude ?? (activeIncident.longitude ?? '')} onChange={(event) => setReviewLocations((locations) => ({ ...locations, [activeIncident.id]: { ...locations[activeIncident.id], longitude: event.target.value } }))}/></div><small>Only enter coordinates you checked in the linked source. Empty both fields and save to remove a wrong location.</small></details>
                <div className="review-controls"><label className="sr-only" htmlFor={`review-status-${activeIncident.id}`}>Review status</label><select id={`review-status-${activeIncident.id}`} value={reviewStatuses[activeIncident.id] || activeIncident.verification} onChange={(event) => setReviewStatuses((statuses) => ({ ...statuses, [activeIncident.id]: event.target.value }))}><option value="unverified">Unverified</option><option value="confirmed">Confirmed</option><option value="conflicting">Conflicting</option><option value="unknown">Unknown</option><option value="resolved">Resolved (reopened / ended)</option><option value="dismissed">Dismissed (not relevant)</option></select><label className="sr-only" htmlFor={`review-note-${activeIncident.id}`}>Review note</label><input id={`review-note-${activeIncident.id}`} placeholder="Review note (required)" value={reviewNotes[activeIncident.id] || ''} onChange={(event) => setReviewNotes((notes) => ({ ...notes, [activeIncident.id]: event.target.value }))}/><button disabled={reviewBusyId === activeIncident.id || (reviewNotes[activeIncident.id] || '').trim().length < 3} onClick={() => reviewIncident(activeIncident)}>{reviewBusyId === activeIncident.id ? 'Saving…' : 'Save review'}</button></div>
                {activeIncident.review_history?.length > 0 ? <div className="review-history"><b>Review history</b>{activeIncident.review_history.slice(0, 5).map((entry) => <span key={entry.reviewed_at}>{formatTime(entry.reviewed_at)} · {entry.previous_verification || 'new'} → {entry.verification}{entry.location_changed ? ' · location updated' : ''} — {entry.review_note}</span>)}</div>
                  : activeIncident.review_note && <div className="review-history"><b>Last review · {formatTime(activeIncident.reviewed_at)}</b><span>{activeIncident.review_note}</span></div>}
                {activeIncident.open_flags?.length > 0 && <div className="open-flags"><b>{activeIncident.open_flags.length} open correction flag{activeIncident.open_flags.length === 1 ? '' : 's'} · the next review closes them</b>{activeIncident.open_flags.map((flag) => <span key={flag.created_at}>{FLAG_REASONS[flag.reason] || flag.reason} · {formatTime(flag.created_at)}{flag.note ? ` — ${flag.note}` : ''}</span>)}</div>}
                <details className="flag-form"><summary>Flag a problem with this record</summary><div><label className="sr-only" htmlFor={`flag-reason-${activeIncident.id}`}>Problem</label><select id={`flag-reason-${activeIncident.id}`} value={flagDrafts[activeIncident.id]?.reason || 'outdated'} onChange={(event) => setFlagDrafts((drafts) => ({ ...drafts, [activeIncident.id]: { ...drafts[activeIncident.id], reason: event.target.value } }))}>{Object.entries(FLAG_REASONS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><label className="sr-only" htmlFor={`flag-note-${activeIncident.id}`}>Details</label><input id={`flag-note-${activeIncident.id}`} maxLength="500" placeholder="What is wrong? (optional)" value={flagDrafts[activeIncident.id]?.note || ''} onChange={(event) => setFlagDrafts((drafts) => ({ ...drafts, [activeIncident.id]: { ...drafts[activeIncident.id], note: event.target.value } }))}/><button type="button" disabled={flagBusyId === activeIncident.id} onClick={() => flagIncident(activeIncident)}>{flagBusyId === activeIncident.id ? 'Sending…' : 'Send flag'}</button></div><small>Flags go to a reviewer. They never change the report’s status on their own.</small></details>
                </div></> : <div className="evidence-empty"><span className="empty-illustration"><Icon name="layers" size={24}/></span><b>{incidents.length ? 'No matching evidence' : 'No evidence collected yet'}</b><p>{incidents.length ? 'Try another search term or filter.' : 'No reports does not mean a road is clear.'}</p></div>}
            </article>

            <article className="panel evidence-list-panel"><div className="list-heading"><div><span className="section-kicker">SOURCE REPORTS</span><h2>Collected evidence</h2></div><button className="text-button" onClick={() => collect()} disabled={collectionLoading || apiStatus !== 'online'} title="Run the pilot-corridor searches">{collectionLoading ? 'Searching…' : 'Run collection'} <Icon name="arrow" size={14}/></button></div>
              <div className="collect-controls"><label htmlFor="collect-window">Search window</label><select id="collect-window" value={collectWindow} onChange={(event) => setCollectWindow(event.target.value)}>{TIME_WINDOWS.map(([days, label]) => <option key={days} value={days}>{label}</option>)}<option value="">Any time</option></select></div>
              <details className="targeted-search"><summary>Targeted search · road, place or event type</summary><div><label className="sr-only" htmlFor="target-road">Road</label><select id="target-road" value={target.road} onChange={(event) => setTarget((current) => ({ ...current, road: event.target.value }))}><option value="">Any road</option>{PILOT_ROADS.map((road) => <option key={road} value={road}>{road}</option>)}</select><label className="sr-only" htmlFor="target-place">Place or district</label><input id="target-place" maxLength="60" placeholder="Place or district" value={target.place} onChange={(event) => setTarget((current) => ({ ...current, place: event.target.value }))}/><label className="sr-only" htmlFor="target-type">Event type</label><select id="target-type" value={target.event_type} onChange={(event) => setTarget((current) => ({ ...current, event_type: event.target.value }))}><option value="">Any event</option>{Object.entries(EVENT_LABELS).filter(([key]) => key !== 'other').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button type="button" disabled={collectionLoading || apiStatus !== 'online' || !(target.road || target.place.trim() || target.event_type)} onClick={() => collect(target)}>Search</button></div><small>Runs TinyFish web and news search, then reads each new page with TinyFish Fetch.</small></details>
              {lastRun && <p className={`last-run ${lastRun.status}`}>Last collection {formatTime(lastRun.finished_at)} · {lastRun.stored} new · {lastRun.duplicates} re-seen · {lastRun.fetched} pages read{lastRun.fetch_failed ? ` (${lastRun.fetch_failed} unreadable)` : ''}{lastRun.failed_searches ? ` · ${lastRun.failed_searches} searches failed` : ''} · {(lastRun.duration_ms / 1000).toFixed(1)} s</p>}
              <div className="list-filters"><label className="sr-only" htmlFor="type-filter">Event type</label><select id="type-filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">All event types</option>{Object.entries(EVENT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><label className="sr-only" htmlFor="status-filter">Evidence status</label><select id="status-filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option>{Object.entries(STATUS_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><label className="sr-only" htmlFor="region-filter">Region</label><select id="region-filter" value={regionFilter} onChange={(event) => setRegionFilter(event.target.value)}><option value="all">All regions</option>{filterOptions.regions.map((region) => <option key={region} value={region}>{region}</option>)}</select><label className="sr-only" htmlFor="road-filter">Road</label><select id="road-filter" value={roadFilter} onChange={(event) => setRoadFilter(event.target.value)}><option value="all">All roads</option>{filterOptions.roads.map((road) => <option key={road} value={road}>{road}</option>)}</select><label className="sr-only" htmlFor="time-filter">Published</label><select id="time-filter" value={timeFilter} onChange={(event) => { setTimeFilter(event.target.value); setPublishedAfter(event.target.value === 'all' ? null : Date.now() - Number(event.target.value) * 86400000) }}><option value="all">Any publish time</option>{TIME_WINDOWS.map(([days, label]) => <option key={days} value={days}>{label}</option>)}</select><label className="sr-only" htmlFor="source-filter">Source</label><select id="source-filter" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="all">All sources</option>{filterOptions.sources.map((source) => <option key={source} value={source}>{source}</option>)}</select></div><div className="evidence-list">{visibleIncidents.length ? visibleIncidents.map((incident) => <button className={`evidence-row ${activeIncident?.id === incident.id ? 'active' : ''}`} key={incident.id} onClick={() => setSelectedIncidentId(incident.id)}><span className={`mini-status ${incident.evidence_status}`} title={statusLabel(incident)}/><span className="evidence-row-copy"><b>{incident.title}</b><small>{incident.source_name} · {formatPublished(incident)}{incident.conflict_ids?.length > 0 ? ' · possible conflict' : ''}</small></span><Icon name="arrow" size={14}/></button>) : <p className="list-empty">Reports from TinyFish appear here as unverified evidence candidates.</p>}</div></article>
            <div className="source-footnote"><Icon name="check" size={15}/><span>Evidence is unverified until independently reviewed. Dispatch advice remains cautious.</span></div>
          </aside>
        </section>
        <footer className="page-footer"><span>INDIA-TRACE <i>·</i> Team Tech Titans</span><span>{chosenRoute ? `Selected estimate · ${formatDistance(chosenRoute.distance_m)} · ${formatDuration(chosenRoute.duration_s)}` : 'Road intelligence for essential deliveries'}</span></footer>
      </div>
    </main>
  </div>
}

export default App
