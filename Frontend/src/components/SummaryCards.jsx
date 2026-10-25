import Icon from './Icon.jsx'
import ReportSymbol from './ReportSymbol.jsx'
import { INACTIVE_STATES, placeName } from '../lib/format.js'
import { routeMatches } from '../lib/routeReports.js'

// The kinds of report a dispatcher scans for first are always listed, with zero when there are none; the rest
// appear when the route has some. Labels and symbols match the map.
const ALWAYS = ['closure', 'landslide', 'flood']
const TYPES = [['closure', 'Closures'], ['landslide', 'Landslides'], ['flood', 'Flooding'], ['accident', 'Accidents'],
  ['bridge', 'Bridge damage'], ['construction', 'Roadworks'], ['weather', 'Heavy rain']]

const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`
const isConfirmed = (item) => item.verification === 'confirmed' && item.evidence_status !== 'stale'

// What the route's reports add up to, in one line. No reports is never called a clear road.
function verdict(total, confirmed, unverified) {
  if (!total) return ['none', 'No reports found', 'Not proof the road is clear']
  if (confirmed) return ['confirmed', plural(confirmed, 'confirmed report'), 'Checked by a reviewer']
  if (unverified) return ['unverified', 'None confirmed', `${unverified} to verify before dispatch`]
  return ['stale', 'Only stale reports', 'Their sources are out of date']
}

// A bar split into parts in proportion, with a key: how much of the route's evidence is solid.
function Split({ label, parts, total }) {
  return <div className="brief-split">
    <span className="brief-label">{label}</span>
    <span className="split-bar" role="img" aria-label={parts.map(([, text, count]) => `${count} ${text}`).join(', ')}>
      {total ? parts.filter(([, , count]) => count).map(([tone, text, count]) => <i key={text} className={tone} style={{ flexGrow: count }} title={`${count} ${text}`}/>) : <i className="none"/>}
    </span>
    <span className="split-key">{parts.map(([tone, text, count]) => <span key={text} className={count ? '' : 'zero'}><i className={tone}/>{count} {text}</span>)}</span>
  </div>
}

// The briefing for the selected route's reports, refreshed by the live route check. It waits for a route:
// the region's totals say nothing about a particular journey.
export default function SummaryCards({ incidents, plan, route, liveCheck }) {
  const ids = routeMatches(route) // reviewer-located nearby, placed at a town on it, or naming its highways
  if (ids == null) {
    return <section className="summary briefing waiting" aria-label="Route briefing">
      <header className="summary-scope">
        <span className="brief-empty-icon"><Icon name="route" size={18}/></span>
        <b>{plan ? 'Saved route' : 'No route planned yet'}</b>
        <span>{plan ? 'This saved route has no live report matching; plan it again when online' : 'Plan a route to see the reports along it'}</span>
        {liveCheck && <span className={`live-check ${liveCheck.state}`}><i/>{liveCheck.text}</span>}
      </header>
    </section>
  }

  const reports = incidents.filter((item) => !INACTIVE_STATES.includes(item.verification) && ids.has(item.id))
  const count = (test) => reports.filter(test).length
  const sources = new Set(reports.map((item) => item.source_name)).size
  const recent = count((item) => item.freshness === 'fresh')
  const types = TYPES.map(([type, label]) => {
    const ofType = reports.filter((item) => item.event_types?.includes(type))
    return { type, label, total: ofType.length, confirmed: ofType.filter(isConfirmed).length,
      recent: ofType.filter((item) => item.freshness === 'fresh').length }
  }).filter((row) => ALWAYS.includes(row.type) || row.total)
  const confirmed = count(isConfirmed)
  const unverified = count((item) => item.verification !== 'confirmed' && item.evidence_status !== 'stale')
  const evidence = [['confirmed', 'confirmed', confirmed], ['unverified', 'unverified', unverified],
    ['stale', 'stale', count((item) => item.evidence_status === 'stale')]]
  const location = [['exact', 'exact spot', count((item) => item.latitude != null)],
    ['town', 'at a town', count((item) => item.latitude == null && item.approximate_location)],
    ['road', 'road only', count((item) => item.latitude == null && !item.approximate_location)]]
  const [tone, headline, detail] = verdict(reports.length, confirmed, unverified)

  return <section className="summary briefing" aria-label="Route briefing">
    <header className="summary-scope">
      <b><span className="brief-route">Route {route.priority_rank}</span>{placeName(plan.origin)} → {placeName(plan.destination)}</b>
      <span>Reports near this route, placed at a town on it, or naming its highways</span>
      {liveCheck && <span className={`live-check ${liveCheck.state}`}><i/>{liveCheck.text}</span>}
    </header>
    <div className="brief-body">
      <div className="brief-total">
        <div className="brief-count"><b>{reports.length}</b>
          <span>{reports.length === 1 ? 'report' : 'reports'} for this route<small>{plural(sources, 'source')} · {recent} recent</small></span></div>
        <p className={`brief-verdict ${tone}`}><i/><span>{headline}<small>{detail}</small></span></p>
        <div className="brief-quality">
          <Split label="Evidence" parts={evidence} total={reports.length}/>
          <Split label="Location" parts={location} total={reports.length}/>
        </div>
      </div>
      <ul className="brief-types" aria-label="Reports by type">
        {types.map((row) => <li key={row.type} className={`brief-type ${row.type}${row.total ? '' : ' zero'}${row.confirmed ? ' has-confirmed' : ''}`}>
          <ReportSymbol type={row.type} size={32}/>
          <span><b>{row.total}</b><span>{row.label}</span><small>{!row.total ? 'None reported' : [row.confirmed && `${row.confirmed} confirmed`, row.recent && `${row.recent} recent`].filter(Boolean).join(' · ') || 'None confirmed'}</small></span>
        </li>)}
      </ul>
    </div>
  </section>
}
