import { useCallback, useEffect, useState } from 'react'
import { getLatestCollectionRun, loadWorkspace } from '../services/api.js'

// API status, stored evidence and the latest collection run, loaded on start and after every change.
export function useWorkspace() {
  const [incidents, setIncidents] = useState([])
  const [apiStatus, setApiStatus] = useState('checking')
  const [lastRun, setLastRun] = useState(null)

  const apply = useCallback((workspace) => {
    setApiStatus(workspace.online ? 'online' : 'offline')
    if (workspace.incidents) setIncidents(workspace.incidents)
    // The run log is informational; the evidence list still works without it.
    getLatestCollectionRun().then(setLastRun).catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    loadWorkspace().then((workspace) => { if (active) apply(workspace) })
    return () => { active = false }
  }, [apply])

  const refresh = useCallback(async () => {
    const workspace = await loadWorkspace()
    apply(workspace)
    if (!workspace.incidents) throw new Error('Could not load evidence records. Check that the API is running.')
  }, [apply])

  return { incidents, apiStatus, lastRun, refresh }
}
