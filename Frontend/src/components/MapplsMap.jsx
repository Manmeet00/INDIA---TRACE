import { useEffect, useRef, useState } from 'react'
import { escapeHtml, loadMappls } from '../lib/mappls.js'
import { INACTIVE_STATES, mapCategory, statusLabel } from '../lib/format.js'
import { BORDER_COLOR, HERE_COLOR, MASK_COLOR, inIndia, mapplsHereZoom } from '../lib/mapStyle.js'

// Same colours as the OpenStreetMap view, so routes and evidence read the same on either map.
const COLORS = { route: '#0878e8', candidate: '#64748b', origin: '#079352', destination: '#e44a58', confirmed: '#df3946', stale: '#9ba8b8', other: '#e99b28' }
const DEFAULT_VIEW = { center: { lat: 26.2, lng: 92.4 }, zoom: 6 }
const READY_TIMEOUT_MS = 15000
const IMAGERY_ID = 'india-trace-imagery'
const IMAGERY_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
let mapCount = 0

function dot(color, size) {
  return `<span class="mappls-dot" style="width:${size}px;height:${size}px;background:${color}"></span>`
}

function marker(mappls, map, { lat, lng, color, size, popup }) {
  return new mappls.Marker({ map, position: { lat, lng }, html: dot(color, size), width: size, height: size,
    offset: [0, size / 2], popupHtml: escapeHtml(popup) })
}

// Takes a route line, marker or layer off the map. When the map is being closed (switching to another map type),
// React runs this after the map itself is gone, and the SDK throws for a map without a style: the layer went with it.
function removeLayer(mappls, map, layer) {
  if (map.__indiaTraceRemoved) return
  try { mappls.remove({ map, layer }) } catch { /* the map was removed meanwhile */ }
}

// The Mappls Web SDK draws on its own canvas, so routes and markers are added and removed imperatively.
// onUnavailable is called if the SDK cannot load or the map never becomes ready (for example an invalid key).
// One polygon covering the world with India's land parts as holes, as standard GeoJSON ([lng, lat]).
function indiaMask(boundary) {
  return { type: 'FeatureCollection', features: [{ type: 'Feature',
    properties: { fill: MASK_COLOR, 'fill-opacity': 1, stroke: BORDER_COLOR, 'stroke-opacity': 0.55, 'stroke-width': 1.2 },
    geometry: { type: 'Polygon', coordinates: [[[-180, -89], [180, -89], [180, 89], [-180, 89], [-180, -89]], ...boundary] } }] }
}

