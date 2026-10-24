// Map types and map details for the OpenStreetMap view, each from a free source checked to cover Northeast India.
// credit: shown under the map (the map itself carries no attribution box).
// thumb: a real tile of the Guwahati area from the same source, saved with the frontend (public/map-thumbs) so the
// layers panel needs no outside request; OpenStreetMap refuses tile requests without a referrer.
const GIBS_WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi'

export const BASE_LAYERS = {
  default: {
    label: 'Default', url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', maxZoom: 19,
    credit: 'Map tiles © OpenStreetMap contributors', thumb: '/map-thumbs/default.png',
  },
  satellite: {
    label: 'Satellite', url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', maxZoom: 19,
    credit: 'Imagery © Esri, Maxar, Earthstar Geographics · Roads and place names © OpenStreetMap contributors via OpenFreeMap',
    thumb: '/map-thumbs/satellite.jpg',
    // Like Google's satellite view: roads, road names and highway numbers drawn over the imagery (HybridRoads),
    // and place names (PlaceLabels), all from OpenStreetMap. No third-party boundary lines are drawn: Esri's
    // boundaries-and-places layer draws disputed lines that differ from India's official boundary.
    roads: true,
    labels: true,
  },
  terrain: {
    label: 'Terrain', url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', maxZoom: 17,
    credit: 'Terrain © OpenTopoMap (CC-BY-SA), SRTM, OpenStreetMap contributors', thumb: '/map-thumbs/terrain.png',
  },
}

// kind: tiles (an XYZ overlay), wms (NASA GIBS imagery), points (air quality values), mappls (Mappls' own control).
export const OVERLAYS = {
  traffic: { label: 'Traffic', icon: 'traffic', kind: 'mappls', credit: 'Live traffic © Mappls' },
  rain: {
    label: 'Rainfall', icon: 'rain', kind: 'wms', layer: 'IMERG_Precipitation_Rate_30min', opacity: 0.7,
    credit: 'Rainfall: NASA IMERG via GIBS (latest half hour available, a few hours behind)',
  },
  fires: {
    label: 'Wildfires', icon: 'fire', kind: 'wms', layer: 'VIIRS_NOAA20_Thermal_Anomalies_375m_All', opacity: 1,
    credit: 'Fires: NASA VIIRS thermal anomalies via GIBS (today)',
  },
  rail: {
    label: 'Railways', icon: 'train', kind: 'tiles', url: 'https://{s}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png', opacity: 0.85,
    credit: 'Railways © OpenRailwayMap (CC-BY-SA)',
  },
  cycling: {
    label: 'Cycling', icon: 'bike', kind: 'tiles', url: 'https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm-lite/{z}/{x}/{y}.png', opacity: 1,
    credit: 'Cycling © CyclOSM, OpenStreetMap contributors',
  },
  air: { label: 'Air quality', icon: 'air', kind: 'points', credit: 'Air quality: Open-Meteo (CAMS)' },
}

export const GIBS = GIBS_WMS

// US AQI bands and their usual colours.
export function aqiTone(aqi) {
  return aqi <= 50 ? 'good' : aqi <= 100 ? 'moderate' : aqi <= 150 ? 'sensitive' : aqi <= 200 ? 'unhealthy' : aqi <= 300 ? 'very' : 'hazardous'
}
