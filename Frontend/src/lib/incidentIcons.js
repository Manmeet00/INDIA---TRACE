// Road report symbols in the style of Google Maps' incident markers: a white symbol on a coloured circle with a
// white edge. One per report type (evidence.py EVENT_TYPES); anything else is a general hazard.
const W = 'stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"'

export const INCIDENT_STYLES = {
  accident: {
    label: 'Accident', color: '#d93025',
    glyph: `<g ${W}><path d="M3.5 17v-3.2l1.7-4A1.6 1.6 0 0 1 6.7 8.8h6.6a1.6 1.6 0 0 1 1.5 1l1.7 4V17"/><path d="M3.5 14h13"/></g>`
      + '<circle cx="6.8" cy="17.2" r="1.5" fill="#fff"/><circle cx="13.2" cy="17.2" r="1.5" fill="#fff"/>'
      + `<path ${W} stroke-width="1.6" d="m18.5 3 .6 2.3 2.3-.6-1.2 2 2 1.3-2.4.4"/>`,
  },
  closure: { label: 'Road closed', color: '#d93025', glyph: '<rect x="5" y="10.3" width="14" height="3.4" rx="1" fill="#fff"/>' },
  construction: {
    label: 'Roadworks', color: '#e8710a',
    glyph: '<path d="M9.6 5h4.8L18 18H6Z" fill="#fff"/><path d="M8.3 10h7.4M7.3 14h9.4" stroke="#e8710a" stroke-width="1.8"/><path d="M4.5 19.2h15" stroke="#fff" stroke-width="2" stroke-linecap="round"/>',
  },
  landslide: {
    label: 'Landslide', color: '#9c5300',
    glyph: '<path d="M3 19.5h18L8.5 6.5Z" fill="#fff"/><circle cx="16.5" cy="8" r="2" fill="#fff"/><circle cx="19.5" cy="12.5" r="1.4" fill="#fff"/>',
  },
  flood: { label: 'Flooding', color: '#1a73e8', glyph: `<path ${W} d="M3 9.5c2 0 2-1.5 4.5-1.5S9.5 9.5 12 9.5 14 8 16.5 8 19 9.5 21 9.5M3 14.5c2 0 2-1.5 4.5-1.5s2 1.5 4.5 1.5 2-1.5 4.5-1.5 2.5 1.5 4.5 1.5"/>` },
  bridge: { label: 'Bridge', color: '#5f6368', glyph: `<path ${W} d="M3 9h18M4.5 9v8M19.5 9v8M4.5 14c2.5-2.6 5-3.6 7.5-3.6s5 1 7.5 3.6"/>` },
  weather: { label: 'Heavy rain', color: '#1967d2', glyph: `<path ${W} d="M7 14.5a4 4 0 1 1 1-7.8A5 5 0 0 1 17.5 8.5a3.2 3.2 0 0 1-.8 6H7Z"/><path ${W} d="m8.5 17.5-1 2.5m4.5-2.5-1 2.5m4.5-2.5-1 2.5"/>` },
  other: { label: 'Road report', color: '#f9ab00', glyph: '<path d="M12 5.5v8.5" stroke="#fff" stroke-width="2.8" stroke-linecap="round"/><circle cx="12" cy="18" r="1.6" fill="#fff"/>' },
}

export function incidentStyle(type) {
  return INCIDENT_STYLES[type] || INCIDENT_STYLES.other
}

/** The marker's HTML: approximate (placed at a town) gets a dashed ring; stale is faded; selected is larger. */
export function incidentIconHtml(type, { approximate = false, stale = false, selected = false } = {}) {
  const style = incidentStyle(type)
  const classes = ['incident-icon', approximate && 'approx', stale && 'stale', selected && 'selected'].filter(Boolean).join(' ')
  return `<span class="${classes}" style="--tone:${style.color}"><svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">${style.glyph}</svg></span>`
}
