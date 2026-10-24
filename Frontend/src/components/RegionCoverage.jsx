import { formatTime } from '../lib/format.js'

// Reports per state in the active region (report 5 and 11). A state without recent reports is a gap
// in coverage, never a sign that its roads are clear.
export default function RegionCoverage({ region }) {
  if (!region) return null
  return <article className="panel region-panel"><div className="panel-heading compact"><div><span className="section-kicker">REGION · {region.name.toUpperCase()}</span><h2>Coverage by state</h2></div></div>
    <p className="region-corridor">Pilot corridor: {region.corridor}</p>
    <ul className="coverage-list">{region.coverage.map((row) => <li key={row.state} className={row.fresh ? '' : 'gap'}>
      <b>{row.state}</b>
      <span>{row.reports} report{row.reports === 1 ? '' : 's'} · {row.fresh ? `${row.fresh} recent` : 'none recent'}</span>
      <small>{row.newest_published ? `Newest ${formatTime(row.newest_published)}` : 'No dated reports'}</small>
    </li>)}</ul>
    <p className="map-hint">{region.coverage_note}</p>
  </article>
}
