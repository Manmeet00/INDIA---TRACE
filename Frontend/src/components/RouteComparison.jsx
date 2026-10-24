import { useState } from 'react'
import Icon from './Icon.jsx'
import Milestone from './Milestone.jsx'
import { STATUS_LABELS, adviceFor, exposureSummary, formatDistance, formatDuration } from '../lib/format.js'

// Which reports may affect the selected route and why (report 6.6), plus per-highway coverage gaps.
const IMPACT_PREVIEW = 5

function RouteImpact({ route, note, onSelect }) {
  const [expanded, setExpanded] = useState(false)
  if (!route?.impact_reports && !route?.coverage) return null
  const reports = route.impact_reports || []
  const shown = expanded ? reports : reports.slice(0, IMPACT_PREVIEW)
  return <div className="route-impact">
    <div className="impact-heading"><b>Reports that may affect Route {route.priority_rank}</b>{note && <small>{note}</small>}</div>
    {route.coverage && <div className="coverage">
      <div className="coverage-chips">{route.coverage.highways.map((row) => <Milestone key={row.highway} road={row.highway} gap={!row.fresh} detail={`${row.km} km · ${row.reports} report${row.reports === 1 ? '' : 's'}`} note={row.fresh ? `${row.fresh} recent` : 'none recent'}/>)}</div>
      <p>{route.coverage.note}</p>
    </div>}
    {reports.length
      ? shown.map((report) => <button type="button" className="impact-row" key={report.id} onClick={() => onSelect(report.id)}>
        <span className="impact-score" title="Relevance score out of 100">{report.score}</span>
        <span className="impact-copy"><b>{report.title}</b><small>{report.source_name} · {STATUS_LABELS[report.evidence_status] || report.evidence_status}</small><span className="impact-factors">{report.factors.slice(0, 2).join(' · ')}</span></span>
      </button>)
      : <p className="impact-empty">No collected report is located near this route or names one of its highways.</p>}
    {reports.length > IMPACT_PREVIEW && <button type="button" className="impact-more" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Show top 5' : `Show all ${reports.length} reports`}</button>}
  </div>
}

function RouteCard({ route, index, plan, selected, onSelect }) {
  const advice = adviceFor(route.recommendation || plan.recommendation)
  const highways = Object.entries(route.highways || {})
  return <button className={`route-card ${selected ? 'selected' : ''}`} onClick={onSelect} aria-pressed={selected}><span className="route-radio"/>
    <span className="route-main"><b>Route {index + 1} · {index === 0 ? 'Top estimate' : 'Alternative'}</b><small>{exposureSummary(route.exposure)} · vehicle fit unknown</small>
      <span className="route-facts"><span><Icon name="clock" size={14}/>{formatDuration(route.duration_s)}</span><span><Icon name="route" size={14}/>{formatDistance(route.distance_m)}</span>{!highways.length && <span><Icon name="layers" size={14}/>{plan.offline_demo ? 'Historical' : 'OSRM'}</span>}</span>
      {highways.length > 0 && <span className="route-roads">{highways.map(([road, metres]) => <Milestone key={road} road={road} detail={`${Math.round(metres / 1000)} km`}/>)}</span>}
    </span>
    <span className={`risk-pill ${advice.tone}`}>{advice.pill}</span>
  </button>
}

export default function RouteComparison({ plan, selectedRoute, onSelectRoute, onSelectIncident }) {
  const chosenRoute = plan?.routes?.find((item) => item.id === selectedRoute)
  const advice = adviceFor(chosenRoute?.recommendation || plan?.recommendation)
  const adviceReasons = chosenRoute?.recommendation_reasons || (plan ? [plan.recommendation_reason] : [])
  return <section className="route-results"><div className="results-heading"><div><span className="section-kicker">ROUTE COMPARISON</span><h2>{plan ? `${plan.routes.length} candidate route${plan.routes.length === 1 ? '' : 's'}` : 'Compare your options'}</h2></div>{plan && <span className="results-provider">{plan.offline_demo ? 'Saved demo' : 'OSRM estimates'}</span>}</div>
    {plan?.routes?.length
      ? <div className="route-card-list">{plan.routes.map((route, index) => <RouteCard key={route.id} route={route} index={index} plan={plan} selected={selectedRoute === route.id} onSelect={() => onSelectRoute(route.id)}/>)}</div>
      : <div className="route-empty"><div className="route-empty-icon"><Icon name="route" size={19}/></div><div><b>No route comparison yet</b><span>Plan a route to fetch provider distance and time estimates.</span></div></div>}
    {plan && <div className={`action-banner ${advice.tone}`} role="status"><small className="banner-eyebrow">Dispatch guidance{chosenRoute ? ` · Route ${chosenRoute.priority_rank}` : ''}</small><b className="verdict">{advice.label}</b><ul className="reasons">{adviceReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul><p className="official-note">Follow official advisories from the district administration, the state disaster management authority and the road agency (NHIDCL / PWD).</p></div>}
    {plan && <RouteImpact key={chosenRoute?.id} route={chosenRoute} note={plan.impact_note} onSelect={onSelectIncident}/>}
  </section>
}
