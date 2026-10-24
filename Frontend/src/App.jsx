import { useMemo, useRef, useState } from 'react'
import './App.css'
import Icon from './components/Icon.jsx'
import RoutePlanner from './components/RoutePlanner.jsx'
import RouteMap, { MapLayers } from './components/RouteMap.jsx'
import RouteComparison from './components/RouteComparison.jsx'
import EvidenceDesk from './components/EvidenceDesk.jsx'
import EvidenceList from './components/EvidenceList.jsx'
import Monitoring from './components/Monitoring.jsx'
import RegionCoverage from './components/RegionCoverage.jsx'
import SummaryCards from './components/SummaryCards.jsx'
import { useWorkspace } from './hooks/useWorkspace.js'
import { useEvidenceFilters } from './hooks/useEvidenceFilters.js'
import { useSidebar } from './hooks/useSidebar.js'
import { useHere } from './hooks/useHere.js'
import { INACTIVE_STATES, formatDistance, formatDuration, formatTime, placeName } from './lib/format.js'
import { inIndia } from './lib/mapStyle.js'
import { metres } from './lib/navigation.js'
import { routeMatches } from './lib/routeReports.js'
import * as api from './services/api.js'

// Degraded: the API answered but could not serve data, usually because its database failed.
const API_STATUS = {
  checking: ['Connecting…', 'Checking the API'],
  online: ['API connected', 'Local intelligence service'],
  degraded: ['API error', 'Running, but data is unavailable'],
  offline: ['API unavailable', 'Start backend on port 8000'],
}

const START_WITHIN_M = 1000 // this close to the route's first point, Start guides live; further away it previews

