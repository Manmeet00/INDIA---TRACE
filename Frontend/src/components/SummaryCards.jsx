import Icon from './Icon.jsx'
import { INACTIVE_STATES, placeName } from '../lib/format.js'

// The reports that matter for a route: reviewer-located nearby, placed at a town on it, or naming its highways.
function routeReportIds(route) {
  const exposure = route?.exposure
  if (!exposure) return null
  return new Set([...exposure.nearby_ids, ...(exposure.place_match_ids || []), ...exposure.highway_mention_ids])
}

// Headline counts. Without a planned route they cover the whole region; with one, only the selected route's reports,
// refreshed by the live route check.
export default function SummaryCards({ incidents, plan, route, liveCheck }) {
  const ids = routeReportIds(route)
  const scoped = ids != null
  const reports = incidents.filter((item) => !INACTIVE_STATES.includes(item.verification) && (!scoped || ids.has(item.id)))
  const ofType = (type) => reports.filter((item) => item.event_types?.includes(type))
  const detail = (type) => `${ofType(type).filter((item) => item.verification === 'confirmed').length} confirmed · ${ofType(type).filter((item) => item.freshness === 'fresh').length} recent`
  const unlocated = reports.filter((item) => item.latitude == null && !item.approximate_location).length
  const approximate = reports.filter((item) => item.latitude == null && item.approximate_location).length
  const sources = new Set(reports.map((item) => item.source_name)).size
  const scope = scoped ? `Route ${route.priority_rank}: ${placeName(plan.origin)} → ${placeName(plan.destination)}` : 'Across the region'

  return <section className="summary" aria-label="Report summary">
    <p className="summary-scope"><b>{scope}</b>{scoped ? <span>Reports near this route, placed at a town on it, or naming its highways</span> : <span>Plan a route to see only the reports that matter for it</span>}
      {liveCheck && <span className={`live-check ${liveCheck.state}`}><i/>{liveCheck.text}</span>}</p>
    <div className="summary-grid">
      <article className="summary-card red"><span className="summary-icon"><Icon name="alert" size={20}/></span><div><b>{ofType('closure').length}</b><span>Closure reports</span><small>{detail('closure')}</small></div></article>
      <article className="summary-card amber"><span className="summary-icon"><Icon name="mountain" size={20}/></span><div><b>{ofType('landslide').length}</b><span>Landslide reports</span><small>{detail('landslide')}</small></div></article>
      <article className="summary-card blue"><span className="summary-icon"><Icon name="water" size={20}/></span><div><b>{ofType('flood').length}</b><span>Flood / waterlogging</span><small>{detail('flood')}</small></div></article>
      <article className="summary-card violet"><span className="summary-icon"><Icon name="pin" size={20}/></span><div><b>{unlocated}</b><span>Location unresolved</span><small>{approximate} more placed at a town</small></div></article>
      <article className="summary-card green"><span className="summary-icon"><Icon name="check" size={20}/></span><div><b>{reports.length}</b><span>{scoped ? 'Reports for this route' : 'Active reports'}</span><small>{sources} sources · {reports.filter((item) => item.freshness === 'fresh').length} recent</small></div></article>
    </div>
  </section>
}
