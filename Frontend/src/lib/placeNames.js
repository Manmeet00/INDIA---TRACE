import { VectorTile } from '@mapbox/vector-tile'
import Pbf from 'pbf'

// Place names for the satellite view, India-wide, from OpenFreeMap: OpenStreetMap data served as small vector
// tiles from a CDN (free, no key). Only the tiles' "place" layer is read; their boundary lines are never used.
const TILEJSON = 'https://tiles.openfreemap.org/planet'
const MAX_TILE_ZOOM = 14
// Most important first; a name that would overlap a more important one is left out when drawn.
const CLASSES = ['state', 'city', 'town', 'suburb', 'village', 'quarter', 'neighbourhood', 'hamlet']

let template = null
const tiles = new Map() // "z/x/y" -> Promise of names, so a revisited area costs nothing

function tileTemplate() {
  template ??= fetch(TILEJSON).then((response) => {
    if (!response.ok) throw new Error('Place names are unavailable.')
    return response.json()
  }).then((tilejson) => tilejson.tiles[0]).catch((error) => {
    template = null
    throw error
  })
  return template
}

function tileNames(url, z, x, y) {
  const key = `${z}/${x}/${y}`
  if (!tiles.has(key)) {
    const names = fetch(url.replace('{z}', z).replace('{x}', x).replace('{y}', y))
      .then((response) => (response.ok ? response.arrayBuffer() : null))
      .then((buffer) => {
        const layer = buffer && new VectorTile(new Pbf(buffer)).layers.place
        if (!layer) return []
        const found = []
        for (let index = 0; index < layer.length; index += 1) {
          const feature = layer.feature(index)
          const { class: kind, rank } = feature.properties
          const name = feature.properties['name:en'] || feature.properties.name_en || feature.properties['name:latin'] || feature.properties.name
          if (!CLASSES.includes(kind) || typeof name !== 'string') continue
          const point = feature.toGeoJSON(x, y, z).geometry
          if (point.type !== 'Point') continue
          found.push({ name, kind, rank: rank ?? 99, longitude: point.coordinates[0], latitude: point.coordinates[1] })
        }
        return found
      })
      .catch(() => {
        tiles.delete(key) // try again next time
        return []
      })
    tiles.set(key, names)
  }
  return tiles.get(key)
}

const lon2x = (longitude, z) => Math.floor(((longitude + 180) / 360) * 2 ** z)
const lat2y = (latitude, z) => {
  const radians = (latitude * Math.PI) / 180
  return Math.floor(((1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2) * 2 ** z)
}

/** Names in a map view, most important first: { south, west, north, east } and the map's zoom. */
export async function placeNamesInView({ south, west, north, east }, zoom) {
  const url = await tileTemplate()
  const z = Math.max(0, Math.min(MAX_TILE_ZOOM, Math.floor(zoom)))
  const xs = [lon2x(west, z), lon2x(east, z)]
  const ys = [lat2y(north, z), lat2y(south, z)]
  const requests = []
  for (let x = xs[0]; x <= xs[1]; x += 1) for (let y = ys[0]; y <= ys[1]; y += 1) requests.push(tileNames(url, z, x, y))
  const seen = new Set()
  return (await Promise.all(requests)).flat()
    .filter((place) => place.latitude >= south && place.latitude <= north && place.longitude >= west && place.longitude <= east)
    .filter((place) => {
      const key = `${place.name}|${place.latitude.toFixed(3)}|${place.longitude.toFixed(3)}`
      return !seen.has(key) && seen.add(key)
    })
    .sort((a, b) => CLASSES.indexOf(a.kind) - CLASSES.indexOf(b.kind) || a.rank - b.rank)
}
