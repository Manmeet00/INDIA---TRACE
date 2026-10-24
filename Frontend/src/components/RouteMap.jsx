import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { Circle, CircleMarker, MapContainer, Marker, Pane, Polygon, Polyline, ScaleControl, TileLayer, Tooltip, WMSTileLayer, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import Icon from './Icon.jsx'
import LayersPanel from './LayersPanel.jsx'
import MapplsMap from './MapplsMap.jsx'
import { useMapLayers } from '../hooks/useMapLayers.js'
import { BASE_LAYERS, GIBS, OVERLAYS, aqiTone } from '../lib/mapLayers.js'
import { INACTIVE_STATES, MAP_CATEGORIES, formatTime, mapCategory, placeName, statusLabel } from '../lib/format.js'
import { BORDER_COLOR, HERE_COLOR, HERE_ZOOM, INDIA_BOUNDS, MASK_COLOR, inIndia, insideBoundary } from '../lib/mapStyle.js'
import { placeNamesInView } from '../lib/placeNames.js'
import { getAirQuality, loadIndiaBoundary } from '../services/api.js'

const WORLD = [[-89, -180], [-89, 180], [89, 180], [89, -180]]

function MapBounds({ geometry }) {
  const map = useMap()
  useEffect(() => {
    const points = geometry.coordinates.map(([longitude, latitude]) => [latitude, longitude])
    // No animation: planning again remounts the map, and removing it mid-zoom throws in Leaflet (_leaflet_pos).
    if (points.length > 1) map.fitBounds(points, { padding: [36, 36], maxZoom: 10, animate: false })
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
    let active = true
    const timer = setTimeout(() => {
      const box = { south: view.bounds.getSouth(), west: view.bounds.getWest(), north: view.bounds.getNorth(), east: view.bounds.getEast() }
      placeNamesInView(box, view.zoom).then((names) => { if (active) setLabels(names) }).catch(() => { if (active) setLabels([]) })
    }, 150)
    return () => {
      active = false
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
function DashboardMap({ plan, incidents, selectedRoute, selectedIncident, onSelectIncident, hiddenTypes, boundary, here, focusKey, base, overlays }) {
  const route = plan?.routes?.find((item) => item.id === selectedRoute) || plan?.routes?.[0]
  const startHere = !plan && inIndia(here)
  const center = plan?.origin ? [plan.origin.latitude, plan.origin.longitude] : startHere ? [here.latitude, here.longitude] : [26.2, 92.4]
  const shown = (item) => !INACTIVE_STATES.includes(item.verification) && !hiddenTypes.includes(mapCategory(item))
  return <MapContainer key={`${plan?.origin?.latitude || 'default'}-${plan?.destination?.latitude || 'default'}`} center={center} zoom={plan ? 7 : startHere ? HERE_ZOOM : 6} minZoom={4} maxBounds={INDIA_BOUNDS} maxBoundsViscosity={1} zoomControl={false} attributionControl={false} className="map-canvas">
    {boundary && <IndiaMask boundary={boundary}/>}
    {route && <MapBounds geometry={route.geometry} />}
    <TileLayer key={base} url={BASE_LAYERS[base].url} maxZoom={BASE_LAYERS[base].maxZoom} {...TILE_OPTIONS}/>
    {BASE_LAYERS[base].roads && <TileLayer key={`${base}-roads`} url={BASE_LAYERS[base].roads} maxZoom={BASE_LAYERS[base].maxZoom} zIndex={4} opacity={0.9} className="hybrid-roads" {...TILE_OPTIONS}/>}
    {BASE_LAYERS[base].labels && <Pane name="place-labels" style={{ zIndex: 380, pointerEvents: 'none' }}><PlaceLabels boundary={boundary}/></Pane>}
    <DetailLayers overlays={overlays} here={here} plan={plan}/>
    <ZoomControl position="bottomright" />
    <ScaleControl position="bottomright" imperial={false}/>
    <HereLayer here={here} hasPlan={Boolean(plan)} focusKey={focusKey}/>
    {plan?.routes && [...plan.routes].sort((a, b) => (a.id === route?.id) - (b.id === route?.id)).map((item) => <Polyline key={item.id} positions={item.geometry.coordinates.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: item.id === route?.id ? '#0878e8' : '#64748b', opacity: item.id === route?.id ? 0.95 : 0.55, weight: item.id === route?.id ? 5 : 3, dashArray: item.id === route?.id ? undefined : '8 9' }} />)}
    {plan?.origin && <CircleMarker center={[plan.origin.latitude, plan.origin.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#079352', fillOpacity: 1 }}><Tooltip>Origin · {plan.origin.name}</Tooltip></CircleMarker>}
    {plan?.destination && <CircleMarker center={[plan.destination.latitude, plan.destination.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#e44a58', fillOpacity: 1 }}><Tooltip>Destination · {plan.destination.name}</Tooltip></CircleMarker>}
    {incidents.filter((item) => shown(item) && item.latitude != null && item.longitude != null).map((item) => <CircleMarker key={item.id} center={[item.latitude, item.longitude]} radius={selectedIncident?.id === item.id ? 9 : 7} eventHandlers={{ click: () => onSelectIncident(item.id) }} pathOptions={{ color: '#fff', weight: 2, fillColor: item.evidence_status === 'confirmed' ? '#df3946' : item.evidence_status === 'stale' ? '#9ba8b8' : '#e99b28', fillOpacity: 0.95 }}><Tooltip>{item.title} · {statusLabel(item)}</Tooltip></CircleMarker>)}
  </MapContainer>
}

// Mappls when the API has a Mappls key, OpenStreetMap otherwise. If Mappls cannot load (no internet, a rejected
// key) the map falls back to OpenStreetMap and says so, so the dashboard never loses its map.
export default function RouteMap({ plan, mapConfig, here, hereProblem, ...mapProps }) {
  const [focusKey, setFocusKey] = useState(0)
  const layers = useMapLayers()
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
  const useMappls = mapConfig?.provider === 'mappls' && !mapplsProblem
  const status = plan?.offline_demo ? 'Historical snapshot' : plan ? `Routing fetched ${formatTime(plan.routing_fetched_at)}` : 'Map ready'
  return <article className="panel map-panel"><div className="map-heading"><div><span className="section-kicker">NORTHEAST INDIA · NETWORK VIEW</span><h2>{plan ? `${placeName(plan.origin)} to ${placeName(plan.destination)}` : 'Regional road intelligence'}</h2></div><span className={`map-status ${plan?.offline_demo ? 'demo' : ''}`}><i/>{status}</span></div>
    {mapplsProblem && <p className="map-fallback" role="status">{mapplsProblem} Showing OpenStreetMap instead.</p>}
    <div className="map-wrap">{!mapConfig ? <div className="map-canvas"/> : useMappls
      ? <MapplsMap apiKey={mapConfig.mappls_key} plan={plan} boundary={boundary} here={here} focusKey={focusKey} {...mapProps} onUnavailable={onUnavailable}/>
      : <DashboardMap plan={plan} boundary={boundary} here={here} focusKey={focusKey} base={layers.base} overlays={layers.overlays} {...mapProps}/>}
      {mapConfig && <LayersPanel base={layers.base} overlays={layers.overlays} onBase={layers.setBase} onToggle={layers.toggleOverlay} mappls={useMappls}/>}
      <button type="button" className="locate-button" onClick={() => setFocusKey((key) => key + 1)} disabled={!inIndia(here)} aria-label="Show my location" title={inIndia(here) ? 'Show my location' : hereText}><Icon name="locate" size={20}/></button><div className="map-legend"><span><i className="legend-route"/> Selected route</span><span><i className="legend-candidate"/> Other candidates</span><span><i className="legend-incident"/> Geolocated evidence</span><span><i className="legend-here"/> You</span></div></div>
    <div className="map-foot"><span><Icon name="pin" size={14}/>{plan ? `${placeName(plan.origin)} → ${placeName(plan.destination)}` : hereText}</span><span>{useMappls ? 'Map © Mappls (MapmyIndia)' : [BASE_LAYERS[layers.base].credit, ...layers.overlays.map((key) => OVERLAYS[key].credit)].join(' · ')} · India boundary: Survey of India</span></div>
  </article>
}

// Layer toggles for the map, with how many reports in each category can actually be placed.
export function MapLayers({ plan, incidents, hiddenTypes, onToggle }) {
  const locatedCount = (category) => incidents.filter((item) => item.latitude != null && mapCategory(item) === category).length
  return <article className="panel map-options"><div className="panel-heading compact"><div><span className="section-kicker">MAP CONTENT</span><h2>Show on map</h2></div></div>
    <label className="toggle-row"><span className="legend-swatch route-swatch"/>Routes<span className="toggle-note">{plan ? plan.routes.length : 0}</span></label>
    {MAP_CATEGORIES.map(([key, label]) => <label className="toggle-row" key={key}><span className="legend-swatch evidence-swatch"/>{label}<span className="toggle-note">{locatedCount(key)} on map</span><input type="checkbox" checked={!hiddenTypes.includes(key)} onChange={(event) => onToggle(key, event.target.checked)}/><span className="switch" aria-hidden="true"/></label>)}
    <p className="map-hint">Only reports with reviewer-confirmed coordinates are drawn. Reports that name a town are matched to routes by that town, without a map marker.</p>
  </article>
}
