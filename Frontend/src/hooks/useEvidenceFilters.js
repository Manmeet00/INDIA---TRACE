import { useMemo, useState } from 'react'

const ALL = { type: 'all', status: 'all', region: 'all', road: 'all', time: 'all', source: 'all' }

// Text search plus the evidence list's filters. The publish-time cutoff is fixed when the filter changes,
// so the list does not shift while it is open.
export function useEvidenceFilters(incidents, search) {
  const [filters, setFilters] = useState(ALL)
  const [publishedAfter, setPublishedAfter] = useState(null)

  const setFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }))
    if (key === 'time') setPublishedAfter(value === 'all' ? null : Date.now() - Number(value) * 86400000)
  }

  const visibleIncidents = useMemo(() => {
    const text = search.trim().toLowerCase()
    return incidents.filter((item) => `${item.title} ${item.summary} ${item.source_name}`.toLowerCase().includes(text)
      && (filters.type === 'all' || (filters.type === 'other' ? item.event_type === 'other' : item.event_types?.includes(filters.type)))
      && (filters.status === 'all' || item.evidence_status === filters.status)
      && (filters.region === 'all' || item.regions?.includes(filters.region))
      && (filters.road === 'all' || item.mentions?.highways?.includes(filters.road))
      && (filters.source === 'all' || item.source_name === filters.source)
      && (publishedAfter === null || (item.published_estimate && new Date(item.published_estimate).valueOf() >= publishedAfter)))
  }, [incidents, search, filters, publishedAfter])

  return { filters, setFilter, visibleIncidents }
}
