import { MAX_TILE_ZOOM, englishName, vectorTile } from './vectorTiles.js'

// Place names for the satellite view, India-wide, from the "place" layer of OpenFreeMap's tiles.
// Most important first; a name that would overlap a more important one is left out when drawn.
const CLASSES = ['state', 'city', 'town', 'suburb', 'village', 'quarter', 'neighbourhood', 'hamlet']

async function tileNames(z, x, y, signal) {
  const layer = (await vectorTile(z, x, y, signal))?.layers.place
  if (!layer) return []
  const found = []
  for (let index = 0; index < layer.length; index += 1) {
    const feature = layer.feature(index)
    const { class: kind, rank } = feature.properties
    const name = englishName(feature.properties)
    if (!CLASSES.includes(kind) || !name) continue
    const point = feature.toGeoJSON(x, y, z).geometry
    if (point.type !== 'Point') continue
    found.push({ name, kind, rank: rank ?? 99, longitude: point.coordinates[0], latitude: point.coordinates[1] })
  }
  return found
}

const lon2x = (longitude, z) => Math.floor(((longitude + 180) / 360) * 2 ** z)
const lat2y = (latitude, z) => {
  const radians = (latitude * Math.PI) / 180
  return Math.floor(((1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2) * 2 ** z)
}

/**
 * Names in a map view, most important first: { south, west, north, east } and the map's zoom. onNames is called
 * again as each tile arrives, so the nearest names show without waiting for the slowest tile.
 */
export async function placeNamesInView({ south, west, north, east }, zoom, onNames, signal) {
  const z = Math.max(0, Math.min(MAX_TILE_ZOOM, Math.floor(zoom)))
  const xs = [lon2x(west, z), lon2x(east, z)]
  const ys = [lat2y(north, z), lat2y(south, z)]
  const found = []
  const requests = []
  for (let x = xs[0]; x <= xs[1]; x += 1) {
    for (let y = ys[0]; y <= ys[1]; y += 1) {
      requests.push(tileNames(z, x, y, signal).then((names) => {
        found.push(...names)
        if (!signal?.aborted) onNames(ordered(found, { south, west, north, east }))
      }))
    }
  }
  await Promise.all(requests)
}

function ordered(names, { south, west, north, east }) {
  const seen = new Set()
  return names
    .filter((place) => place.latitude >= south && place.latitude <= north && place.longitude >= west && place.longitude <= east)
    .filter((place) => {
      const key = `${place.name}|${place.latitude.toFixed(3)}|${place.longitude.toFixed(3)}`
      return !seen.has(key) && seen.add(key)
    })
    .sort((a, b) => CLASSES.indexOf(a.kind) - CLASSES.indexOf(b.kind) || a.rank - b.rank)
}
