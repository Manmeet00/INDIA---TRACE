import { useState } from 'react'
import './App.css'
import Icon from './components/Icon.jsx'
import RoutePlanner from './components/RoutePlanner.jsx'
import RouteMap, { MapLayers } from './components/RouteMap.jsx'
import RouteComparison from './components/RouteComparison.jsx'
import EvidenceDesk from './components/EvidenceDesk.jsx'
import EvidenceList from './components/EvidenceList.jsx'
import Monitoring from './components/Monitoring.jsx'
import RegionCoverage from './components/RegionCoverage.jsx'
import { useWorkspace } from './hooks/useWorkspace.js'
import { useEvidenceFilters } from './hooks/useEvidenceFilters.js'
import { useSidebar } from './hooks/useSidebar.js'
import { INACTIVE_STATES, formatDistance, formatDuration, formatTime } from './lib/format.js'
import * as api from './services/api.js'

// Degraded: the API answered but could not serve data, usually because its database failed.
const API_STATUS = {
  checking: ['Connecting…', 'Checking the API'],
  online: ['API connected', 'Local intelligence service'],
  degraded: ['API error', 'Running, but data is unavailable'],
  offline: ['API unavailable', 'Start backend on port 8000'],
}

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
  const [search, setSearch] = useState('')
  const { filters, setFilter, visibleIncidents } = useEvidenceFilters(incidents, search)
  const [plan, setPlan] = useState(null)
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [selectedIncidentId, setSelectedIncidentId] = useState(null)
  const [hiddenTypes, setHiddenTypes] = useState([])
  const [routeLoading, setRouteLoading] = useState(false)
  const [routeError, setRouteError] = useState('')
  const [collectionLoading, setCollectionLoading] = useState(false)
  const [runProgress, setRunProgress] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [message, setMessage] = useState('')

  const showPlan = (payload) => {
    setPlan(payload)
    setSelectedRoute(payload.routes[0]?.id || null)
  }

  const planRoute = async (request) => {
    setRouteLoading(true)
    setRouteError('')
    setPlan(null)
    setSelectedRoute(null)
    try {
      showPlan(await api.planRoute(request))
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
  // A town pin lists the reports that name the town, newest first.
  const selectTown = (town) => { setSearch(''); setFilter('town', town.place); setSelectedIncidentId(town.items[0].id) }
  const toggleLayer = (key, shown) => setHiddenTypes((types) => shown ? types.filter((type) => type !== key) : [...types, key])

  const activeIncident = visibleIncidents.find((item) => item.id === selectedIncidentId) || visibleIncidents[0] || null
  const relevantIncidents = incidents.filter((item) => !INACTIVE_STATES.includes(item.verification))
  const typeSummary = (type) => {
    const matching = relevantIncidents.filter((item) => item.event_types?.includes(type))
    return `${matching.filter((item) => item.verification === 'confirmed').length} confirmed · ${matching.filter((item) => item.freshness === 'fresh').length} recent`
  }
  const typeCount = (type) => relevantIncidents.filter((item) => item.event_types?.includes(type)).length
  const unknownLocationCount = relevantIncidents.filter((item) => item.latitude == null && !item.approximate_location).length
  const sourceCount = new Set(incidents.map((item) => item.source_name)).size
  const chosenRoute = plan?.routes?.find((item) => item.id === selectedRoute)

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
        <section className="summary-grid" aria-label="Workspace summary">
          <article className="summary-card red"><span className="summary-icon"><Icon name="alert" size={20}/></span><div><b>{typeCount('closure')}</b><span>Closure reports</span><small>{typeSummary('closure')}</small></div></article>
          <article className="summary-card amber"><span className="summary-icon"><Icon name="mountain" size={20}/></span><div><b>{typeCount('landslide')}</b><span>Landslide reports</span><small>{typeSummary('landslide')}</small></div></article>
          <article className="summary-card blue"><span className="summary-icon"><Icon name="water" size={20}/></span><div><b>{typeCount('flood')}</b><span>Flood / waterlogging</span><small>{typeSummary('flood')}</small></div></article>
          <article className="summary-card violet"><span className="summary-icon"><Icon name="pin" size={20}/></span><div><b>{unknownLocationCount}</b><span>Location unresolved</span><small>Not on the map yet</small></div></article>
          <article className="summary-card green"><span className="summary-icon"><Icon name="check" size={20}/></span><div><b>{incidents.length}</b><span>Reports processed</span><small>{sourceCount} sources · {relevantIncidents.filter((item) => item.freshness === 'fresh').length} recent</small></div></article>
        </section>

        <section className="workspace-grid">
          <div className="left-column">
            <RoutePlanner loading={routeLoading} error={routeError} isSnapshot={Boolean(plan?.offline_demo)} onPlan={planRoute}/>
            <MapLayers plan={plan} incidents={relevantIncidents} hiddenTypes={hiddenTypes} onToggle={toggleLayer}/>
            <RegionCoverage region={region}/>
          </div>

          <div className="center-column" id="map-section">
            <RouteMap plan={plan} mapConfig={mapConfig} incidents={incidents} selectedRoute={selectedRoute} selectedIncident={activeIncident} onSelectIncident={selectIncident} onSelectTown={selectTown} hiddenTypes={hiddenTypes}/>
            <RouteComparison plan={plan} selectedRoute={selectedRoute} onSelectRoute={setSelectedRoute} onSelectIncident={selectIncident}/>
          </div>

          <aside className="right-column" id="evidence">
            <EvidenceDesk incident={activeIncident} incidents={incidents} visibleCount={visibleIncidents.length} message={message || problem || arrivalNote} refreshing={refreshing} onRefresh={refresh} onSelect={selectIncident} onReview={reviewIncident} onFlag={flagIncident} canRecheck={apiStatus === 'online' && !collectionLoading} onRecheck={recheckIncident}/>
            <EvidenceList incidents={incidents} visibleIncidents={visibleIncidents} activeId={activeIncident?.id} onSelect={setSelectedIncidentId} filters={filters} onFilterChange={setFilter} canCollect={apiStatus === 'online'} collecting={collectionLoading} progress={runProgress} onCollect={collect} onRecheckDue={recheckDue} lastRun={lastRun}/>
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
