import { useMemo, useState } from 'react'
import Icon from './Icon.jsx'
import { EVENT_LABELS, LIFECYCLE_LABELS, PILOT_ROADS, SOURCE_LABELS, STATUS_LABELS, TIME_WINDOWS, formatPublished, formatTime, statusLabel } from '../lib/format.js'

// Collection controls, filters and the list of collected reports. Filter values live in App because the
// evidence desk and the map read the same filtered list.
// What a running collection or re-check is doing, from its run record.
function progressLabel(run) {
  if (!run) return 'Starting…'
  if (run.phase === 'searching') return `Searching ${Math.min(run.searches_done + 1, run.searches.length)} of ${run.searches.length}…`
  return run.searches.length ? `Reading pages · ${run.stored} new…` : 'Re-checking sources…'
}

export default function EvidenceList({ incidents, visibleIncidents, activeId, onSelect, filters, onFilterChange, canCollect, collecting, progress, onCollect, onRecheckDue, lastRun }) {
  const [collectWindow, setCollectWindow] = useState('30')
  const [target, setTarget] = useState({ road: '', place: '', event_type: '' })
  // Report 7: a research task names its allowed source categories. All are allowed unless narrowed here.
  const [categories, setCategories] = useState(Object.keys(SOURCE_LABELS))
  const dueCount = incidents.filter((item) => item.lifecycle === 'needs_recheck').length

  const options = useMemo(() => ({
    regions: [...new Set(incidents.flatMap((item) => item.regions || []))].sort(),
    roads: [...new Set(incidents.flatMap((item) => item.mentions?.highways || []))].sort((a, b) => a.length - b.length || a.localeCompare(b)),
    sources: [...new Set(incidents.map((item) => item.source_name))].sort(),
  }), [incidents])

  // No target runs the pilot-corridor searches; a road, place or event type runs a targeted search.
  const collect = (targeted = {}) => onCollect({
    window_days: Number(collectWindow) || null,
    source_categories: categories.length < Object.keys(SOURCE_LABELS).length ? categories : null,
    ...Object.fromEntries(Object.entries(targeted).map(([key, value]) => [key, value || null])),
  })
  const toggleCategory = (key, on) => setCategories((current) => on ? [...current, key] : current.filter((item) => item !== key))
  const filterSelect = (key, label, allLabel, entries) => <><label className="sr-only" htmlFor={`${key}-filter`}>{label}</label><select id={`${key}-filter`} value={filters[key]} onChange={(event) => onFilterChange(key, event.target.value)}><option value="all">{allLabel}</option>{entries.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></>
  const asEntries = (values) => values.map((value) => [value, value])

  return <article className="panel evidence-list-panel"><div className="list-heading"><div><span className="section-kicker">SOURCE REPORTS</span><h2>Collected evidence</h2></div><button className="text-button" onClick={() => collect()} disabled={collecting || !canCollect} title="Run the corridor searches">{collecting ? progressLabel(progress) : 'Run collection'} <Icon name="arrow" size={14}/></button></div>
    <div className="collect-controls"><label htmlFor="collect-window">Search window</label><select id="collect-window" value={collectWindow} onChange={(event) => setCollectWindow(event.target.value)}>{TIME_WINDOWS.map(([days, label]) => <option key={days} value={days}>{label}</option>)}<option value="">Any time</option></select></div>
    <fieldset className="source-choice"><legend>Sources to keep</legend>{Object.entries(SOURCE_LABELS).map(([key, label]) => <label key={key}><input type="checkbox" checked={categories.includes(key)} disabled={categories.length === 1 && categories.includes(key)} onChange={(event) => toggleCategory(key, event.target.checked)}/>{label}</label>)}</fieldset>
    <details className="targeted-search"><summary>Targeted search · road, place or event type</summary><div><label className="sr-only" htmlFor="target-road">Road</label><select id="target-road" value={target.road} onChange={(event) => setTarget((current) => ({ ...current, road: event.target.value }))}><option value="">Any road</option>{PILOT_ROADS.map((road) => <option key={road} value={road}>{road}</option>)}</select><label className="sr-only" htmlFor="target-place">Place or district</label><input id="target-place" maxLength="60" placeholder="Place or district" value={target.place} onChange={(event) => setTarget((current) => ({ ...current, place: event.target.value }))}/><label className="sr-only" htmlFor="target-type">Event type</label><select id="target-type" value={target.event_type} onChange={(event) => setTarget((current) => ({ ...current, event_type: event.target.value }))}><option value="">Any event</option>{Object.entries(EVENT_LABELS).filter(([key]) => key !== 'other').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button type="button" disabled={collecting || !canCollect || !(target.road || target.place.trim() || target.event_type)} onClick={() => collect(target)}>Search</button></div><small>Runs TinyFish web and news search, then reads each new page with TinyFish Fetch.</small></details>
    <div className="recheck-row"><button type="button" className="text-button" onClick={onRecheckDue} disabled={collecting || !canCollect || !dueCount}><Icon name="refresh" size={14}/>Re-check due sources ({dueCount})</button><small>Reads the pages of reports past half their freshness window again.</small></div>
    {lastRun && <p className={`last-run ${lastRun.status}`}>Last collection {formatTime(lastRun.finished_at)} · {lastRun.stored} new · {lastRun.duplicates} re-seen · {lastRun.fetched} pages read{lastRun.fetch_failed ? ` (${lastRun.fetch_failed} unreadable)` : ''}{lastRun.failed_searches ? ` · ${lastRun.failed_searches} searches failed` : ''} · {(lastRun.duration_ms / 1000).toFixed(1)} s</p>}
    {filters.town !== 'all' && <div className="town-filter"><span>Placed at <b>{filters.town}</b> (approximate)</span><button type="button" onClick={() => onFilterChange('town', 'all')} aria-label={`Show reports from every town, not only ${filters.town}`}>Show all</button></div>}
    <div className="list-filters">
      {filterSelect('type', 'Event type', 'All event types', Object.entries(EVENT_LABELS))}
      {filterSelect('status', 'Evidence status', 'All statuses', Object.entries(STATUS_LABELS))}
      {filterSelect('region', 'Region', 'All regions', asEntries(options.regions))}
      {filterSelect('road', 'Road', 'All roads', asEntries(options.roads))}
      {filterSelect('time', 'Published', 'Any publish time', TIME_WINDOWS)}
      {filterSelect('category', 'Source type', 'All source types', Object.entries(SOURCE_LABELS))}
      {filterSelect('lifecycle', 'Lifecycle', 'Any lifecycle', Object.entries(LIFECYCLE_LABELS))}
      {filterSelect('source', 'Source', 'All sources', asEntries(options.sources))}
    </div>
    <div className="evidence-list">{visibleIncidents.length ? visibleIncidents.map((incident) => <button className={`evidence-row ${activeId === incident.id ? 'active' : ''}`} key={incident.id} onClick={() => onSelect(incident.id)}><span className={`mini-status ${incident.evidence_status}`} title={statusLabel(incident)}/><span className="evidence-row-copy"><b>{incident.title}</b><small>{incident.source_name} · {formatPublished(incident)}{incident.conflict_ids?.length > 0 ? ' · possible conflict' : ''}{incident.lifecycle === 'needs_recheck' ? ' · needs re-check' : ''}{incident.media ? (incident.media.kind === 'image' ? ' · photo' : incident.media.kind === 'youtube' ? ' · video' : ` · ${incident.media.site} post`) : ''}</small></span><Icon name="arrow" size={14}/></button>) : <p className="list-empty">Reports from TinyFish appear here as unverified evidence candidates.</p>}</div>
  </article>
}
