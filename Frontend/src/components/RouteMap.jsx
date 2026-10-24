import { useEffect } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, ZoomControl, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import Icon from './Icon.jsx'
import { INACTIVE_STATES, MAP_CATEGORIES, formatTime, mapCategory, placeName, statusLabel } from '../lib/format.js'

function MapBounds({ geometry }) {
  const map = useMap()
  useEffect(() => {
    const points = geometry.coordinates.map(([longitude, latitude]) => [latitude, longitude])
    // No animation: planning again remounts the map, and removing it mid-zoom throws in Leaflet (_leaflet_pos).
    if (points.length > 1) map.fitBounds(points, { padding: [36, 36], maxZoom: 10, animate: false })
  }, [geometry, map])
  return null
}

// Only reports with reviewer-confirmed coordinates are drawn; text mentions never become map points.
function DashboardMap({ plan, incidents, selectedRoute, selectedIncident, onSelectIncident, hiddenTypes }) {
  const route = plan?.routes?.find((item) => item.id === selectedRoute) || plan?.routes?.[0]
  const center = plan?.origin ? [plan.origin.latitude, plan.origin.longitude] : [26.2, 92.4]
  return <MapContainer key={`${plan?.origin?.latitude || 'default'}-${plan?.destination?.latitude || 'default'}`} center={center} zoom={plan ? 7 : 6} zoomControl={false} className="map-canvas">
    {route && <MapBounds geometry={route.geometry} />}
    <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    <ZoomControl position="bottomright" />
    {plan?.routes && [...plan.routes].sort((a, b) => (a.id === route?.id) - (b.id === route?.id)).map((item) => <Polyline key={item.id} positions={item.geometry.coordinates.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: item.id === route?.id ? '#0878e8' : '#64748b', opacity: item.id === route?.id ? 0.95 : 0.55, weight: item.id === route?.id ? 5 : 3, dashArray: item.id === route?.id ? undefined : '8 9' }} />)}
    {plan?.origin && <CircleMarker center={[plan.origin.latitude, plan.origin.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#079352', fillOpacity: 1 }}><Tooltip>Origin · {plan.origin.name}</Tooltip></CircleMarker>}
    {plan?.destination && <CircleMarker center={[plan.destination.latitude, plan.destination.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#e44a58', fillOpacity: 1 }}><Tooltip>Destination · {plan.destination.name}</Tooltip></CircleMarker>}
    {incidents.filter((item) => !INACTIVE_STATES.includes(item.verification) && !hiddenTypes.includes(mapCategory(item)) && item.latitude != null && item.longitude != null).map((item) => <CircleMarker key={item.id} center={[item.latitude, item.longitude]} radius={selectedIncident?.id === item.id ? 9 : 7} eventHandlers={{ click: () => onSelectIncident(item.id) }} pathOptions={{ color: '#fff', weight: 2, fillColor: item.evidence_status === 'confirmed' ? '#df3946' : item.evidence_status === 'stale' ? '#9ba8b8' : '#e99b28', fillOpacity: 0.95 }}><Tooltip>{item.title} · {statusLabel(item)}</Tooltip></CircleMarker>)}
  </MapContainer>
}

export default function RouteMap({ plan, ...mapProps }) {
  return <article className="panel map-panel"><div className="map-heading"><div><span className="section-kicker">NORTHEAST INDIA · NETWORK VIEW</span><h2>{plan ? `${placeName(plan.origin)} to ${placeName(plan.destination)}` : 'Regional road intelligence'}</h2></div><span className={`map-status ${plan?.offline_demo ? 'demo' : ''}`}><i/>{plan?.offline_demo ? 'Historical snapshot' : plan ? `Routing fetched ${formatTime(plan.routing_fetched_at)}` : 'Map ready'}</span></div>
    <div className="map-wrap"><DashboardMap plan={plan} {...mapProps}/>{!plan && <div className="map-empty"><span className="map-empty-icon"><Icon name="route" size={22}/></span><b>Your route will appear here</b><span>Enter locations to compare candidate driving routes.</span></div>}<div className="map-legend"><span><i className="legend-route"/> Selected route</span><span><i className="legend-candidate"/> Other candidates</span><span><i className="legend-incident"/> Geolocated evidence</span></div></div>
    <div className="map-foot"><span><Icon name="pin" size={14}/>{plan ? `${placeName(plan.origin)} → ${placeName(plan.destination)}` : 'Assam · Meghalaya · Northeast India'}</span><span>Map tiles © OpenStreetMap contributors</span></div>
  </article>
}

// Layer toggles for the map, with how many reports in each category can actually be placed.
export function MapLayers({ plan, incidents, hiddenTypes, onToggle }) {
  const locatedCount = (category) => incidents.filter((item) => item.latitude != null && mapCategory(item) === category).length
  return <article className="panel map-options"><div className="panel-heading compact"><div><span className="section-kicker">MAP CONTENT</span><h2>Show on map</h2></div></div>
    <label className="toggle-row"><span className="legend-swatch route-swatch"/>Routes<span className="toggle-note">{plan ? plan.routes.length : 0}</span></label>
    {MAP_CATEGORIES.map(([key, label]) => <label className="toggle-row" key={key}><span className="legend-swatch evidence-swatch"/>{label}<span className="toggle-note">{locatedCount(key)} on map</span><input type="checkbox" checked={!hiddenTypes.includes(key)} onChange={(event) => onToggle(key, event.target.checked)}/><span className="switch" aria-hidden="true"/></label>)}
    <p className="map-hint">Reports without reviewer-confirmed coordinates cannot be placed on the map.</p>
  </article>
}
