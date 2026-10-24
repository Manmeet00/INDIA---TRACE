import { useCallback, useEffect, useState } from 'react'
import { BASE_LAYERS, OVERLAYS } from '../lib/mapLayers.js'

const STORAGE_KEY = 'india-trace.map-layers'

function read() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return {
      base: BASE_LAYERS[saved.base] ? saved.base : 'default',
      overlays: Array.isArray(saved.overlays) ? saved.overlays.filter((key) => OVERLAYS[key]) : [],
    }
  } catch {
    return { base: 'default', overlays: [] }
  }
}

// The chosen map type and map details, remembered in this browser.
export function useMapLayers() {
  const [layers, setLayers] = useState(read)
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(layers)) } catch { /* private mode: not remembered */ }
  }, [layers])
  const setBase = useCallback((base) => setLayers((current) => ({ ...current, base })), [])
  const toggleOverlay = useCallback((key) => setLayers((current) => ({
    ...current, overlays: current.overlays.includes(key) ? current.overlays.filter((item) => item !== key) : [...current.overlays, key],
  })), [])
  return { ...layers, setBase, toggleOverlay }
}