function App() {
  const { incidents, apiStatus, problem, lastRun, region, metrics, mapConfig, schedule, updatedAt, arrivals, refresh: refreshWorkspace } = useWorkspace()
  const [statusLabel, statusNote] = API_STATUS[apiStatus]
  // Live: the dashboard reloads every minute; the API collects on its own schedule when one is set.
  const clock = (value) => new Intl.DateTimeFormat('en-IN', { timeStyle: 'short' }).format(new Date(value))
  const liveLabel = apiStatus === 'online' && updatedAt ? `Live · updated ${clock(updatedAt)}` : statusLabel
  const scheduleNote = !schedule?.collection_interval_minutes ? 'Automatic collection is off'
    : `Collects every ${schedule.collection_interval_minutes} min${schedule.next_collection_at ? ` · next ${clock(schedule.next_collection_at)}` : ''}`
  const arrivalNote = arrivals ? `${arrivals.count} new report${arrivals.count === 1 ? '' : 's'} arrived at ${clock(arrivals.at)}.` : ''
  const sidebar = useSidebar()
  const { here, problem: hereProblem, retry: retryHere } = useHere()
  const [search, setSearch] = useState('')
  const { filters, setFilter, visibleIncidents } = useEvidenceFilters(incidents, search)
  const [plan, setPlan] = useState(null)
  const [searched, setSearched] = useState(null) // a destination from the map's search bar
  const [searchNote, setSearchNote] = useState('')
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [selectedIncidentId, setSelectedIncidentId] = useState(null)
  const [evidenceScope, setEvidenceScope] = useState('route') // with a route planned: 'route' (its reports) or 'all'
  const [hiddenTypes, setHiddenTypes] = useState([])
  const [routeLoading, setRouteLoading] = useState(false)
  const [routeError, setRouteError] = useState('')
  const [collectionLoading, setCollectionLoading] = useState(false)
  const [runProgress, setRunProgress] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [message, setMessage] = useState('')
  const [liveCheck, setLiveCheck] = useState(null)
  const [navigating, setNavigating] = useState(null) // 'live' (following the route) or 'preview' (stepping through it)
  const planToken = useRef(0)
  const lastRequest = useRef(null)

  // A new route shows its own reports in the evidence desk, most relevant first.
  const showPlan = (payload) => {
    setPlan(payload)
    setSelectedRoute(payload.routes[0]?.id || null)
    setSelectedIncidentId(null)
    setEvidenceScope('route')
  }

  // A live check for the planned route: a TinyFish search of the last 3 days for its main highway and its two
  // towns. When it finishes, the route is planned again so its reports, cards and advice include what was found.
  const LIVE_CHECK_DAYS = 3
  const checkRouteLive = async (request, payload, token) => {
    const main = Object.entries(payload.routes[0]?.highways || {}).sort((a, b) => b[1] - a[1])[0]?.[0]
    // Towns as the route plan names them; a device position ("Your location") is not a searchable place.
    const towns = [payload.origin, payload.destination].filter((stop) => stop.query !== 'Your location')
      .map((stop) => placeName(stop)).join(' ').replace(/[^A-Za-z .'-]/g, '').trim().slice(0, 60)
    setLiveCheck({ state: 'running', text: `Checking live reports for this route (last ${LIVE_CHECK_DAYS} days)…` })
    try {
      const job = await api.startCollection({ road: main || null, place: towns || null, window_days: LIVE_CHECK_DAYS })
      if (job.status !== 'running') {
        if (token === planToken.current) setLiveCheck({ state: 'skipped', text: job.message })
        return
      }
      const run = await api.followRun(job.run_id, () => {})
      await refreshWorkspace()
      const updated = await api.planRoute(request)
      if (token !== planToken.current) return // another route was planned meanwhile
      setPlan(updated)
      setSelectedRoute((current) => updated.routes.some((item) => item.id === current) ? current : updated.routes[0]?.id || null)
      const time = new Intl.DateTimeFormat('en-IN', { timeStyle: 'short' }).format(new Date())
      setLiveCheck({ state: 'done', text: run.stored
        ? `Live check ${time}: ${run.stored} new report${run.stored === 1 ? '' : 's'} from the route search`
        : `Live check ${time}: no new reports in the last ${LIVE_CHECK_DAYS} days. No reports does not mean the road is clear.` })
    } catch (error) {
      if (token === planToken.current) setLiveCheck({ state: 'skipped', text: `Live check not run: ${error.message}` })
    }
  }

  // keepNavigating: a re-route while following a route; planning any other route ends navigation.
  const planRoute = async (request, { keepNavigating = false } = {}) => {
    const token = ++planToken.current
    lastRequest.current = request
    if (!keepNavigating) setNavigating(null)
    setRouteLoading(true)
    setRouteError('')
    setPlan(null)
    setSelectedRoute(null)
    setLiveCheck(null)
    try {
      const payload = await api.planRoute(request)
      showPlan(payload)
      checkRouteLive(request, payload, token)
    } catch (error) {
      if (api.hasOfflineRoute(request)) {
        try {
          const snapshot = await api.loadOfflineRoute()
          showPlan(snapshot)
          setRouteError(`Live services unavailable. Showing a saved OSRM snapshot from ${formatTime(snapshot.captured_at)}. This historical route is not for dispatch.`)
          return
        } catch { /* Keep the original service error if the saved demo asset is unavailable. */ }
      }
      setRouteError(error.message || 'Route planning failed. Check the API and routing connection.')
    } finally { setRouteLoading(false) }
  }

  // Collections and re-checks run in the background on the API; the dashboard follows the run until it ends.
  const runJob = async (start) => {
    setCollectionLoading(true)
    setRunProgress(null)
    setMessage('')
    try {
      const job = await start()
      if (job.status !== 'running') {
        setMessage(job.message)
        return
      }
      const run = await api.followRun(job.run_id, setRunProgress)
      setMessage(run.message || `The run ended with status ${run.status}.`)
      await refreshWorkspace()
    } catch (error) { setMessage(error.message || 'The run failed.') }
    finally {
      setCollectionLoading(false)
      setRunProgress(null)
    }
  }
  const collect = (options) => runJob(() => api.startCollection(options))
  const recheckDue = () => runJob(() => api.startRecheck())

  const recheckIncident = async (incident) => {
    try {
      const updated = await api.recheckIncident(incident.id)
      setMessage(updated.timeline[0]?.text || 'Source re-checked.')
      await refreshWorkspace()
    } catch (error) { setMessage(error.message) }
  }

  const refresh = async () => {
    setRefreshing(true)
    setMessage('')
    try {
      await refreshWorkspace()
      setMessage('Evidence and service status are up to date.')
    } catch (error) { setMessage(error.message) }
    finally { setRefreshing(false) }
  }

  // Shared by review and flag: report the outcome in the evidence desk and reload on success.
  const save = async (send, done) => {
    try {
      await send()
      setMessage(done)
      await refreshWorkspace()
      return true
    } catch (error) {
      setMessage(error.message)
      return false
    }
  }
  const reviewIncident = (incident, review) => save(() => api.reviewIncident(incident.id, review), 'Evidence review saved.')
  const flagIncident = (incident, flag) => save(() => api.flagIncident(incident.id, flag), 'Flag sent for review. It does not change the report’s status.')

  const selectIncident = (id) => { setSearch(''); setSelectedIncidentId(id) }
  const toggleLayer = (key, shown) => setHiddenTypes((types) => shown ? types.filter((type) => type !== key) : [...types, key])

  const relevantIncidents = incidents.filter((item) => !INACTIVE_STATES.includes(item.verification))
  const chosenRoute = plan?.routes?.find((item) => item.id === selectedRoute)
  // With a route planned the desk and list show its reports (in relevance order) unless 'All reports' is chosen.
  // A report picked on the map is shown even when it is not one of them.
  const matches = useMemo(() => routeMatches(chosenRoute), [chosenRoute])
  const routeIncidents = useMemo(() => {
    if (!matches) return []
    const byId = new Map(visibleIncidents.map((item) => [item.id, item]))
    return [...matches.keys()].map((id) => byId.get(id)).filter(Boolean)
  }, [matches, visibleIncidents])
  const shownIncidents = matches && evidenceScope === 'route' ? routeIncidents : visibleIncidents
  const activeIncident = shownIncidents.find((item) => item.id === selectedIncidentId)
    || visibleIncidents.find((item) => item.id === selectedIncidentId) || shownIncidents[0] || null
  const evidenceScopes = matches ? { current: evidenceScope, onChange: setEvidenceScope, route: routeIncidents.length, all: visibleIncidents.length } : null
  // Like a maps app: live guidance (Start) when the device is at the start of the route, whether that is Your
  // location or a typed place; from anywhere else the route can be stepped through turn by turn (Preview).
  const routeStart = chosenRoute?.geometry?.coordinates?.[0]
  const atStart = inIndia(here) && routeStart && metres([here.longitude, here.latitude], routeStart) <= START_WITHIN_M
  const startMode = atStart ? 'live' : 'preview'
  const startNote = !plan ? '' : plan.offline_demo ? 'A saved snapshot cannot be followed.'
    : !chosenRoute?.steps?.length ? 'The routing service sent no turn-by-turn steps for this route.'
      : startMode === 'preview' ? `Preview steps through the turns. Live guidance starts when you are at ${placeName(plan.origin)}.` : ''
  const start = plan && chosenRoute?.steps?.length && !plan.offline_demo ? () => setNavigating(startMode) : null
  const reroute = () => {
    if (!inIndia(here) || !lastRequest.current) return
    planRoute({ ...lastRequest.current, origin: `${here.latitude.toFixed(5)}, ${here.longitude.toFixed(5)}` }, { keepNavigating: true })
  }
  const navigation = navigating ? { mode: navigating, route: chosenRoute, destination: plan?.destination, rerouting: routeLoading, error: routeError,
    onExit: () => setNavigating(null), onReroute: reroute } : null

  return <div className={`app-shell${sidebar.hidden ? ' sidebar-hidden' : ''}`}>
    <aside className="sidebar" id="sidebar" inert={sidebar.hidden}>
      <a className="brand" href="#overview" aria-label="INDIA-TRACE home"><span className="brand-mark"><span /><span /><span /></span><span className="brand-copy"><b>INDIA-TRACE</b><small>Essential deliveries · Northeast India</small></span></a>
      <nav className="side-nav" aria-label="Main navigation">
        <a className="nav-item active" href="#overview"><Icon name="home"/> <span>Overview</span></a>
        <a className="nav-item" href="#route-planning"><Icon name="route"/> <span>Plan route</span></a>
        <a className="nav-item" href="#evidence"><Icon name="alert"/> <span>Live evidence</span>{incidents.length > 0 && <span className="nav-count">{incidents.length}</span>}</a>
        <a className="nav-item" href="#map-section"><Icon name="layers"/> <span>Map view</span></a>
        <a className="nav-item" href="#monitoring"><Icon name="clock"/> <span>Monitoring</span></a>
      </nav>
      <div className="sidebar-bottom">
        <div className="offline-card"><span className={`status-dot ${apiStatus}`} /><span><b>{statusLabel}</b><small>{apiStatus === 'online' ? scheduleNote : statusNote}</small></span></div>
        <div className="sidebar-note"><span className="sidebar-landscape" aria-hidden="true">⌁</span><p>Road intelligence for essential deliveries across Northeast India.</p></div>
        <div className="team-card"><div className="team-avatar">TT</div><div><b>Team Tech Titans</b><small>INDIA-TRACE workspace</small></div></div>
      </div>
    </aside>

    <main className="main-area" id="overview">
      <header className="topbar"><button type="button" className="sidebar-toggle" onClick={sidebar.toggle} aria-controls="sidebar" aria-expanded={!sidebar.hidden} aria-label={sidebar.hidden ? 'Show sidebar' : 'Hide sidebar'} title={sidebar.hidden ? 'Show sidebar' : 'Hide sidebar'}><Icon name="sidebar" size={20}/></button><div className="topbar-brand"><span className="brand-mark small"><span /><span /><span /></span><span><b>INDIA-TRACE</b><small>Road risk dashboard</small></span></div><label className="global-search"><Icon name="search" size={19}/><input aria-label="Search evidence" placeholder="Search locations, roads, sources or reports…" value={search} onChange={(event) => setSearch(event.target.value)}/></label><div className="top-actions"><span className={`connection-label ${apiStatus}`} title={scheduleNote}><i/>{liveLabel}</span><div className="profile-avatar">TT</div><span className="profile-name">Tech Titans</span></div></header>

      <div className="page-content">
        <SummaryCards incidents={incidents} plan={plan} route={chosenRoute} liveCheck={liveCheck}/>

        <section className="workspace-grid">
          <div className="left-column">
            <RoutePlanner loading={routeLoading} error={routeError} isSnapshot={Boolean(plan?.offline_demo)} onPlan={planRoute} searched={searched} hasPlan={Boolean(plan)} onStart={start} startMode={startMode} startNote={startNote} onSearchWithoutStart={() => setSearchNote('Destination set. Choose a starting point in the route planner.')}/>
            <MapLayers plan={plan} incidents={relevantIncidents} hiddenTypes={hiddenTypes} onToggle={toggleLayer}/>
            <RegionCoverage region={region}/>
          </div>

          <div className="center-column" id="map-section">
            <RouteMap plan={plan} mapConfig={mapConfig} here={here} hereProblem={hereProblem} onRetryHere={retryHere} onStart={start} startMode={startMode} navigation={navigation} onSearch={(place) => { setSearchNote(''); setSearched({ ...place, at: Date.now() }) }}
              searchStatus={!searched ? null : searchNote ? { tone: 'note', text: searchNote } : routeLoading ? { tone: 'busy', text: 'Finding routes…' } : routeError ? { tone: plan?.offline_demo ? 'note' : 'error', text: routeError } : null} incidents={incidents} selectedRoute={selectedRoute} selectedIncident={activeIncident} onSelectIncident={selectIncident} hiddenTypes={hiddenTypes}/>
            <RouteComparison plan={plan} selectedRoute={selectedRoute} onSelectRoute={setSelectedRoute} onSelectIncident={selectIncident}/>
          </div>

          <aside className="right-column" id="evidence">
            <EvidenceDesk incident={activeIncident} incidents={incidents} visibleCount={shownIncidents.length} scopes={evidenceScopes} matchReason={matches ? matches.get(activeIncident?.id) || null : undefined} message={message || problem || arrivalNote} refreshing={refreshing} onRefresh={refresh} onSelect={selectIncident} onReview={reviewIncident} onFlag={flagIncident} canRecheck={apiStatus === 'online' && !collectionLoading} onRecheck={recheckIncident}/>
            <EvidenceList incidents={incidents} visibleIncidents={shownIncidents} activeId={activeIncident?.id} onSelect={setSelectedIncidentId} filters={filters} onFilterChange={setFilter} canCollect={apiStatus === 'online'} collecting={collectionLoading} progress={runProgress} onCollect={collect} onRecheckDue={recheckDue} lastRun={lastRun}/>
            <div className="source-footnote"><Icon name="check" size={15}/><span>Evidence is unverified until independently reviewed. Dispatch advice remains cautious.</span></div>
          </aside>
        </section>
        <Monitoring metrics={metrics}/>
        <footer className="page-footer"><span>INDIA-TRACE <i>·</i> Team Tech Titans</span><span>{chosenRoute ? `Selected estimate · ${formatDistance(chosenRoute.distance_m)} · ${formatDuration(chosenRoute.duration_s)}` : 'Road intelligence for essential deliveries'}</span></footer>
      </div>
    </main>
  </div>
}

export default App
