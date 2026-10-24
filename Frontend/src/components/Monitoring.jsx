import { formatShare, formatTime } from '../lib/format.js'

function Figure({ label, value, note }) {
  return <div className="figure"><span>{label}</span><b className={value === 'not measured' ? 'unmeasured' : undefined}>{value}</b>{note && <small>{note}</small>}</div>
}

const hours = (value) => value == null ? 'not measured' : value >= 48 ? `${Math.round(value / 24)} days` : `${value} h`
const seconds = (value) => value == null ? 'not measured' : `${value} s`

// Monitoring and evaluation (report 8, 11 and 13), from the API's logs and stored reports.
// Figures without data say "not measured"; rates show how many records they come from.
export default function Monitoring({ metrics }) {
  if (!metrics) return null
  const { evidence, collection, providers_today: providers, routing } = metrics
  const search = providers.tinyfish_search
  const fetch = providers.tinyfish_fetch
  return <section className="panel monitoring" id="monitoring" aria-labelledby="monitoring-title">
    <div className="panel-heading"><div><span className="section-kicker">MONITORING AND EVALUATION</span><h2 id="monitoring-title">How the system is doing</h2></div><small className="monitoring-time">Updated {formatTime(metrics.generated_at)}</small></div>
    <div className="figure-groups">
      <div className="figure-group"><h3>Evidence quality</h3>
        <Figure label="Stale" value={formatShare(evidence.stale_share)} note={`of ${evidence.active} active reports`}/>
        <Figure label="No source time" value={formatShare(evidence.unknown_time_share)}/>
        <Figure label="Located by a reviewer" value={formatShare(evidence.located_share)}/>
        <Figure label="In a duplicate group" value={formatShare(evidence.in_duplicate_groups_share)} note={`of ${evidence.total} reports`}/>
        <Figure label="Need a re-check" value={evidence.by_lifecycle.needs_recheck || 0}/>
      </div>
      <div className="figure-group"><h3>Evaluation</h3>
        <Figure label="Freshness lag, median" value={hours(evidence.freshness_lag_hours.median)} note={`p90 ${hours(evidence.freshness_lag_hours.p90)} · ${evidence.freshness_lag_hours.n} reports with an exact source time`}/>
        <Figure label="Kept after review" value={formatShare(evidence.reviewer_kept_share.value)} note={`${evidence.reviewer_kept_share.n} reviewed; dismissed counts as not relevant`}/>
      </div>
      <div className="figure-group"><h3>Collection, last 30 days</h3>
        <Figure label="Runs" value={collection.runs_30d} note={collection.last_finished_at ? `Last ${formatTime(collection.last_finished_at)}` : 'None yet'}/>
        <Figure label="Median run time" value={seconds(collection.median_duration_s)}/>
        <Figure label="Searches failed" value={formatShare(collection.search_failure_share)}/>
        <Figure label="Pages unreadable" value={formatShare(collection.fetch_failure_share)}/>
      </div>
      <div className="figure-group"><h3>Usage today (UTC)</h3>
        <Figure label="TinyFish searches" value={`${search.units - (search.by_outcome.cache || 0)} / ${search.free_daily_limit.toLocaleString('en-IN')}`} note="free daily allowance"/>
        <Figure label="TinyFish pages read" value={`${fetch.units} / ${fetch.free_daily_limit.toLocaleString('en-IN')}`} note="free daily allowance"/>
        <Figure label="Map and route lookups" value={['nominatim', 'osrm'].reduce((total, key) => total + (providers[key]?.calls || 0), 0)} note={`${['nominatim', 'osrm'].reduce((total, key) => total + (providers[key]?.by_outcome.cache || 0), 0)} answered from the saved copy`}/>
      </div>
      <div className="figure-group"><h3>Route planning, last 7 days</h3>
        <Figure label="Plans" value={routing.plans_7d} note={`${routing.failed_7d} failed`}/>
        <Figure label="Response time" value={seconds(routing.p50_s)} note={`median · p95 ${seconds(routing.p95_s)}`}/>
      </div>
    </div>
  </section>
}
