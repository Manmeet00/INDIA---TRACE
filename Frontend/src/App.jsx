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

function freshnessLabel(value) {
  return value === 'fresh' ? 'Recent source time' : value === 'stale' ? 'Older source time' : 'Source time unknown'
}

const RECOMMENDATIONS = {
  proceed_cautiously: { label: 'Proceed cautiously', pill: 'Proceed with care', tone: 'proceed' },
  consider_alternative: { label: 'Consider an alternative', pill: 'Alternative advised', tone: 'alternative' },
  verify_before_dispatch: { label: 'Verify before dispatch', pill: 'Verify first', tone: 'verify' },
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
  const duplicates = incident.duplicate_ids || []
  const links = [
    ...conflicts.map((id) => ['conflict', 'Possible conflict', id]),
    ...duplicates.map((id) => ['duplicate', 'Possible duplicate', id]),
    ...(incident.related_ids || []).filter((id) => !conflicts.includes(id) && !duplicates.includes(id)).map((id) => ['related', 'Same highway', id]),
  ].filter(([, , id]) => byId.has(id)).slice(0, 5)
  const mentions = [...(incident.mentions?.highways || []), ...(incident.mentions?.places || [])]
  if (!links.length && !mentions.length) return null
  return <div className="report-hints">
    {mentions.length > 0 && <div className="mention-row"><small>Mentions</small>{mentions.map((mention) => <span className="mention-chip" key={mention}>{mention}</span>)}</div>}
    {links.map(([kind, label, id]) => <button type="button" key={`${kind}-${id}`} className={`report-link ${kind}`} onClick={() => onSelect(id)}><b>{label}</b><span>{byId.get(id).title}</span></button>)}
    <small className="hint-note">Automatic text hints. Check the sources before acting on them.</small>
  </div>
}

