import { useCallback, useEffect, useState } from 'react'
import { getLatestCollectionRun, getMapConfig, getMetrics, getRegion, loadWorkspace } from '../services/api.js'

// API status (online, offline, degraded), stored evidence, the latest collection run, the region with its coverage,
// and monitoring figures; loaded on start and after every change.
export function useWorkspace() {
  const [incidents, setIncidents] = useState([])
  const [apiStatus, setApiStatus] = useState('checking')
  const [lastRun, setLastRun] = useState(null)
  const [problem, setProblem] = useState('')
  const [region, setRegion] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [mapConfig, setMapConfig] = useState(null)

  const apply = useCallback((workspace) => {
    setApiStatus(workspace.status)
    setProblem(workspace.problem)
    if (workspace.incidents) setIncidents(workspace.incidents)
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
    return () => { active = false }
  }, [apply])

  const refresh = useCallback(async () => {
    const workspace = await loadWorkspace()
    apply(workspace)
    if (workspace.status !== 'online') throw new Error(workspace.problem)
  }, [apply])

  return { incidents, apiStatus, problem, lastRun, region, metrics, mapConfig, refresh }
}
