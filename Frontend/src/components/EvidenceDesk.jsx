import { useState } from 'react'
import Icon from './Icon.jsx'
import Milestone from './Milestone.jsx'
import ReportSymbol from './ReportSymbol.jsx'
import { EVENT_LABELS, FLAG_REASONS, LIFECYCLE_LABELS, SOURCE_LABELS, formatPublished, formatTime, freshnessLabel, locationText, statusLabel } from '../lib/format.js'

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
  const highways = incident.mentions?.highways || []
  const places = incident.mentions?.places || []
  if (!links.length && !highways.length && !places.length) return null
  return <div className="report-hints">
    {(highways.length > 0 || places.length > 0) && <div className="mention-row"><small>Mentions</small>{highways.map((road) => <Milestone key={road} road={road}/>)}{places.map((place) => <span className="mention-chip" key={place}>{place}</span>)}</div>}
    {links.length > 0 && <div className="linked-reports"><span className="desk-label">Linked reports</span>
      {links.map(([kind, label, id]) => <button type="button" key={`${kind}-${id}`} className={`report-link ${kind}`} onClick={() => onSelect(id)}><b>{label}</b><span>{byId.get(id).title}</span><Icon name="arrow" size={13}/></button>)}
      <small className="hint-note">Automatic text hints. Check the sources before acting on them.</small></div>}
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
      <dt>Run</dt><dd>{incident.collection_run_id ? incident.collection_run_id.replace('run_', '').slice(0, 8) : 'Collected before runs were recorded'}</dd>
      <dt>Last checked</dt><dd>{incident.last_checked_at ? formatTime(incident.last_checked_at) : 'Not checked yet'}</dd>
      <dt>Page</dt><dd>{fetched}</dd>
      <dt>Source type</dt><dd>{SOURCE_LABELS[incident.source_category] || incident.source_category}</dd>
      {incident.districts?.length > 0 && <><dt>District</dt><dd>{incident.districts.join(', ')}</dd></>}
      {incident.scripts?.length > 0 && <><dt>Script</dt><dd>{incident.scripts.join(', ')} (original text kept)</dd></>}
      {incident.page_author && <><dt>Author</dt><dd>{incident.page_author}</dd></>}
    </dl>
    {incident.page_description && <p className="page-description">“{incident.page_description}”</p>}
  </details>
}

// Player sizes for each site's official embed. A Facebook video gets a video-shaped frame: its player is no taller,
// and a refusal ("Unavailable") then fills the frame instead of leaving blank space under it.
const EMBED_FRAMES = { youtube: { ratio: '16 / 9' }, instagram: { height: 560 }, facebook: { height: 520 }, 'facebook-video': { ratio: '16 / 9' } }
const EMBED_NOUN = { youtube: 'video', instagram: 'post', facebook: 'post' }

