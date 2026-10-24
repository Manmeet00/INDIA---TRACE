import { VectorTile } from '@mapbox/vector-tile'
import Pbf from 'pbf'

// OpenStreetMap data as small vector tiles from OpenFreeMap's CDN (free, no key). The satellite view reads two
// things from them: place names and roads. Their boundary lines are never read.
const TILEJSON = 'https://tiles.openfreemap.org/planet'
export const MAX_TILE_ZOOM = 14 // the deepest tiles OpenFreeMap serves; closer views draw from these
const KEEP = 400 // tiles kept in memory, most recently used, so panning back costs nothing

let template = null
const tiles = new Map() // "z/x/y" -> { tile: Promise of a VectorTile or null, controller, users, done }

function tileTemplate() {
  template ??= fetch(TILEJSON).then((response) => {
    if (!response.ok) throw new Error('OpenFreeMap is unavailable.')
    return response.json()
  }).then((tilejson) => tilejson.tiles[0]).catch((error) => {
    template = null
    throw error
  })
  return template
}

/**
 * The decoded tile z/x/y (z at most MAX_TILE_ZOOM); null when it cannot be loaded, so it is tried again later.
 * signal: aborted when the caller no longer needs the tile (the map moved on); once every caller has let go of a
 * tile still downloading, the download stops, so a quick zoom through several levels does not queue them all.
 */
export function vectorTile(z, x, y, signal) {
  const key = `${z}/${x}/${y}`
  let entry = tiles.get(key)
  if (entry) {
    tiles.delete(key) // re-insert: Map order is the recently-used order
  } else {
    const controller = new AbortController()
    entry = { controller, users: 0, done: false }
    entry.tile = tileTemplate()
      .then((url) => fetch(url.replace('{z}', z).replace('{x}', x).replace('{y}', y), { signal: controller.signal }))
      .then((response) => (response.ok ? response.arrayBuffer() : null))
      .then((buffer) => (buffer ? new VectorTile(new Pbf(buffer)) : null))
      .catch(() => null)
      .then((result) => {
        entry.done = true
        if (!result && tiles.get(key) === entry) tiles.delete(key)
        return result
      })
  }
  tiles.set(key, entry)
  if (tiles.size > KEEP) tiles.delete(tiles.keys().next().value)
  if (!entry.done) {
    entry.users += 1
    signal?.addEventListener('abort', () => {
      entry.users -= 1
      if (entry.users > 0 || entry.done) return
      entry.controller.abort()
      if (tiles.get(key) === entry) tiles.delete(key)
    }, { once: true })
  }
  return entry.tile
}

/** A feature's English name where the data has one. */
export function englishName(properties) {
  const name = properties['name:en'] || properties.name_en || properties.name_int || properties['name:latin'] || properties.name
  return typeof name === 'string' ? name : ''
}
