import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { Circle, CircleMarker, MapContainer, Marker, Pane, Polygon, Polyline, ScaleControl, TileLayer, Tooltip, WMSTileLayer, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import Icon from './Icon.jsx'
import LayersPanel from './LayersPanel.jsx'
import MapSearch from './MapSearch.jsx'
import NavigationPanel from './NavigationPanel.jsx'
import MapplsMap from './MapplsMap.jsx'
import { useMapLayers } from '../hooks/useMapLayers.js'
import { BASE_LAYERS, GIBS, OVERLAYS, aqiTone } from '../lib/mapLayers.js'
import { INACTIVE_STATES, MAP_CATEGORIES, mapCategory, placeName, statusLabel } from '../lib/format.js'
import { BORDER_COLOR, HERE_COLOR, HERE_ZOOM, INDIA_BOUNDS, MASK_COLOR, inIndia, insideBoundary } from '../lib/mapStyle.js'
import { placeNamesInView } from '../lib/placeNames.js'
import { drawRoadTile } from '../lib/hybridRoads.js'
import { prepareRoute, progress } from '../lib/navigation.js'
import { INCIDENT_STYLES, incidentIconHtml, incidentStyle } from '../lib/incidentIcons.js'
import { getAirQuality, loadIndiaBoundary } from '../services/api.js'

const WORLD = [[-89, -180], [-89, 180], [89, 180], [89, -180]]

function MapBounds({ geometry }) {
  const map = useMap()
  useEffect(() => {
    const points = geometry.coordinates.map(([longitude, latitude]) => [latitude, longitude])
    // The same map moves to each new route (it is never rebuilt, so loaded imagery, roads and names are kept).
    // No animation: a route chosen mid-zoom would otherwise throw in Leaflet (_leaflet_pos).
    // Room at the top for the search bar and at the bottom for the Start button, so neither covers the route.
    if (points.length > 1) map.fitBounds(points, { paddingTopLeft: [36, 72], paddingBottomRight: [64, 96], maxZoom: 10, animate: false })
  }, [geometry, map])
  return null
}

// Covers everything outside India and outlines its boundary, below routes and markers. Drawn on a canvas:
// the boundary has thousands of points, which SVG redraws slowly on every pan and zoom.
function IndiaMask({ boundary }) {
  const rings = useMemo(() => boundary.map((ring) => ring.map(([lng, lat]) => [lat, lng])), [boundary])
  const renderer = useMemo(() => L.canvas({ pane: 'india-mask', padding: 0.5 }), [])
  return <Pane name="india-mask" style={{ zIndex: 350 }}>
    <Polygon positions={[WORLD, ...rings]} interactive={false} renderer={renderer} pathOptions={{ stroke: false, fillColor: MASK_COLOR, fillOpacity: 1 }}/>
    <Polygon positions={rings.map((ring) => [ring])} interactive={false} renderer={renderer} pathOptions={{ color: BORDER_COLOR, weight: 1.2, opacity: 0.55, fill: false }}/>
  </Pane>
}

// Tiles load once zooming stops, not at every intermediate zoom level.
const TILE_OPTIONS = { updateWhenZooming: false, keepBuffer: 3 }

// The blue dot with its accuracy ring. Without a route the map centres on it once, when the first fix arrives;
// focusKey changes when the person asks to see their location again.
function HereLayer({ here, hasPlan, focusKey }) {
  const map = useMap()
  const centered = useRef(false)
  const latest = useRef(here)
  useEffect(() => { latest.current = here }, [here])
  useEffect(() => {
    if (hasPlan || centered.current || !inIndia(here)) return
    centered.current = true
    map.setView([here.latitude, here.longitude], HERE_ZOOM, { animate: false })
  }, [here, hasPlan, map])
  useEffect(() => {
    const position = latest.current
    if (focusKey && inIndia(position)) map.setView([position.latitude, position.longitude], Math.max(map.getZoom(), HERE_ZOOM), { animate: false })
  }, [focusKey, map])
  if (!inIndia(here)) return null
  return <>
    <Circle center={[here.latitude, here.longitude]} radius={here.accuracy || 0} interactive={false} pathOptions={{ color: HERE_COLOR, weight: 1, opacity: 0.4, fillColor: HERE_COLOR, fillOpacity: 0.1 }}/>
    <CircleMarker center={[here.latitude, here.longitude]} radius={7} pathOptions={{ color: '#fff', weight: 3, fillColor: HERE_COLOR, fillOpacity: 1 }}><Tooltip>Your location</Tooltip></CircleMarker>
  </>
}

// The followed route as Google Maps draws it while navigating: the part already driven in grey, the rest in blue
// with a darker edge, and a blue arrow at focus ({ position: [lat, lon], bearing }: the device while guiding, the
// current turn in a preview). Following keeps the map on the arrow; dragging the map stops that until Re-centre.
// Overview fits the rest of the route.
function NavigationLayer({ line, now, focus, following, overview, onUserMove }) {
  const map = useMap()
  useMapEvents({ dragstart: onUserMove })
  const position = focus?.position || null
  const latitude = position?.[0]
  const longitude = position?.[1]
  useEffect(() => {
    if (following && latitude != null) map.setView([latitude, longitude], Math.max(map.getZoom(), NAVIGATION_ZOOM), { animate: false })
  }, [following, latitude, longitude, map])
  const ahead = useMemo(() => {
    const rest = line.slice(now ? now.segment : 0).map(([lon, lat]) => [lat, lon])
    return now && !now.offRoute ? [[now.snapped[1], now.snapped[0]], ...rest] : rest
  }, [line, now])
  const behind = useMemo(() => (now && !now.offRoute
    ? [...line.slice(0, now.segment).map(([lon, lat]) => [lat, lon]), [now.snapped[1], now.snapped[0]]] : []), [line, now])
  useEffect(() => {
    // Room for the banner at the top and the sheet at the bottom.
    if (overview && ahead.length > 1) map.fitBounds(ahead, { paddingTopLeft: [40, 150], paddingBottomRight: [40, 120], animate: false })
  }, [overview, ahead, map])
  return <>
    {behind.length > 1 && <Polyline positions={behind} interactive={false} pathOptions={{ color: '#9aa0a6', weight: 7, opacity: 0.95 }}/>}
    <Polyline positions={ahead} interactive={false} pathOptions={{ color: '#1967d2', weight: 10, opacity: 1 }}/>
    <Polyline positions={ahead} interactive={false} pathOptions={{ color: '#4285f4', weight: 6, opacity: 1 }}/>
    {position && <Marker position={position} interactive={false} keyboard={false} zIndexOffset={1000}
      icon={L.divIcon({ className: '', html: `<span class="nav-arrow" style="transform: rotate(${Math.round(focus?.bearing || 0)}deg)">${ARROW_SVG}</span>`, iconSize: [40, 40], iconAnchor: [20, 20] })}/>}
  </>
}
const NAVIGATION_ZOOM = 17
const ARROW_SVG = '<svg width="40" height="40" viewBox="0 0 40 40"><path d="M20 4 33 34 20 27 7 34Z" fill="#1a73e8" stroke="#fff" stroke-width="3" stroke-linejoin="round"/></svg>'
const TOLL_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 21V9h7v12M4 13h7M11 12h9M14 12v-2M17 12v-2"/></svg>'

// Current air quality at your position and at the route's start and end, as small AQI labels.
function AirQualityLayer({ here, plan }) {
  const [readings, setReadings] = useState({})
  const points = useMemo(() => [
    ...(inIndia(here) ? [{ key: 'here', name: 'Your location', latitude: here.latitude, longitude: here.longitude }] : []),
    ...(plan ? [{ key: 'origin', name: placeName(plan.origin), ...plan.origin }, { key: 'destination', name: placeName(plan.destination), ...plan.destination }] : []),
  ].map(({ key, name, latitude, longitude }) => ({ key, name, latitude, longitude })), [here, plan])
  // Asked again only when a point moves about a kilometre, not for every update of a moving position.
  const signature = points.map((point) => `${point.key}:${point.latitude.toFixed(2)},${point.longitude.toFixed(2)}`).join('|')
  const latestPoints = useRef(points)
  useEffect(() => { latestPoints.current = points }, [points])
  useEffect(() => {
    let active = true
    latestPoints.current.forEach((point) => {
      getAirQuality(point.latitude, point.longitude)
        .then((reading) => { if (active) setReadings((current) => ({ ...current, [point.key]: reading })) })
        .catch(() => { if (active) setReadings((current) => ({ ...current, [point.key]: null })) })
    })
    return () => { active = false }
  }, [signature])
  return points.filter((point) => readings[point.key]).map((point) => {
    const reading = readings[point.key]
    return <Marker key={point.key} position={[point.latitude, point.longitude]} interactive={false}
      icon={L.divIcon({ className: '', html: `<span class="aqi-pill ${aqiTone(reading.us_aqi)}">AQI ${reading.us_aqi}</span>`, iconSize: [64, 22], iconAnchor: [32, 34] })}>
      <Tooltip>{`${point.name}: AQI ${reading.us_aqi}, ${reading.band} · PM2.5 ${reading.pm2_5} µg/m³`}</Tooltip>
    </Marker>
  })
}

// Place names over satellite imagery, anywhere in India, for the area on screen (lib/placeNames.js). Labels that
// would overlap a more important one (cities before towns before villages) are left out, so the map stays readable.
const LABEL_BOX = { width: 90, height: 18 }

function PlaceLabels({ boundary }) {
  const map = useMap()
  const [labels, setLabels] = useState([])
  const [view, setView] = useState(() => ({ bounds: map.getBounds(), zoom: map.getZoom() }))
  useMapEvents({ moveend: () => setView({ bounds: map.getBounds(), zoom: map.getZoom() }) })
  useEffect(() => {
    const controller = new AbortController()
    const timer = setTimeout(() => {
      const box = { south: view.bounds.getSouth(), west: view.bounds.getWest(), north: view.bounds.getNorth(), east: view.bounds.getEast() }
      placeNamesInView(box, view.zoom, setLabels, controller.signal).catch(() => {})
    }, 150)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [view])
  const placed = []
  // Only names inside India: the downloaded area is a rectangle that also covers neighbouring countries.
  const shown = labels.filter((label) => {
    if (!boundary || !insideBoundary(boundary, label.latitude, label.longitude)) return false
    const point = map.latLngToContainerPoint([label.latitude, label.longitude])
    if (placed.some((other) => Math.abs(other.x - point.x) < LABEL_BOX.width && Math.abs(other.y - point.y) < LABEL_BOX.height)) return false
    placed.push(point)
    return true
  })
  return shown.map((label) => <Marker key={`${label.name}-${label.latitude}-${label.longitude}`} position={[label.latitude, label.longitude]} interactive={false} keyboard={false}
    icon={L.divIcon({ className: '', html: `<span class="map-label ${label.kind}">${label.name.replace(/[&<>"']/g, '')}</span>`, iconSize: [0, 0], iconAnchor: [0, 0] })}/>)
}

// Google-style roads over the satellite imagery, drawn into canvas tiles (see lib/hybridRoads.js).
const RoadTiles = L.GridLayer.extend({
  createTile(coords, done) {
    const tile = document.createElement('canvas')
    const ratio = window.devicePixelRatio || 1
    tile.width = tile.height = 256 * ratio
    const context = tile.getContext('2d')
    context.scale(ratio, ratio)
    tile.loading = new AbortController() // aborted if the map moves on before the tile arrives
    drawRoadTile(context, coords, tile.loading.signal).catch(() => {}).finally(() => done(null, tile))
    return tile
  },
})

function HybridRoads({ maxZoom }) {
  const map = useMap()
  useEffect(() => {
    const layer = new RoadTiles({ maxZoom, zIndex: 4, className: 'hybrid-roads', ...TILE_OPTIONS })
    layer.on('tileunload', ({ tile }) => tile.loading?.abort()).addTo(map)
    return () => { layer.remove() }
  }, [map, maxZoom])
  return null
}

// The chosen detail layers over the base map: NASA imagery as WMS, the rest as tiles, air quality as labels.
function DetailLayers({ overlays, here, plan }) {
  return overlays.map((key) => {
    const layer = OVERLAYS[key]
    if (layer.kind === 'wms') {
      return <WMSTileLayer key={key} url={GIBS} opacity={layer.opacity} zIndex={5}
        params={{ layers: layer.layer, format: 'image/png', transparent: true, version: '1.3.0' }}/>
    }
    if (layer.kind === 'tiles') return <TileLayer key={key} url={layer.url} opacity={layer.opacity} zIndex={6}/>
    if (layer.kind === 'points') return <AirQualityLayer key={key} here={here} plan={plan}/>
    return null
  })
}

// Only reports with reviewer-confirmed coordinates are drawn; text mentions never become map points.
// navigating: only the followed route is drawn and the map follows the device instead of fitting the route.
// Road reports as Google Maps-style symbols by type. Reviewer-entered coordinates are exact. A report that names a
// town is drawn at that town with a dashed ring, because the spot on the road is unknown: one symbol per town and
// type (no counts), several types at one town side by side. Stale reports are faded.
const ICON_SIZE = 30
function IncidentMarkers({ incidents, selectedIncident, onSelectIncident }) {
  const typeOf = (item) => (INCIDENT_STYLES[item.event_type] ? item.event_type : 'other')
  const exact = incidents.filter((item) => item.latitude != null && item.longitude != null)
  const groups = new Map()
  for (const item of incidents) {
    const town = item.latitude == null && item.approximate_location
    if (!town || town.latitude == null) continue
    const key = `${town.place}|${typeOf(item)}`
    if (!groups.has(key)) groups.set(key, { key, type: typeOf(item), town, items: [] })
    groups.get(key).items.push(item)
  }
  const atTown = new Map()
  for (const group of groups.values()) atTown.set(group.town.place, [...(atTown.get(group.town.place) || []), group])
  const newest = (items) => [...items].sort((a, b) => (a.evidence_status === 'stale') - (b.evidence_status === 'stale')
    || String(b.collected_at || '').localeCompare(String(a.collected_at || '')))[0]
  return <>
    {exact.map((item) => <Marker key={item.id} position={[item.latitude, item.longitude]} zIndexOffset={selectedIncident?.id === item.id ? 600 : 400}
      eventHandlers={{ click: () => onSelectIncident(item.id) }}
      icon={L.divIcon({ className: '', html: incidentIconHtml(typeOf(item), { stale: item.evidence_status === 'stale', selected: selectedIncident?.id === item.id }), iconSize: [ICON_SIZE, ICON_SIZE], iconAnchor: [ICON_SIZE / 2, ICON_SIZE / 2] })}>
      <Tooltip>{incidentStyle(typeOf(item)).label} · {item.title} · {statusLabel(item)}</Tooltip></Marker>)}
    {[...atTown.values()].flatMap((list) => list.map((group, index) => {
      const shift = (index - (list.length - 1) / 2) * (ICON_SIZE + 6)
      const selected = group.items.some((item) => item.id === selectedIncident?.id)
      const lead = newest(group.items)
      const count = group.items.length
      return <Marker key={group.key} position={[group.town.latitude, group.town.longitude]} zIndexOffset={selected ? 500 : 300}
        eventHandlers={{ click: () => onSelectIncident(selected ? selectedIncident.id : lead.id) }}
        icon={L.divIcon({ className: '', html: incidentIconHtml(group.type, { approximate: true, stale: group.items.every((item) => item.evidence_status === 'stale'), selected }),
          iconSize: [ICON_SIZE, ICON_SIZE], iconAnchor: [ICON_SIZE / 2 - shift, ICON_SIZE / 2] })}>
        <Tooltip>{incidentStyle(group.type).label}: {count} report{count === 1 ? '' : 's'} placed at {group.town.place} · exact spot unknown<br/>{lead.title}</Tooltip></Marker>
    }))}
  </>
}

// navigation: { now, following, overview, onUserMove } while a route is followed (see NavigationLayer).
function DashboardMap({ plan, incidents, selectedRoute, selectedIncident, onSelectIncident, hiddenTypes, boundary, here, focusKey, base, overlays, navigation }) {
  const navigating = Boolean(navigation)
  const route = plan?.routes?.find((item) => item.id === selectedRoute) || plan?.routes?.[0]
  const startHere = !plan && inIndia(here)
  const center = plan?.origin ? [plan.origin.latitude, plan.origin.longitude] : startHere ? [here.latitude, here.longitude] : [26.2, 92.4]
  const shown = (item) => !INACTIVE_STATES.includes(item.verification) && !hiddenTypes.includes(mapCategory(item))
  return <MapContainer center={center} zoom={plan ? 7 : startHere ? HERE_ZOOM : 6} minZoom={4} maxBounds={INDIA_BOUNDS} maxBoundsViscosity={1} zoomControl={false} attributionControl={false} className="map-canvas">
    {boundary && <IndiaMask boundary={boundary}/>}
    {route && !navigating && <MapBounds geometry={route.geometry} />}
    <TileLayer key={base} url={BASE_LAYERS[base].url} maxZoom={BASE_LAYERS[base].maxZoom} {...(BASE_LAYERS[base].subdomains && { subdomains: BASE_LAYERS[base].subdomains })} {...TILE_OPTIONS}/>
    {BASE_LAYERS[base].roads && <HybridRoads key={`${base}-roads`} maxZoom={BASE_LAYERS[base].maxZoom}/>}
    {BASE_LAYERS[base].labels && <Pane name="place-labels" style={{ zIndex: 380, pointerEvents: 'none' }}><PlaceLabels boundary={boundary}/></Pane>}
    <DetailLayers overlays={overlays} here={here} plan={plan}/>
    <ZoomControl position="bottomright" />
    <ScaleControl position="bottomright" imperial={false}/>
    {!navigating && <HereLayer here={here} hasPlan={Boolean(plan)} focusKey={focusKey}/>}
    {navigating && route && <NavigationLayer line={route.geometry.coordinates} here={here} {...navigation}/>}
    {plan?.routes && [...plan.routes].filter(() => !navigating).sort((a, b) => (a.id === route?.id) - (b.id === route?.id)).map((item) => <Polyline key={item.id} positions={item.geometry.coordinates.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: item.id === route?.id ? '#0878e8' : '#64748b', opacity: item.id === route?.id ? 0.95 : 0.55, weight: item.id === route?.id ? 5 : 3, dashArray: item.id === route?.id ? undefined : '8 9' }} />)}
    {route?.tolls?.plazas?.map((plaza) => <Marker key={`toll-${plaza.code || plaza.name}`} position={[plaza.latitude, plaza.longitude]} keyboard={false}
      icon={L.divIcon({ className: '', html: `<span class="toll-marker">${TOLL_SVG}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] })}>
      <Tooltip>{plaza.name} toll plaza · {plaza.km_from_start} km from the start · price not available</Tooltip></Marker>)}
    {plan?.origin && !navigating && <CircleMarker center={[plan.origin.latitude, plan.origin.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#079352', fillOpacity: 1 }}><Tooltip>Origin · {plan.origin.name}</Tooltip></CircleMarker>}
    {plan?.destination && <CircleMarker center={[plan.destination.latitude, plan.destination.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#e44a58', fillOpacity: 1 }}><Tooltip>Destination · {plan.destination.name}</Tooltip></CircleMarker>}
    <IncidentMarkers incidents={incidents.filter(shown)} selectedIncident={selectedIncident} onSelectIncident={onSelectIncident}/>
  </MapContainer>
}

// The map alone filling the screen, with its controls and legend. Uses the browser's full screen where it has one
// (not iPhone Safari), otherwise a full-window view; Esc leaves either. The map is told to redraw at its new size.
function useFullscreen(element) {
  const [on, setOn] = useState(false)
  const native = typeof document !== 'undefined' && document.fullscreenEnabled
  useEffect(() => {
    const sync = () => setOn(Boolean(element.current) && document.fullscreenElement === element.current)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [element])
  useEffect(() => {
    window.dispatchEvent(new Event('resize'))
    if (!on || native) return undefined
    const leave = (event) => { if (event.key === 'Escape') setOn(false) }
    document.addEventListener('keydown', leave)
    return () => document.removeEventListener('keydown', leave)
  }, [on, native])
  const enter = useCallback(() => {
    if (!native) setOn(true)
    else if (!document.fullscreenElement) element.current?.requestFullscreen().catch(() => setOn(true))
  }, [element, native])
  const exit = useCallback(() => {
    if (native && document.fullscreenElement) document.exitFullscreen()
    setOn(false)
  }, [native])
  return { on, toggle: () => (on ? exit() : enter()), enter, exit }
}

// Mappls when the API has a Mappls key, OpenStreetMap otherwise. If Mappls cannot load (no internet, a rejected
// key) the map falls back to OpenStreetMap and says so, so the dashboard never loses its map.
// onStart begins navigation (null when the route cannot be followed); navigation is the followed route's state.
export default function RouteMap({ plan, mapConfig, here, hereProblem, onRetryHere, onSearch, searchStatus, onStart, startMode, navigation, ...mapProps }) {
  const [focusKey, setFocusKey] = useState(0)
  const layers = useMapLayers()
  const wrap = useRef(null)
  const hereText = !here ? (hereProblem ? `${hereProblem} Showing Northeast India.` : 'Finding your location…')
    : inIndia(here) ? `Your location · accurate to about ${Math.max(1, Math.round(here.accuracy || 0))} m` : 'Your location is outside India. Showing Northeast India.'
  const [mapplsProblem, setMapplsProblem] = useState('')
  const [boundary, setBoundary] = useState(null)
  useEffect(() => {
    let active = true
    // Without the file the map still works, with neighbouring countries visible.
    loadIndiaBoundary().then((rings) => { if (active) setBoundary(rings) }).catch(() => {})
    return () => { active = false }
  }, [])
  const onUnavailable = useCallback((reason) => setMapplsProblem(reason || 'The Mappls map could not load.'), [])
  const fullscreen = useFullscreen(wrap)
  // Navigation fills the screen, like a maps app, and gives the dashboard back when it ends.
  const navigating = Boolean(navigation)
  const { enter, exit } = fullscreen
  useEffect(() => {
    if (!navigating) return undefined
    enter()
    return exit
  }, [navigating, enter, exit])
  // Where the device is along the followed route, shared by the guidance panel and the map.
  const followed = navigation?.route
  const prepared = useMemo(() => (followed?.steps?.length ? prepareRoute(followed) : null), [followed])
  const previewing = navigation?.mode === 'preview'
  const now = navigating && !previewing && prepared && inIndia(here) ? progress(prepared, here) : null
  // Preview: which turn is shown; live: none. The arrow sits on the device (snapped to the route while on it) or,
  // in a preview, on the turn shown, pointing the way the route leaves it.
  const [previewStep, setPreviewStep] = useState(0)
  const shownStep = previewing && prepared ? prepared.steps[Math.min(previewStep, prepared.steps.length - 1)] : null
  const focus = shownStep ? { position: [shownStep.location[1], shownStep.location[0]], bearing: shownStep.bearing_after ?? 0 }
    : now && !now.offRoute ? { position: [now.snapped[1], now.snapped[0]], bearing: now.bearing }
      : inIndia(here) ? { position: [here.latitude, here.longitude], bearing: now?.bearing || 0 } : null
  // Following the arrow, or looking around (after a drag) or at the whole route (overview); reset at each start.
  const [view, setView] = useState({ following: true, overview: false })
  const [viewFor, setViewFor] = useState(navigating)
  if (viewFor !== navigating) {
    setViewFor(navigating)
    setView({ following: true, overview: false })
    setPreviewStep(0)
  }
  const onUserMove = useCallback(() => setView({ following: false, overview: false }), [])
  const recentre = () => setView({ following: true, overview: false })
  const toggleOverview = () => setView((current) => (current.overview ? { following: true, overview: false } : { following: false, overview: true }))
  const useMappls = mapConfig?.provider === 'mappls' && !mapplsProblem
  const credit = `${useMappls ? 'Map © Mappls (MapmyIndia)' : [BASE_LAYERS[layers.base].credit, ...layers.overlays.map((key) => OVERLAYS[key].credit)].join(' · ')} · India boundary: Survey of India`
  return <article className="panel map-panel" aria-label="Map">
    {mapplsProblem && <p className="map-fallback" role="status">{mapplsProblem} Showing OpenStreetMap instead.</p>}
    <div className={`map-wrap${fullscreen.on ? ' fullscreen' : ''}${navigating ? ' navigating' : ''}`} ref={wrap}>{!mapConfig ? <div className="map-canvas"/> : useMappls
      ? <MapplsMap apiKey={mapConfig.mappls_key} plan={plan} boundary={boundary} here={here} focusKey={focusKey} {...mapProps} onUnavailable={onUnavailable}/>
      : <DashboardMap plan={plan} boundary={boundary} here={here} focusKey={focusKey} base={layers.base} overlays={layers.overlays} navigation={navigating ? { now, focus, ...view, onUserMove } : null} {...mapProps}/>}
      {navigation ? <NavigationPanel {...navigation} prepared={prepared} now={now} here={here} following={view.following}
        previewStep={previewing ? Math.min(previewStep, (prepared?.steps.length || 1) - 1) : null}
        onPreviewStep={(index) => { setPreviewStep(index); setView({ following: true, overview: false }) }}
        onRecentre={recentre} overview={view.overview} onOverview={toggleOverview}/> : <MapSearch onSearch={onSearch} status={searchStatus}/>}
      {plan && onStart && !navigation && <button type="button" className="map-start" onClick={onStart}><Icon name={startMode === 'preview' ? 'route' : 'navigate'} size={18}/> {startMode === 'preview' ? 'Preview' : 'Start'}</button>}
      {mapConfig && <LayersPanel base={layers.base} overlays={layers.overlays} onBase={layers.setBase} onToggle={layers.toggleOverlay} mappls={useMappls}/>}
      <button type="button" className="locate-button" onClick={() => (here ? setFocusKey((key) => key + 1) : onRetryHere())} disabled={Boolean(here) && !inIndia(here)} aria-label="Show my location" title={inIndia(here) ? 'Show my location' : here ? hereText : `${hereText} Press to try again.`}><Icon name="locate" size={20}/></button>
      <button type="button" className="fullscreen-button" onClick={fullscreen.toggle} aria-pressed={fullscreen.on} aria-label={fullscreen.on ? 'Exit full screen' : 'Show the map full screen'} title={fullscreen.on ? 'Exit full screen (Esc)' : 'Full screen'}><Icon name={fullscreen.on ? 'fullscreen-exit' : 'fullscreen'} size={20}/></button>
      {fullscreen.on && <details className="map-credit"><summary aria-label="Map credits" title="Map credits">i</summary><small>{credit}</small></details>}{!navigation && <div className="map-legend"><span><i className="legend-route"/> Selected route</span><span><i className="legend-candidate"/> Other candidates</span><span><i className="legend-symbol" dangerouslySetInnerHTML={{ __html: incidentIconHtml('accident') }}/> Road reports</span><span><i className="legend-toll"/> Toll plaza</span><span><i className="legend-here"/> You</span></div>}</div>
    <div className="map-foot"><span><Icon name="pin" size={14}/>{plan ? `${placeName(plan.origin)} → ${placeName(plan.destination)}` : hereText}</span><span>{credit}</span></div>
  </article>
}

// Layer toggles for the map, with how many reports in each category can actually be placed.
export function MapLayers({ plan, incidents, hiddenTypes, onToggle }) {
  const locatedCount = (category) => incidents.filter((item) => (item.latitude != null || item.approximate_location) && mapCategory(item) === category).length
  return <article className="panel map-options"><div className="panel-heading compact"><div><span className="section-kicker">MAP CONTENT</span><h2>Show on map</h2></div></div>
    <label className="toggle-row"><span className="legend-swatch route-swatch"/>Routes<span className="toggle-note">{plan ? plan.routes.length : 0}</span></label>
    {MAP_CATEGORIES.map(([key, label]) => <label className="toggle-row" key={key}><span className="legend-symbol" dangerouslySetInnerHTML={{ __html: incidentIconHtml(key) }}/>{label}<span className="toggle-note">{locatedCount(key)} on map</span><input type="checkbox" checked={!hiddenTypes.includes(key)} onChange={(event) => onToggle(key, event.target.checked)}/><span className="switch" aria-hidden="true"/></label>)}
    <p className="map-hint">Reports with reviewer-confirmed coordinates are drawn where they are. A report that names a town is drawn at that town with a dashed ring: the spot on the road is unknown. Faded symbols are stale.</p>
  </article>
}
