import { useCallback, useEffect, useRef, useState } from 'react'
import { getLatestCollectionRun, getMapConfig, getMetrics, getRegion, loadWorkspace } from '../services/api.js'

// The dashboard reloads its data this often while the tab is visible, so scheduled collections show up live.
export const LIVE_REFRESH_MS = 60000

// API status (online, offline, degraded), stored evidence, the latest collection run, the region with its coverage,
// monitoring figures and the collection schedule; loaded on start, every minute, and after every change.
export function useWorkspace() {
  const [incidents, setIncidents] = useState([])
  const [apiStatus, setApiStatus] = useState('checking')
  const [lastRun, setLastRun] = useState(null)
  const [problem, setProblem] = useState('')
  const [region, setRegion] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [mapConfig, setMapConfig] = useState(null)
  const [schedule, setSchedule] = useState(null)
  const [updatedAt, setUpdatedAt] = useState(null)
  // Reports that appeared since the previous load, so a live refresh can say what is new.
  const [arrivals, setArrivals] = useState(null)
  const knownIds = useRef(null)

  const apply = useCallback((workspace) => {
    setApiStatus(workspace.status)
    setProblem(workspace.problem)
    if (workspace.health) setSchedule(workspace.health)
    if (workspace.incidents) {
      const fresh = knownIds.current ? workspace.incidents.filter((item) => !knownIds.current.has(item.id)) : []
      if (fresh.length) setArrivals({ count: fresh.length, at: new Date() })
      knownIds.current = new Set(workspace.incidents.map((item) => item.id))
      setIncidents(workspace.incidents)
      setUpdatedAt(new Date())
    }
    // The run log, region coverage and metrics are informational; the evidence list still works without them.
    getLatestCollectionRun().then(setLastRun).catch(() => {})
    getRegion().then(setRegion).catch(() => {})
    getMetrics().then(setMetrics).catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    loadWorkspace().then((workspace) => { if (active) apply(workspace) })
    // Without the API the map still works, on OpenStreetMap.
    getMapConfig().catch(() => ({ provider: 'osm' })).then((config) => { if (active) setMapConfig(config) })
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadWorkspace().then((workspace) => { if (active) apply(workspace) })
    }, LIVE_REFRESH_MS)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [apply])

  const refresh = useCallback(async () => {
    const workspace = await loadWorkspace()
    apply(workspace)
    if (workspace.status !== 'online') throw new Error(workspace.problem)
  }, [apply])

  return { incidents, apiStatus, problem, lastRun, region, metrics, mapConfig, schedule, updatedAt, arrivals, refresh }
}
