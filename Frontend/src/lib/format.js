// Labels and formatting shared by the panels. Codes (event types, evidence states, recommendations) come from the API.

export function formatDistance(meters) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${meters} m`
}

export function formatDuration(seconds) {
  const mins = Math.round(seconds / 60)
  const hours = Math.floor(mins / 60)
  const rest = mins % 60
  return hours ? `${hours} hr ${rest} min` : `${rest} min`
}

export function formatTime(value) {
  if (!value) return 'Time not provided by source'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? 'Time not provided by source' : new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

// published_estimate is parsed by the API; approximate values came from a date or relative text like "3 months ago".
export function formatPublished(incident) {
  if (!incident.published_estimate) return incident.published_at ? `Source time unclear: “${incident.published_at}”` : 'Time not provided by source'
  if (!incident.published_approximate) return formatTime(incident.published_estimate)
  const day = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium' }).format(new Date(incident.published_estimate))
  return /ago$/i.test(incident.published_at) ? `≈ ${day} (“${incident.published_at}” at collection)` : day
}

function formatHours(hours) {
  return hours >= 48 ? `${Math.round(hours / 24)} days` : `${hours} h`
}

// Freshness windows differ by event type (API: freshness_window_h), e.g. 12 h for accidents, 72 h for landslides.
export function freshnessLabel(item) {
  const window = formatHours(item.freshness_window_h || 24)
  return item.freshness === 'fresh' ? `Within ${window} window` : item.freshness === 'stale' ? `Older than ${window} window` : 'Source time unknown'
}

export const LOCATION_LABELS = { precise: 'Reviewer-confirmed coordinates', approximate: 'Approximate · town named in report', road_mentioned: 'Road named · exact spot unknown', place_mentioned: 'Place named · exact spot unknown', none: 'No location in source' }
export const FLAG_REASONS = { outdated: 'Outdated', wrong_location: 'Wrong location', duplicate: 'Duplicate', not_relevant: 'Not relevant', other: 'Other' }
export const TIME_WINDOWS = [['1', 'Last 24 hours'], ['7', 'Last 7 days'], ['30', 'Last 30 days'], ['365', 'Last year']]
export const INACTIVE_STATES = ['dismissed', 'resolved']
export const PILOT_ROADS = ['NH-6', 'NH-306', 'NH-27', 'NH-37', 'NH-2', 'NH-10']

const RECOMMENDATIONS = {
  proceed_cautiously: { label: 'Proceed cautiously', pill: 'Proceed with care', tone: 'proceed' },
  consider_alternative: { label: 'Consider an alternative', pill: 'Alternative advised', tone: 'alternative' },
  verify_before_dispatch: { label: 'Verify before dispatch', pill: 'Verify first', tone: 'verify' },
}

// Event types are keyword tags from the API. The map groups the less common ones under "other".
export const EVENT_LABELS = { closure: 'Closure', landslide: 'Landslide', flood: 'Flood', bridge: 'Bridge', weather: 'Weather', accident: 'Accident', construction: 'Works', other: 'Other' }
export const MAP_CATEGORIES = [['accident', 'Accidents'], ['closure', 'Road closures'], ['construction', 'Roadworks'], ['landslide', 'Landslides'], ['flood', 'Floods'], ['bridge', 'Bridge damage'], ['other', 'Other reports']]

// evidence_status comes from the API: stale outranks a reviewer's confirmation so old reports never read as current.
export const STATUS_LABELS = { confirmed: 'Confirmed by reviewer', corroborated: 'Corroborated', unverified: 'Unverified', conflicting: 'Conflicting', stale: 'Stale', unknown: 'Unknown', resolved: 'Resolved', dismissed: 'Dismissed' }

export function statusLabel(item) {
  return item.evidence_status === 'stale' && item.verification === 'confirmed' ? 'Stale · confirmed earlier' : STATUS_LABELS[item.evidence_status] || item.verification
}

export function mapCategory(item) {
  return MAP_CATEGORIES.some(([key]) => key === item.event_type) ? item.event_type : 'other'
}

export function adviceFor(code) {
  return RECOMMENDATIONS[code] || RECOMMENDATIONS.verify_before_dispatch
}

export function exposureSummary(exposure) {
  if (!exposure) return 'Disruption exposure not assessed'
  const km = `${exposure.tolerance_m / 1000} km`
  const nearby = Object.values(exposure.nearby).reduce((total, count) => total + count, 0)
  // A confirmation older than its report's freshness window is not counted as confirmed: it may no longer hold.
  const confirmed = exposure.nearby.confirmed - (exposure.nearby_confirmed_stale || 0)
  const parts = [nearby ? `${nearby} report${nearby === 1 ? '' : 's'} within ${km}${confirmed ? ` (${confirmed} confirmed)` : ''}` : `No located reports within ${km}`]
  const placed = exposure.place_match_ids?.length || 0
  if (placed) parts.push(`${placed} name${placed === 1 ? 's' : ''} a town on the route (${Object.keys(exposure.place_matches).join(', ')}, approximate)`)
  const mentioned = exposure.highway_mention_ids?.length || 0
  if (mentioned) parts.push(`${mentioned} name${mentioned === 1 ? 's' : ''} ${Object.keys(exposure.highway_mentions).join(', ')} (location unconfirmed)`)
  if (exposure.unlocated_reports - mentioned - placed > 0) parts.push(`${exposure.unlocated_reports - mentioned - placed} unlocated`)
  return parts.join(' · ')
}

// The name the person typed; saved snapshots without it fall back to the geocoder's first name part.
export function placeName(place) {
  return (place.query || place.name).split(',')[0]
}

// Where a report sits on the map: reviewer coordinates (exact) or the town it names (approximate).
export function locationText(incident) {
  if (incident.location_text) return `${incident.location_text} · reviewer-confirmed`
  if (incident.approximate_location) return `Approximate · ${incident.approximate_location.place} named in report`
  return LOCATION_LABELS[incident.location_confidence] || 'Location unknown'
}

// Report 7 and 9: where a source comes from. Official means a government domain (gov.in, nic.in).
export const SOURCE_LABELS = { official: 'Official source', news: 'News', social: 'Social post', other: 'Other web page' }

// Report 6.5: new, then needs a re-check of its source, then stale; resolved and dismissed come from a reviewer.
export const LIFECYCLE_LABELS = { new: 'New', needs_recheck: 'Needs re-check', stale: 'Stale', resolved: 'Resolved', dismissed: 'Dismissed' }

export function formatShare(value) {
  return value == null ? 'not measured' : `${Math.round(value * 100)}%`
}