function DashboardMap({ plan, incidents, selectedRoute, selectedIncident, onSelectIncident, showEvidence }) {
  const route = plan?.routes?.find((item) => item.id === selectedRoute) || plan?.routes?.[0]
  const center = plan?.origin ? [plan.origin.latitude, plan.origin.longitude] : [26.2, 92.4]
  return <MapContainer key={`${plan?.origin?.latitude || 'default'}-${plan?.destination?.latitude || 'default'}`} center={center} zoom={plan ? 7 : 6} zoomControl={false} className="map-canvas">
    {route && <MapBounds geometry={route.geometry} />}
    <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    <ZoomControl position="bottomright" />
    {plan?.routes && [...plan.routes].sort((a, b) => (a.id === route?.id) - (b.id === route?.id)).map((item) => <Polyline key={item.id} positions={item.geometry.coordinates.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: item.id === route?.id ? '#0878e8' : '#64748b', opacity: item.id === route?.id ? 0.95 : 0.55, weight: item.id === route?.id ? 5 : 3, dashArray: item.id === route?.id ? undefined : '8 9' }} />)}
    {plan?.origin && <CircleMarker center={[plan.origin.latitude, plan.origin.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#079352', fillOpacity: 1 }}><Tooltip>Origin · {plan.origin.name}</Tooltip></CircleMarker>}
    {plan?.destination && <CircleMarker center={[plan.destination.latitude, plan.destination.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#e44a58', fillOpacity: 1 }}><Tooltip>Destination · {plan.destination.name}</Tooltip></CircleMarker>}
    {showEvidence && incidents.filter((item) => item.verification !== 'dismissed' && item.latitude != null && item.longitude != null).map((item) => <CircleMarker key={item.id} center={[item.latitude, item.longitude]} radius={selectedIncident?.id === item.id ? 9 : 7} eventHandlers={{ click: () => onSelectIncident(item.id) }} pathOptions={{ color: '#fff', weight: 2, fillColor: item.verification === 'confirmed' ? '#df3946' : '#e99b28', fillOpacity: 0.95 }}><Tooltip>{item.title} · {item.verification}</Tooltip></CircleMarker>)}
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
  const [showEvidence, setShowEvidence] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const refreshWorkspace = useCallback(async () => {
    const [healthResult, evidenceResult] = await Promise.allSettled([fetch(`${API}/api/health`), fetch(`${API}/api/incidents`)])
    const healthOk = healthResult.status === 'fulfilled' && healthResult.value.ok
    const evidenceOk = evidenceResult.status === 'fulfilled' && evidenceResult.value.ok
    setApiStatus(healthOk && evidenceOk ? 'online' : 'offline')
    if (evidenceOk) setIncidents(await evidenceResult.value.json())
    if (!evidenceOk) throw new Error('Could not load evidence records. Check that the API is running.')
  }, [])

  useEffect(() => {
    let active = true
    Promise.allSettled([fetch(`${API}/api/health`), fetch(`${API}/api/incidents`)]).then(async ([healthResult, evidenceResult]) => {
      if (!active) return
      const healthOk = healthResult.status === 'fulfilled' && healthResult.value.ok
      const evidenceOk = evidenceResult.status === 'fulfilled' && evidenceResult.value.ok
      setApiStatus(healthOk && evidenceOk ? 'online' : 'offline')
      if (evidenceOk) setIncidents(await evidenceResult.value.json())
    })
    return () => { active = false }
  }, [])

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

  const collect = async () => {
    setCollectionLoading(true)
    setCollectionMessage('')
    try {
      const response = await fetch(`${API}/api/collection/run`, { method: 'POST' })
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

  const visibleIncidents = useMemo(() => incidents.filter((item) => `${item.title} ${item.summary} ${item.source_name}`.toLowerCase().includes(search.trim().toLowerCase())), [incidents, search])
  const activeIncident = visibleIncidents.find((item) => item.id === selectedIncidentId) || visibleIncidents[0] || null
  const verifiedCount = incidents.filter((item) => item.verification === 'confirmed').length
  const unknownLocationCount = incidents.filter((item) => item.verification !== 'dismissed' && (item.latitude == null || item.longitude == null)).length
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
          <article className="summary-card red"><span className="summary-icon"><Icon name="alert" size={20}/></span><div><b>{incidents.length}</b><span>Evidence candidates</span><small>Unverified public reports</small></div></article>
          <article className="summary-card violet"><span className="summary-icon"><Icon name="search" size={20}/></span><div><b>{verifiedCount}</b><span>Confirmed by reviewer</span><small>Human reviewed status</small></div></article>
          <article className="summary-card amber"><span className="summary-icon"><Icon name="pin" size={20}/></span><div><b>{unknownLocationCount}</b><span>Location unresolved</span><small>Needs geographic review</small></div></article>
          <article className="summary-card blue"><span className="summary-icon"><Icon name="route" size={20}/></span><div><b>{plan?.routes?.length || 0}</b><span>Candidate routes</span><small>{plan ? 'Routing estimates' : 'Plan a route to compare'}</small></div></article>
          <article className="summary-card green"><span className="summary-icon"><Icon name="check" size={20}/></span><div><b>{sourceCount}</b><span>Source sites</span><small>{apiStatus === 'online' ? 'Connected workspace' : 'API connection needed'}</small></div></article>
        </section>

        <section className="workspace-grid">
          <div className="left-column">
            <article className="panel route-panel" id="route-planning">
              <div className="panel-heading"><div><span className="section-kicker">ROUTE PLANNER</span><h1>Plan your route</h1></div><span className="step-indicator">01 <i>/ 03</i></span></div>
              <form onSubmit={planRoute}>
                <label className="field-label" htmlFor="origin">FROM</label><div className="place-input"><Icon name="pin" size={17}/><input id="origin" value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="City or location" required minLength="2"/></div>
                <label className="field-label field-spaced" htmlFor="destination">TO</label><div className="place-input"><Icon name="pin" size={17}/><input id="destination" value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="City or location" required minLength="2"/></div>
                <label className="field-label field-spaced" htmlFor="vehicle">VEHICLE TYPE</label><div className="select-wrap"><Icon name="truck" size={17}/><select id="vehicle" value={vehicle} onChange={(event) => setVehicle(event.target.value)}><option value="truck">Delivery truck</option><option value="van">Delivery van</option><option value="ambulance">Ambulance</option></select></div>
                <label className="field-label field-spaced" htmlFor="priority">ROUTE PRIORITY</label><div className="select-wrap"><Icon name="layers" size={17}/><select id="priority" value={priority} onChange={(event) => setPriority(event.target.value)}><option value="cautious">Cautious</option><option value="balanced">Balanced</option><option value="fastest">Fastest</option><option value="shortest">Shortest</option></select></div>
                <button className="primary-button" type="submit" disabled={routeLoading}>{routeLoading ? 'Finding routes…' : <><Icon name="search" size={17}/> Find candidate routes</>}</button>
                {routeError && <div className={plan?.offline_demo ? 'inline-demo-note' : 'inline-error'} role="status">{routeError}</div>}
              </form>
              <div className="route-disclaimer"><span>i</span><p>Route estimates do not confirm current road conditions or vehicle restrictions.</p></div>
            </article>

            <article className="panel map-options"><div className="panel-heading compact"><div><span className="section-kicker">MAP CONTENT</span><h2>Show on map</h2></div></div><label className="toggle-row"><span className="legend-swatch route-swatch"/>Routes<span className="toggle-note">{plan ? plan.routes.length : 0}</span></label><label className="toggle-row"><span className="legend-swatch evidence-swatch"/>Geolocated evidence<input type="checkbox" checked={showEvidence} onChange={(event) => setShowEvidence(event.target.checked)} /><span className="switch" aria-hidden="true"/></label><p className="map-hint">Reports without reviewer-confirmed coordinates cannot be placed on the map.</p></article>
          </div>

          <div className="center-column" id="map-section">
            <article className="panel map-panel"><div className="map-heading"><div><span className="section-kicker">NORTHEAST INDIA · NETWORK VIEW</span><h2>{plan ? `${plan.origin.name.split(',')[0]} to ${plan.destination.name.split(',')[0]}` : 'Regional road intelligence'}</h2></div><span className={`map-status ${plan?.offline_demo ? 'demo' : ''}`}><i/>{plan?.offline_demo ? 'Historical snapshot' : plan ? `Routing fetched ${formatTime(plan.routing_fetched_at)}` : 'Map ready'}</span></div><div className="map-wrap"><DashboardMap plan={plan} incidents={incidents} selectedRoute={selectedRoute} selectedIncident={activeIncident} onSelectIncident={setSelectedIncidentId} showEvidence={showEvidence}/>{!plan && <div className="map-empty"><span className="map-empty-icon"><Icon name="route" size={22}/></span><b>Your route will appear here</b><span>Enter locations to compare candidate driving routes.</span></div>}<div className="map-legend"><span><i className="legend-route"/> Selected route</span><span><i className="legend-candidate"/> Other candidates</span><span><i className="legend-incident"/> Geolocated evidence</span></div></div><div className="map-foot"><span><Icon name="pin" size={14}/>{plan ? `${plan.origin.name.split(',')[0]} → ${plan.destination.name.split(',')[0]}` : 'Assam · Meghalaya · Northeast India'}</span><span>Map tiles © OpenStreetMap contributors</span></div></article>

            <section className="route-results"><div className="results-heading"><div><span className="section-kicker">ROUTE COMPARISON</span><h2>{plan ? `${plan.routes.length} candidate route${plan.routes.length === 1 ? '' : 's'}` : 'Compare your options'}</h2></div>{plan && <span className="results-provider">{plan.offline_demo ? 'Saved demo' : 'OSRM estimates'}</span>}</div>
              {plan?.routes?.length ? <div className="route-card-list">{plan.routes.map((route, index) => <button className={`route-card ${selectedRoute === route.id ? 'selected' : ''}`} key={route.id} onClick={() => setSelectedRoute(route.id)} aria-pressed={selectedRoute === route.id}><span className="route-radio"/><span className="route-main"><b>Route {index + 1} · {index === 0 ? 'Top estimate' : 'Alternative'}</b><small>{exposureSummary(route.exposure)} · vehicle fit unknown</small><span className="route-facts"><span><Icon name="clock" size={14}/>{formatDuration(route.duration_s)}</span><span><Icon name="route" size={14}/>{formatDistance(route.distance_m)}</span><span><Icon name="layers" size={14}/>{route.highways && Object.keys(route.highways).length ? `via ${Object.keys(route.highways).join(' · ')}` : plan.offline_demo ? 'Historical' : 'OSRM'}</span></span></span><span className={`risk-pill ${adviceFor(route.recommendation || plan.recommendation).tone}`}>{adviceFor(route.recommendation || plan.recommendation).pill}</span></button>)}</div> : <div className="route-empty"><div className="route-empty-icon"><Icon name="route" size={19}/></div><div><b>No route comparison yet</b><span>Plan a route to fetch provider distance and time estimates.</span></div></div>}
              {plan && <div className={`action-banner ${advice.tone}`} role="status"><span className="action-symbol">!</span><div><b>{advice.label}{chosenRoute ? ` · Route ${chosenRoute.priority_rank}` : ''}</b>{adviceReasons.map((reason) => <span key={reason}>{reason}</span>)}</div><small>DISPATCH GUIDANCE</small></div>}
            </section>
          </div>

          <aside className="right-column" id="evidence">
            <article className="panel incident-panel"><div className="incident-panel-heading"><div><span className="section-kicker">ROAD DISRUPTION MONITOR</span><h2>Evidence desk <span className="evidence-count">{visibleIncidents.length}</span></h2></div><button className="icon-button" onClick={refresh} disabled={refreshing} aria-label="Refresh evidence and API status"><Icon name="refresh" size={17}/></button></div>
              {collectionMessage && <div className="collection-message" role="status">{collectionMessage}</div>}
              {activeIncident ? <><div className="selected-incident"><div className="incident-top"><span className={`verification-badge ${activeIncident.verification}`}>{activeIncident.verification}</span><span className={`freshness-badge ${activeIncident.freshness}`}>{freshnessLabel(activeIncident.freshness)}</span>{activeIncident.conflict_ids?.length > 0 && <span className="hint-badge conflict">Possible conflict</span>}{activeIncident.duplicate_ids?.length > 0 && <span className="hint-badge">Possible duplicate</span>}</div><h3>{activeIncident.title}</h3><div className="incident-meta"><span><Icon name="pin" size={15}/>{activeIncident.location_text || 'Location unknown'}</span><span><Icon name="clock" size={15}/>{formatPublished(activeIncident)}</span></div><p className="incident-summary">{activeIncident.summary || 'No source summary provided.'}</p><ReportHints incident={activeIncident} incidents={incidents} onSelect={(id) => { setSearch(''); setSelectedIncidentId(id) }}/><div className="source-link"><span className="source-avatar">{activeIncident.source_name.slice(0, 1).toUpperCase()}</span><span><b>{activeIncident.source_name}</b><small>Collected {formatTime(activeIncident.collected_at)}</small></span><a href={activeIncident.source_url} target="_blank" rel="noreferrer" aria-label={`Open source: ${activeIncident.source_name}`}><Icon name="arrow" size={16}/></a></div><div className="safety-callout"><span>!</span><p>The report is evidence to review. Current road status and impact are not confirmed.</p></div>
                <details className="verified-location"><summary>Add reviewer-confirmed map location</summary><input aria-label={`Location name for ${activeIncident.title}`} placeholder="Location from source" value={reviewLocations[activeIncident.id]?.name ?? (activeIncident.location_text || '')} onChange={(event) => setReviewLocations((locations) => ({ ...locations, [activeIncident.id]: { ...locations[activeIncident.id], name: event.target.value } }))}/><div><input aria-label={`Latitude for ${activeIncident.title}`} type="number" min="-90" max="90" step="any" placeholder="Latitude" value={reviewLocations[activeIncident.id]?.latitude ?? (activeIncident.latitude ?? '')} onChange={(event) => setReviewLocations((locations) => ({ ...locations, [activeIncident.id]: { ...locations[activeIncident.id], latitude: event.target.value } }))}/><input aria-label={`Longitude for ${activeIncident.title}`} type="number" min="-180" max="180" step="any" placeholder="Longitude" value={reviewLocations[activeIncident.id]?.longitude ?? (activeIncident.longitude ?? '')} onChange={(event) => setReviewLocations((locations) => ({ ...locations, [activeIncident.id]: { ...locations[activeIncident.id], longitude: event.target.value } }))}/></div><small>Only enter coordinates you checked in the linked source. Empty both fields and save to remove a wrong location.</small></details>
                <div className="review-controls"><label className="sr-only" htmlFor={`review-status-${activeIncident.id}`}>Review status</label><select id={`review-status-${activeIncident.id}`} value={reviewStatuses[activeIncident.id] || activeIncident.verification} onChange={(event) => setReviewStatuses((statuses) => ({ ...statuses, [activeIncident.id]: event.target.value }))}><option value="unverified">Unverified</option><option value="confirmed">Confirmed</option><option value="conflicting">Conflicting</option><option value="unknown">Unknown</option><option value="dismissed">Dismissed (not relevant)</option></select><label className="sr-only" htmlFor={`review-note-${activeIncident.id}`}>Review note</label><input id={`review-note-${activeIncident.id}`} placeholder="Review note (required)" value={reviewNotes[activeIncident.id] || ''} onChange={(event) => setReviewNotes((notes) => ({ ...notes, [activeIncident.id]: event.target.value }))}/><button disabled={reviewBusyId === activeIncident.id || (reviewNotes[activeIncident.id] || '').trim().length < 3} onClick={() => reviewIncident(activeIncident)}>{reviewBusyId === activeIncident.id ? 'Saving…' : 'Save review'}</button></div>
                {activeIncident.review_note && <div className="review-history"><b>Last review · {formatTime(activeIncident.reviewed_at)}</b><span>{activeIncident.review_note}</span></div>}
                </div></> : <div className="evidence-empty"><span className="empty-illustration"><Icon name="layers" size={24}/></span><b>{incidents.length ? 'No matching evidence' : 'No evidence collected yet'}</b><p>{incidents.length ? 'Try another search term.' : 'No reports does not mean a road is clear.'}</p></div>}
            </article>

            <article className="panel evidence-list-panel"><div className="list-heading"><div><span className="section-kicker">SOURCE REPORTS</span><h2>Collected evidence</h2></div><button className="text-button" onClick={collect} disabled={collectionLoading || apiStatus !== 'online'}>{collectionLoading ? 'Searching…' : 'Run collection'} <Icon name="arrow" size={14}/></button></div><div className="evidence-list">{visibleIncidents.length ? visibleIncidents.map((incident) => <button className={`evidence-row ${activeIncident?.id === incident.id ? 'active' : ''}`} key={incident.id} onClick={() => setSelectedIncidentId(incident.id)}><span className={`mini-status ${incident.verification}`}/><span className="evidence-row-copy"><b>{incident.title}</b><small>{incident.source_name} · {formatPublished(incident)}{incident.conflict_ids?.length > 0 ? ' · possible conflict' : ''}</small></span><Icon name="arrow" size={14}/></button>) : <p className="list-empty">Reports from TinyFish appear here as unverified evidence candidates.</p>}</div></article>
            <div className="source-footnote"><Icon name="check" size={15}/><span>Evidence is unverified until independently reviewed. Dispatch advice remains cautious.</span></div>
          </aside>
        </section>
        <footer className="page-footer"><span>INDIA-TRACE <i>·</i> Team Tech Titans</span><span>{chosenRoute ? `Selected estimate · ${formatDistance(chosenRoute.distance_m)} · ${formatDuration(chosenRoute.duration_s)}` : 'Road intelligence for essential deliveries'}</span></footer>
      </div>
    </main>
  </div>
}

export default App