// The source's own picture or video. Embeds load only when asked, so opening a report sends nothing to
// YouTube, Instagram or Facebook; a picture that fails to load (some sites block it) is simply left out.
// The page cannot see inside a site's player, so when an owner does not allow embedding (Facebook shows
// "Unavailable") the caption offers the post on the site itself, and the player can be hidden again.
function EvidenceMedia({ media, sourceUrl }) {
  const [showEmbed, setShowEmbed] = useState(false)
  const [imageFailed, setImageFailed] = useState(false)
  if (!media) return null
  if (media.kind === 'image') {
    if (imageFailed) return null
    return <figure className="evidence-media">
      <img src={media.url} alt="Picture published with this source" referrerPolicy="no-referrer" onError={() => setImageFailed(true)}/>
      <figcaption>Picture from the {media.site} page. It may be a file photo, not this exact incident.</figcaption>
    </figure>
  }
  const noun = media.format === 'video' ? 'video' : EMBED_NOUN[media.kind] || 'post'
  const frame = EMBED_FRAMES[media.format === 'video' ? `${media.kind}-video` : media.kind] || EMBED_FRAMES[media.kind] || { height: 520 }
  return <figure className={`evidence-media embed ${media.kind}`}>
    {showEmbed
      ? <iframe src={media.embed_url} title={`${media.site} ${noun} from the source`} loading="lazy" referrerPolicy="strict-origin-when-cross-origin"
          allow="encrypted-media; picture-in-picture; fullscreen" style={frame.ratio ? { aspectRatio: frame.ratio } : { height: frame.height }}/>
      : <button type="button" className="embed-load" onClick={() => setShowEmbed(true)}>
          <span className="embed-play" aria-hidden="true">{media.kind === 'youtube' || noun === 'video' ? '▶' : '◩'}</span>
          <span><b>Show the {media.site} {noun}</b><small>The source’s own {noun}, loaded from {media.site.toLowerCase()}.com</small></span>
        </button>}
    {showEmbed
      ? <figcaption className="embed-caption"><span>Shown by {media.site}. If it says Unavailable, the owner does not allow it to be shown here, or it was removed.</span>
          <span className="embed-actions">{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">Open on {media.site} <Icon name="arrow" size={13}/></a>}<button type="button" onClick={() => setShowEmbed(false)}>Hide</button></span></figcaption>
      : <figcaption>Nothing loads from {media.site} until you choose to.</figcaption>}
  </figure>
}

const TIMELINE_PREVIEW = 6
// Kinds that need the reviewer's attention are marked in the timeline.
const TIMELINE_ALERTS = ['page_changed', 'page_unreadable', 'flagged']

// Everything that happened to a report, newest first: nothing is overwritten (report 5 and 6.3).
function Timeline({ events }) {
  const [expanded, setExpanded] = useState(false)
  if (!events?.length) return null
  const shown = expanded ? events : events.slice(0, TIMELINE_PREVIEW)
  return <div className="timeline"><b>Timeline</b>
    <ol>{shown.map((event, index) => <li key={`${index}-${event.kind}`} className={TIMELINE_ALERTS.includes(event.kind) ? 'alert' : event.kind}>
      <time dateTime={event.at}>{event.approximate ? '≈ ' : ''}{formatTime(event.at)}</time><span>{event.text}</span>
    </li>)}</ol>
    {events.length > TIMELINE_PREVIEW && <button type="button" className="impact-more" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Show recent' : `Show all ${events.length} events`}</button>}
  </div>
}

// With a route planned: its reports or all of them. counts are { route, all }.
function ScopeSwitch({ scopes }) {
  return <div className="evidence-scope" role="group" aria-label="Reports to show">
    {[['route', 'This route', scopes.route], ['all', 'All reports', scopes.all]].map(([key, label, count]) =>
      <button type="button" key={key} className={scopes.current === key ? 'on' : ''} aria-pressed={scopes.current === key} onClick={() => scopes.onChange(key)}>{label}<span>{count}</span></button>)}
  </div>
}

// The selected report with its review and flag forms. Drafts are kept per report, so switching reports never loses them.
// onReview and onFlag resolve to true when the API saved the change. scopes and matchReason exist once a route is
// planned: matchReason says why the report is on that route, or is null when it is not matched to it. position
// ({ index, total, onStep }) steps through the reports shown, when the open report is one of them.
export default function EvidenceDesk({ incident, incidents, visibleCount, scopes, matchReason, position, message, refreshing, onRefresh, onSelect, onReview, onFlag, canRecheck, onRecheck }) {
  const [reviewNotes, setReviewNotes] = useState({})
  const [reviewStatuses, setReviewStatuses] = useState({})
  const [reviewLocations, setReviewLocations] = useState({})
  const [reviewBusyId, setReviewBusyId] = useState(null)
  const [flagDrafts, setFlagDrafts] = useState({})
  const [flagBusyId, setFlagBusyId] = useState(null)
  const [recheckBusyId, setRecheckBusyId] = useState(null)

  const saveReview = async () => {
    setReviewBusyId(incident.id)
    try {
      // Send only the location fields the reviewer touched: omitted fields are kept, empty ones are cleared.
      const location = reviewLocations[incident.id] || {}
      const body = { verification: reviewStatuses[incident.id] || incident.verification, review_note: reviewNotes[incident.id].trim() }
      if ('name' in location) body.location_text = location.name
      if ('latitude' in location || 'longitude' in location) {
        const latitude = location.latitude ?? incident.latitude ?? ''
        const longitude = location.longitude ?? incident.longitude ?? ''
        body.latitude = latitude === '' ? null : Number(latitude)
        body.longitude = longitude === '' ? null : Number(longitude)
      }
      if (await onReview(incident, body)) {
        setReviewNotes((notes) => ({ ...notes, [incident.id]: '' }))
        setReviewStatuses((statuses) => ({ ...statuses, [incident.id]: undefined }))  // follow the saved status from now on
        setReviewLocations((locations) => ({ ...locations, [incident.id]: {} }))
      }
    } finally { setReviewBusyId(null) }
  }

  const sendFlag = async () => {
    const draft = flagDrafts[incident.id] || {}
    setFlagBusyId(incident.id)
    try {
      if (await onFlag(incident, { reason: draft.reason || 'outdated', note: draft.note?.trim() || null })) setFlagDrafts((drafts) => ({ ...drafts, [incident.id]: {} }))
    } finally { setFlagBusyId(null) }
  }

  const recheck = async () => {
    setRecheckBusyId(incident.id)
    try { await onRecheck(incident) } finally { setRecheckBusyId(null) }
  }

  const editLocation = (field, value) => setReviewLocations((locations) => ({ ...locations, [incident.id]: { ...locations[incident.id], [field]: value } }))
  const editFlag = (field, value) => setFlagDrafts((drafts) => ({ ...drafts, [incident.id]: { ...drafts[incident.id], [field]: value } }))
  const note = incident ? reviewNotes[incident.id] || '' : ''

  const freshTone = incident?.freshness === 'fresh' ? 'fresh' : incident?.freshness === 'stale' ? 'stale' : ''
  const attention = incident ? [
    incident.lifecycle === 'needs_recheck' && ['recheck', LIFECYCLE_LABELS.needs_recheck],
    incident.open_flags?.length > 0 && ['conflict', 'Flagged'],
    incident.conflict_ids?.length > 0 && ['conflict', 'Possible conflict'],
    incident.road_report === false && ['', 'No disruption described'],
  ].filter(Boolean) : []

  return <article className="panel incident-panel">
    <div className="incident-panel-heading"><div><span className="section-kicker">ROAD DISRUPTION MONITOR</span><h2>Evidence desk {!scopes && <span className="evidence-count">{visibleCount}</span>}</h2></div><button className="icon-button" onClick={onRefresh} disabled={refreshing} aria-label="Refresh evidence and API status"><Icon name="refresh" size={17}/></button></div>
    {scopes && <ScopeSwitch scopes={scopes}/>}
    {message && <div className="collection-message" role="status">{message}</div>}
    {incident ? <div className="selected-incident">
      {position && position.total > 1 && <div className="report-stepper"><span>Report <b>{position.index + 1}</b> of {position.total}</span>
        <span><button type="button" onClick={() => position.onStep(-1)} disabled={position.index === 0} aria-label="Previous report" title="Previous report"><Icon name="chevron-left" size={18}/></button>
        <button type="button" onClick={() => position.onStep(1)} disabled={position.index >= position.total - 1} aria-label="Next report" title="Next report"><Icon name="chevron-right" size={18}/></button></span></div>}

      <header className="report-head">
        <ReportSymbol type={incident.event_type}/>
        <div>
          <span className="report-kind">{EVENT_LABELS[incident.event_type] || 'Other'}<i>·</i><span className={`source-badge ${incident.source_category}`}>{SOURCE_LABELS[incident.source_category] || 'Other web page'}</span></span>
          <h3>{incident.title}</h3>
          <div className="incident-top"><span className={`verification-badge ${incident.evidence_status}`}>{statusLabel(incident)}</span>{attention.map(([tone, label]) => <span key={label} className={`hint-badge ${tone}`} title={label === 'No disruption described' ? 'The text names no closure, landslide, flood, accident, roadworks or reopening, or the page sells a trip' : undefined}>{label}</span>)}</div>
        </div>
      </header>

      {matchReason !== undefined && <p className={`route-match${matchReason ? '' : ' off'}`}><Icon name="route" size={16}/><span><b>{matchReason ? 'Why it is on this route' : 'Not matched to this route'}</b>{matchReason || 'Opened from the map or the list of all reports.'}</span></p>}

      <section className="report-says" aria-label="What the source says">
        <blockquote className="incident-summary">{incident.summary || 'No source summary provided.'}</blockquote>
        <div className="source-link"><span className="source-avatar">{incident.source_name.slice(0, 1).toUpperCase()}</span><span><b>{incident.source_name}</b><small>Collected {formatTime(incident.collected_at)}</small></span><a href={incident.source_url} target="_blank" rel="noreferrer" aria-label={`Open source: ${incident.source_name}`}>Open <Icon name="arrow" size={14}/></a></div>
      </section>

      <dl className="incident-meta">
        <div><dt><Icon name="pin" size={14}/>Where</dt><dd>{locationText(incident)}</dd></div>
        <div><dt><Icon name="clock" size={14}/>Published</dt><dd>{formatPublished(incident)}{incident.published_estimate && <small className={`freshness-badge ${freshTone}`}>{freshnessLabel(incident)}</small>}</dd></div>
        <div><dt><Icon name="layers" size={14}/>Region</dt><dd>{incident.regions?.length ? incident.regions.join(', ') : 'Not named in source'}</dd></div>
      </dl>

      <EvidenceMedia key={`media-${incident.id}`} media={incident.media} sourceUrl={incident.source_url}/>
      <ReportHints incident={incident} incidents={incidents} onSelect={onSelect}/>

      <section className="review-area" aria-label="Review this report">
        <div className="safety-callout"><Icon name="alert" size={15}/><p>Evidence to review. Current road status and impact are not confirmed.</p></div>
        <span className="desk-label">Your review</span>
        <div className="review-controls"><label className="sr-only" htmlFor={`review-status-${incident.id}`}>Review status</label><select id={`review-status-${incident.id}`} value={reviewStatuses[incident.id] || incident.verification} onChange={(event) => setReviewStatuses((statuses) => ({ ...statuses, [incident.id]: event.target.value }))}><option value="unverified">Unverified</option><option value="confirmed">Confirmed</option><option value="conflicting">Conflicting</option><option value="unknown">Unknown</option><option value="resolved">Resolved (reopened / ended)</option><option value="dismissed">Dismissed (not relevant)</option></select><label className="sr-only" htmlFor={`review-note-${incident.id}`}>Review note</label><input id={`review-note-${incident.id}`} placeholder="Review note (required)" value={note} onChange={(event) => setReviewNotes((notes) => ({ ...notes, [incident.id]: event.target.value }))}/><button disabled={reviewBusyId === incident.id || note.trim().length < 3} onClick={saveReview}>{reviewBusyId === incident.id ? 'Saving…' : 'Save review'}</button></div>
        <div className="source-actions"><button type="button" className="text-button" onClick={recheck} disabled={!canRecheck || recheckBusyId === incident.id}><Icon name="refresh" size={14}/>{recheckBusyId === incident.id ? 'Re-checking…' : 'Re-check source'}</button><small>Last checked {incident.last_checked_at ? formatTime(incident.last_checked_at) : 'never'}</small></div>
        {incident.open_flags?.length > 0 && <div className="open-flags"><b>{incident.open_flags.length} open correction flag{incident.open_flags.length === 1 ? '' : 's'} · the next review closes them</b>{incident.open_flags.map((flag) => <span key={flag.created_at}>{FLAG_REASONS[flag.reason] || flag.reason} · {formatTime(flag.created_at)}{flag.note ? ` — ${flag.note}` : ''}</span>)}</div>}
        <div className="desk-more">
          <Provenance incident={incident}/>
          <details className="verified-location"><summary>Add reviewer-confirmed map location</summary><input aria-label={`Location name for ${incident.title}`} placeholder="Location from source" value={reviewLocations[incident.id]?.name ?? (incident.location_text || '')} onChange={(event) => editLocation('name', event.target.value)}/><div><input aria-label={`Latitude for ${incident.title}`} type="number" min="-90" max="90" step="any" placeholder="Latitude" value={reviewLocations[incident.id]?.latitude ?? (incident.latitude ?? '')} onChange={(event) => editLocation('latitude', event.target.value)}/><input aria-label={`Longitude for ${incident.title}`} type="number" min="-180" max="180" step="any" placeholder="Longitude" value={reviewLocations[incident.id]?.longitude ?? (incident.longitude ?? '')} onChange={(event) => editLocation('longitude', event.target.value)}/></div><small>Only enter coordinates you checked in the linked source. Empty both fields and save to remove a wrong location.</small></details>
          <details className="flag-form"><summary>Flag a problem with this record</summary><div><label className="sr-only" htmlFor={`flag-reason-${incident.id}`}>Problem</label><select id={`flag-reason-${incident.id}`} value={flagDrafts[incident.id]?.reason || 'outdated'} onChange={(event) => editFlag('reason', event.target.value)}>{Object.entries(FLAG_REASONS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><label className="sr-only" htmlFor={`flag-note-${incident.id}`}>Details</label><input id={`flag-note-${incident.id}`} maxLength="500" placeholder="What is wrong? (optional)" value={flagDrafts[incident.id]?.note || ''} onChange={(event) => editFlag('note', event.target.value)}/><button type="button" disabled={flagBusyId === incident.id} onClick={sendFlag}>{flagBusyId === incident.id ? 'Sending…' : 'Send flag'}</button></div><small>Flags go to a reviewer. They never change the report’s status on their own.</small></details>
        </div>
      </section>
      <Timeline key={`timeline-${incident.id}`} events={incident.timeline}/>
    </div> : scopes?.current === 'route' ? <div className="evidence-empty"><span className="empty-illustration"><Icon name="route" size={24}/></span><b>No reports matched to this route</b><p>No reports does not mean the road is clear. Reports only match when they are placed near the route or name a highway it uses.</p>{scopes.all > 0 && <button type="button" className="impact-more" onClick={() => scopes.onChange('all')}>Show all {scopes.all} reports</button>}</div>
      : <div className="evidence-empty"><span className="empty-illustration"><Icon name="layers" size={24}/></span><b>{incidents.length ? 'No matching evidence' : 'No evidence collected yet'}</b><p>{incidents.length ? 'Try another search term or filter.' : 'No reports does not mean a road is clear.'}</p></div>}
  </article>
}