export default function MapplsMap({ apiKey, plan, incidents, selectedRoute, selectedIncident, onSelectIncident, hiddenTypes, boundary, here, focusKey, imagery = false, onUnavailable }) {
  // The SDK documents creating a map from its container's id.
  const [containerId] = useState(() => `mappls-map-${++mapCount}`)
  const select = useRef(onSelectIncident)
  const latestHere = useRef(here)
  const centered = useRef(false)
  const [map, setMap] = useState(null)
  const baseLayers = useRef([]) // Mappls' own style layers, as loaded (before the mask, routes and markers)

  useEffect(() => { select.current = onSelectIncident }, [onSelectIncident])
  useEffect(() => { latestHere.current = here }, [here])

  useEffect(() => {
    let cancelled = false
    let instance = null
    const timer = setTimeout(() => { if (!cancelled) onUnavailable('The Mappls map did not start in time.') }, READY_TIMEOUT_MS)
    loadMappls(apiKey).then((mappls) => {
      if (cancelled) return
      instance = new mappls.Map(containerId, {
        ...DEFAULT_VIEW, zoomControl: true, zoomControlOptions: { position: mappls.ControlPosition?.RIGHT_BOTTOM },
        // traffic: Mappls' live traffic control, so a dispatcher can switch real-time traffic on.
        fullscreenControl: false, traffic: true, clickableIcons: false, backgroundColor: '#e2ece7',
        token_callback: () => { if (!cancelled) onUnavailable('Mappls rejected the map key.') },
      })
      instance.addListener('load', () => {
        if (cancelled) return
        clearTimeout(timer)
        try { baseLayers.current = instance.getStyle().layers.map(({ id, type }) => ({ id, type })) } catch { baseLayers.current = [] }
        setMap(instance)
      })
    }).catch((error) => { if (!cancelled) onUnavailable(error.message) })
    return () => {
      cancelled = true
      clearTimeout(timer)
      // After this render's other clean-ups have taken their layers off, so none of them meets a removed map.
      const closing = instance
      queueMicrotask(() => {
        if (!closing) return
        closing.__indiaTraceRemoved = true
        try { closing.remove?.() } catch { /* already gone */ }
      })
    }
  }, [apiKey, containerId, onUnavailable])

  // Only India: added before routes and markers, so they draw above it. fitbounds: false keeps the view where it is;
  // by default Mappls fits the map to the layer, which for this world-sized mask means zoom 1 centred on 0°, 0°
  // (preserveViewport is not a Mappls option and does not prevent it).
  useEffect(() => {
    if (!map || !boundary) return undefined
    const mappls = window.mappls
    const layer = mappls.addGeoJson({ map, data: indiaMask(boundary), cType: 1, fitbounds: false })
    return () => removeLayer(mappls, map, layer)
  }, [map, boundary])

  // Satellite: Esri's imagery (as on the OpenStreetMap satellite view) under Mappls' own roads and names, so colony,
  // mohalla and galli names show on the photo. Mappls' land, water and building fills are hidden; its roads, labels,
  // the India mask, routes and markers stay above the imagery. Default restores the map as it was.
  useEffect(() => {
    if (!map || !imagery || !baseLayers.current.length) return undefined
    const fills = baseLayers.current.filter(({ type }) => type === 'fill' || type === 'background' || type === 'fill-extrusion')
    const above = baseLayers.current.find(({ type }) => type === 'line' || type === 'symbol')
    const hidden = []
    try {
      map.addSource(IMAGERY_ID, { type: 'raster', tileSize: 256, maxzoom: 19, tiles: [IMAGERY_TILES] })
      map.addLayer({ id: IMAGERY_ID, type: 'raster', source: IMAGERY_ID }, above?.id)
      for (const { id } of fills) {
        hidden.push([id, map.getLayoutProperty(id, 'visibility') || 'visible'])
        map.setLayoutProperty(id, 'visibility', 'none')
      }
    } catch { /* the style changed underneath: the map keeps its own look */ }
    return () => {
      if (map.__indiaTraceRemoved) return
      try {
        hidden.forEach(([id, visibility]) => map.setLayoutProperty(id, 'visibility', visibility))
        if (map.getLayer(IMAGERY_ID)) map.removeLayer(IMAGERY_ID)
        if (map.getSource(IMAGERY_ID)) map.removeSource(IMAGERY_ID)
      } catch { /* the map is closing */ }
    }
  }, [map, imagery])

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
      const position = latestHere.current
      map.setCenter(inIndia(position) ? { lat: position.latitude, lng: position.longitude } : DEFAULT_VIEW.center)
      map.setZoom(inIndia(position) ? mapplsHereZoom(position.latitude) : DEFAULT_VIEW.zoom)
    }
    return () => layers.forEach((layer) => removeLayer(mappls, map, layer))
  }, [map, plan, selectedRoute])

  // The blue dot; without a route the map centres on it once, and again whenever the person asks.
  useEffect(() => {
    if (!map || !inIndia(here)) return undefined
    const mappls = window.mappls
    const dot = new mappls.Marker({ map, position: { lat: here.latitude, lng: here.longitude }, html: `<span class="here-dot" style="background:${HERE_COLOR}"></span>`,
      width: 18, height: 18, offset: [0, 9], popupHtml: 'Your location' })
    if (!plan && !centered.current) {
      centered.current = true
      map.setCenter({ lat: here.latitude, lng: here.longitude })
      map.setZoom(mapplsHereZoom(here.latitude))
    }
    return () => removeLayer(mappls, map, dot)
  }, [map, here, plan])

  useEffect(() => {
    const position = latestHere.current
    if (!map || !focusKey || !inIndia(position)) return
    map.setCenter({ lat: position.latitude, lng: position.longitude })
    map.setZoom(mapplsHereZoom(position.latitude))
  }, [map, focusKey])

  // Origin, destination and reports with reviewer-confirmed coordinates; text mentions never become map points.
  useEffect(() => {
    if (!map) return undefined
    const mappls = window.mappls
    const layers = []
    if (plan?.origin) layers.push(marker(mappls, map, { lat: plan.origin.latitude, lng: plan.origin.longitude, color: COLORS.origin, size: 16, popup: `Origin · ${plan.origin.name}` }))
    if (plan?.destination) layers.push(marker(mappls, map, { lat: plan.destination.latitude, lng: plan.destination.longitude, color: COLORS.destination, size: 16, popup: `Destination · ${plan.destination.name}` }))
    const shown = (item) => !INACTIVE_STATES.includes(item.verification) && !hiddenTypes.includes(mapCategory(item))
    incidents.filter((item) => shown(item) && item.latitude != null && item.longitude != null)
      .forEach((item) => {
        const color = item.evidence_status === 'confirmed' ? COLORS.confirmed : item.evidence_status === 'stale' ? COLORS.stale : COLORS.other
        const point = marker(mappls, map, { lat: item.latitude, lng: item.longitude, color, size: selectedIncident?.id === item.id ? 18 : 14, popup: `${item.title} · ${statusLabel(item)}` })
        point.addListener('click', () => select.current(item.id))
        layers.push(point)
      })
    return () => layers.forEach((layer) => removeLayer(mappls, map, layer))
  }, [map, plan, incidents, selectedIncident, hiddenTypes])

  return <div id={containerId} className="map-canvas mappls-canvas" aria-label="Mappls map"/>
}
