import { useEffect, useRef, useState } from 'react'
import { escapeHtml, loadMappls } from '../lib/mappls.js'
import { INACTIVE_STATES, mapCategory, statusLabel } from '../lib/format.js'
import { BORDER_COLOR, MASK_COLOR } from '../lib/mapStyle.js'

// Same colours as the OpenStreetMap view, so routes and evidence read the same on either map.
const COLORS = { route: '#0878e8', candidate: '#64748b', origin: '#079352', destination: '#e44a58', confirmed: '#df3946', stale: '#9ba8b8', other: '#e99b28' }
const DEFAULT_VIEW = { center: { lat: 26.2, lng: 92.4 }, zoom: 6 }
const READY_TIMEOUT_MS = 15000
let mapCount = 0

function dot(color, size) {
  return `<span class="mappls-dot" style="width:${size}px;height:${size}px;background:${color}"></span>`
}

function marker(mappls, map, { lat, lng, color, size, popup }) {
  return new mappls.Marker({ map, position: { lat, lng }, html: dot(color, size), width: size, height: size,
    offset: [0, size / 2], popupHtml: escapeHtml(popup) })
}

// The Mappls Web SDK draws on its own canvas, so routes and markers are added and removed imperatively.
// onUnavailable is called if the SDK cannot load or the map never becomes ready (for example an invalid key).
// One polygon covering the world with India's land parts as holes, as standard GeoJSON ([lng, lat]).
function indiaMask(boundary) {
  return { type: 'FeatureCollection', features: [{ type: 'Feature',
    properties: { fill: MASK_COLOR, 'fill-opacity': 1, stroke: BORDER_COLOR, 'stroke-opacity': 0.55, 'stroke-width': 1.2 },
    geometry: { type: 'Polygon', coordinates: [[[-180, -89], [180, -89], [180, 89], [-180, 89], [-180, -89]], ...boundary] } }] }
}

export default function MapplsMap({ apiKey, plan, incidents, selectedRoute, selectedIncident, onSelectIncident, hiddenTypes, boundary, onUnavailable }) {
  // The SDK documents creating a map from its container's id.
  const [containerId] = useState(() => `mappls-map-${++mapCount}`)
  const select = useRef(onSelectIncident)
  const [map, setMap] = useState(null)

  useEffect(() => { select.current = onSelectIncident }, [onSelectIncident])

  useEffect(() => {
    let cancelled = false
    let instance = null
    const timer = setTimeout(() => { if (!cancelled) onUnavailable('The Mappls map did not start in time.') }, READY_TIMEOUT_MS)
    loadMappls(apiKey).then((mappls) => {
      if (cancelled) return
      instance = new mappls.Map(containerId, {
        ...DEFAULT_VIEW, zoomControl: true, zoomControlOptions: { position: mappls.ControlPosition?.RIGHT_BOTTOM },
        fullscreenControl: false, traffic: false, clickableIcons: false, backgroundColor: '#e2ece7',
        token_callback: () => { if (!cancelled) onUnavailable('Mappls rejected the map key.') },
      })
      instance.addListener('load', () => {
        if (cancelled) return
        clearTimeout(timer)
        setMap(instance)
      })
    }).catch((error) => { if (!cancelled) onUnavailable(error.message) })
    return () => {
      cancelled = true
      clearTimeout(timer)
      instance?.remove?.()
    }
  }, [apiKey, containerId, onUnavailable])

  // Only India: added before routes and markers, so they draw above it.
  useEffect(() => {
    if (!map || !boundary) return undefined
    const mappls = window.mappls
    const layer = mappls.addGeoJson({ map, data: indiaMask(boundary), cType: 1, preserveViewport: true })
    return () => mappls.remove({ map, layer })
  }, [map, boundary])

  // Routes: the selected one on top, and the view fitted to it, as in the OpenStreetMap view.
  useEffect(() => {
    if (!map) return undefined
    const mappls = window.mappls
    const chosen = plan?.routes?.find((item) => item.id === selectedRoute) || plan?.routes?.[0]
    const layers = [...(plan?.routes || [])].sort((a, b) => (a.id === chosen?.id) - (b.id === chosen?.id)).map((item) => {
      const selected = item.id === chosen?.id
      return new mappls.Polyline({
        map, path: item.geometry.coordinates.map(([lng, lat]) => ({ lat, lng })),
        strokeColor: selected ? COLORS.route : COLORS.candidate, strokeOpacity: selected ? 0.95 : 0.55, strokeWeight: selected ? 5 : 3,
        fitbounds: selected, fitboundOptions: { padding: 36, duration: 0 },
      })
    })
    if (!plan) {
      map.setCenter(DEFAULT_VIEW.center)
      map.setZoom(DEFAULT_VIEW.zoom)
    }
    return () => layers.forEach((layer) => mappls.remove({ map, layer }))
  }, [map, plan, selectedRoute])

  // Origin, destination and reports with reviewer-confirmed coordinates; text mentions never become map points.
  useEffect(() => {
    if (!map) return undefined
    const mappls = window.mappls
    const layers = []
    if (plan?.origin) layers.push(marker(mappls, map, { lat: plan.origin.latitude, lng: plan.origin.longitude, color: COLORS.origin, size: 16, popup: `Origin · ${plan.origin.name}` }))
    if (plan?.destination) layers.push(marker(mappls, map, { lat: plan.destination.latitude, lng: plan.destination.longitude, color: COLORS.destination, size: 16, popup: `Destination · ${plan.destination.name}` }))
    incidents.filter((item) => !INACTIVE_STATES.includes(item.verification) && !hiddenTypes.includes(mapCategory(item)) && item.latitude != null && item.longitude != null)
      .forEach((item) => {
        const color = item.evidence_status === 'confirmed' ? COLORS.confirmed : item.evidence_status === 'stale' ? COLORS.stale : COLORS.other
        const point = marker(mappls, map, { lat: item.latitude, lng: item.longitude, color, size: selectedIncident?.id === item.id ? 18 : 14, popup: `${item.title} · ${statusLabel(item)}` })
        point.addListener('click', () => select.current(item.id))
        layers.push(point)
      })
    return () => layers.forEach((layer) => mappls.remove({ map, layer }))
  }, [map, plan, incidents, selectedIncident, hiddenTypes])

  return <div id={containerId} className="map-canvas mappls-canvas" aria-label="Mappls map"/>
}
