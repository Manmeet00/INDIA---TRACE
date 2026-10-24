import { MAX_TILE_ZOOM, englishName, vectorTile } from './vectorTiles.js'

// Roads over satellite imagery in the style of Google Maps' satellite view: thin, see-through white streets,
// pale arterials and yellow highways with a faint dark edge, white road names with a dark halo along the road,
// and national highway numbers in small boxes. Drawn from OpenStreetMap roads (OpenFreeMap vector tiles).

const TILE = 256
const FONT = 'Roboto, Arial, sans-serif'

// Bottom to top. width: [zoom, pixels] stops, interpolated; minZoom: when the class first appears.
const ROADS = [
  { classes: ['service'], minZoom: 15, color: 'rgba(255, 255, 255, .4)', width: [[15, 0.8], [18, 3]] },
  { classes: ['minor'], minZoom: 13, color: 'rgba(255, 255, 255, .55)', width: [[13, 0.7], [15, 1.6], [18, 5]] },
  { classes: ['tertiary'], minZoom: 11, color: 'rgba(255, 255, 255, .7)', width: [[11, 0.8], [14, 2], [18, 7]] },
  { classes: ['secondary'], minZoom: 10, color: 'rgba(255, 252, 232, .85)', width: [[9, 0.8], [13, 2.2], [18, 9]], casing: true },
  { classes: ['primary'], minZoom: 9, color: '#fff6cf', width: [[9, 0.8], [12, 2.4], [18, 10]], casing: true },
  { classes: ['trunk', 'motorway'], minZoom: 5, color: '#f9d161', width: [[5, 0.7], [8, 1.2], [10, 2.4], [14, 4], [18, 12]], casing: true },
]
const CASING = 'rgba(40, 30, 0, .45)'

// Road names: when each class is named. Highway numbers: when they are boxed.
const NAME_ZOOM = { motorway: 11, trunk: 11, primary: 12, secondary: 13, tertiary: 14, minor: 15, service: 17 }
const SHIELD_ZOOM = { motorway: 6, trunk: 6, primary: 10, secondary: 12 }

function interpolate(stops, zoom) {
  if (zoom <= stops[0][0]) return stops[0][1]
  for (let index = 1; index < stops.length; index += 1) {
    const [z1, w1] = stops[index]
    const [z0, w0] = stops[index - 1]
    if (zoom <= z1) return w0 + ((w1 - w0) * (zoom - z0)) / (z1 - z0)
  }
  return stops.at(-1)[1]
}

// The number shown for a highway: the national (or state) highway number, as Google shows it ("48", not "NH48").
function highwayNumber(properties) {
  for (let route = 1; route <= 6; route += 1) {
    const network = properties[`route_${route}_network`]
    if (network === 'IN:NH' || network === 'IN:SH') return String(properties[`route_${route}_ref`] || '')
  }
  const ref = typeof properties.ref === 'string' ? properties.ref.split(';')[0].trim() : ''
  return ref.replace(/^(NH|SH)[-\s]*/i, '')
}

// Clips a polyline to a box, keeping the pieces inside it (Liang-Barsky per segment).
function clip(points, [x0, y0, x1, y1]) {
  const pieces = []
  let current = []
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1]
    const b = points[index]
    const dx = b.x - a.x
    const dy = b.y - a.y
    let t0 = 0
    let t1 = 1
    const ok = [[-dx, a.x - x0], [dx, x1 - a.x], [-dy, a.y - y0], [dy, y1 - a.y]].every(([p, q]) => {
      if (p === 0) return q >= 0
      const r = q / p
      if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r } else { if (r < t0) return false; if (r < t1) t1 = r }
      return true
    })
    if (!ok) { if (current.length > 1) pieces.push(current); current = []; continue }
    const start = { x: a.x + t0 * dx, y: a.y + t0 * dy }
    const end = { x: a.x + t1 * dx, y: a.y + t1 * dy }
    if (!current.length || t0 > 0) { if (current.length > 1) pieces.push(current); current = [start] }
    current.push(end)
    if (t1 < 1) { pieces.push(current); current = [] }
  }
  if (current.length > 1) pieces.push(current)
  return pieces
}

function lengths(points) {
  const out = [0]
  for (let index = 1; index < points.length; index += 1) out.push(out[index - 1] + Math.hypot(points[index].x - points[index - 1].x, points[index].y - points[index - 1].y))
  return out
}

function pointAt(points, cumulative, distance) {
  let index = 1
  while (index < points.length - 1 && cumulative[index] < distance) index += 1
  const a = points[index - 1]
  const b = points[index]
  const span = cumulative[index] - cumulative[index - 1] || 1
  const t = Math.min(1, Math.max(0, (distance - cumulative[index - 1]) / span))
  return { x: a.x + t * (b.x - a.x), y: a.y + t * (b.y - a.y), angle: Math.atan2(b.y - a.y, b.x - a.x) }
}

const overlaps = (box, placed) => placed.some((other) => box.x0 < other.x1 && box.x1 > other.x0 && box.y0 < other.y1 && box.y1 > other.y0)

// A road name along its road, letter by letter, centred on the piece of road inside the tile.
function nameAlong(context, points, text, size, placed) {
  context.font = `500 ${size}px ${FONT}`
  const width = context.measureText(text).width
  let line = points
  if (line.at(-1).x < line[0].x) line = [...line].reverse() // read left to right, never upside down
  const cumulative = lengths(line)
  const total = cumulative.at(-1)
  if (total < width + 30) return false
  const start = (total - width) / 2
  const letters = []
  let offset = 0
  for (const letter of text) {
    const advance = context.measureText(letter).width
    letters.push({ letter, ...pointAt(line, cumulative, start + offset + advance / 2) })
    offset += advance
  }
  // Too sharp a bend makes the name unreadable; a busy spot is left to the names already there.
  for (let index = 1; index < letters.length; index += 1) {
    let turn = Math.abs(letters[index].angle - letters[index - 1].angle)
    if (turn > Math.PI) turn = 2 * Math.PI - turn
    if (turn > 0.5) return false
  }
  const boxes = letters.map(({ x, y }) => ({ x0: x - size * 0.6, x1: x + size * 0.6, y0: y - size * 0.6, y1: y + size * 0.6 }))
  if (boxes.some((box) => overlaps(box, placed))) return false
  placed.push(...boxes)
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  context.lineJoin = 'round'
  for (const pass of ['halo', 'text']) {
    for (const { letter, x, y, angle } of letters) {
      context.save()
      context.translate(x, y)
      context.rotate(angle)
      if (pass === 'halo') {
        context.strokeStyle = 'rgba(0, 0, 0, .75)'
        context.lineWidth = 3
        context.strokeText(letter, 0, 0)
      } else {
        context.fillStyle = '#fff'
        context.fillText(letter, 0, 0)
      }
      context.restore()
    }
  }
  return true
}

// A highway number in a small box, a quarter of the way along, leaving the middle for the road's name.
function shield(context, points, number, placed) {
  context.font = `600 10px ${FONT}`
  const width = Math.max(18, context.measureText(number).width + 8)
  const cumulative = lengths(points)
  const total = cumulative.at(-1)
  if (total < width + 20) return false
  const { x, y } = pointAt(points, cumulative, total > 4 * width ? total / 4 : total / 2)
  const box = { x0: x - width / 2 - 2, x1: x + width / 2 + 2, y0: y - 9, y1: y + 9 }
  if (overlaps(box, placed)) return false
  placed.push(box)
  context.beginPath()
  context.roundRect(x - width / 2, y - 7.5, width, 15, 3)
  context.fillStyle = '#fff'
  context.fill()
  context.lineWidth = 1
  context.strokeStyle = 'rgba(0, 0, 0, .45)'
  context.stroke()
  context.fillStyle = '#3c3c3c'
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  context.fillText(number, x, y + 0.5)
  return true
}

/**
 * Draws the roads of map tile {x, y, z} onto a 256-pixel canvas context. Views closer than the deepest
 * OpenFreeMap tiles draw the matching part of a deeper tile, enlarged, so lines stay sharp.
 */
export async function drawRoadTile(context, { x, y, z }, signal) {
  const sourceZ = Math.min(z, MAX_TILE_ZOOM)
  const factor = 2 ** (z - sourceZ)
  const tile = await vectorTile(sourceZ, Math.floor(x / factor), Math.floor(y / factor), signal)
  if (!tile) return
  const shiftX = (x % factor) * TILE
  const shiftY = (y % factor) * TILE
  const project = (layer) => (point) => ({ x: (point.x / layer.extent) * TILE * factor - shiftX, y: (point.y / layer.extent) * TILE * factor - shiftY })

  const roads = tile.layers.transportation
  if (roads) {
    const byClass = new Map(ROADS.map((style) => [style, []]))
    for (let index = 0; index < roads.length; index += 1) {
      const feature = roads.feature(index)
      const style = ROADS.find((item) => item.classes.includes(feature.properties.class))
      if (!style || z < style.minZoom || feature.type !== 2) continue
      const lines = feature.loadGeometry().map((line) => line.map(project(roads)))
      byClass.get(style).push({ lines, tunnel: feature.properties.brunnel === 'tunnel', ramp: Number(feature.properties.ramp) === 1 })
    }
    context.lineCap = 'round'
    context.lineJoin = 'round'
    const stroke = (items, style, extra, color) => {
      const width = interpolate(style.width, z)
      for (const item of items) {
        context.globalAlpha = item.tunnel ? 0.45 : 1
        context.lineWidth = (item.ramp ? width * 0.6 : width) + extra
        context.strokeStyle = color
        context.beginPath()
        for (const line of item.lines) {
          context.moveTo(line[0].x, line[0].y)
          for (let point = 1; point < line.length; point += 1) context.lineTo(line[point].x, line[point].y)
        }
        context.stroke()
      }
      context.globalAlpha = 1
    }
    for (const [style, items] of byClass) if (style.casing) stroke(items, style, 1.4, CASING)
    for (const [style, items] of byClass) stroke(items, style, 0, style.color)
  }

  const names = tile.layers.transportation_name
  if (!names) return
  const placed = []
  const named = new Set()
  const inside = [6, 6, TILE - 6, TILE - 6] // labels stay whole inside their tile
  const features = []
  for (let index = 0; index < names.length; index += 1) {
    const feature = names.feature(index)
    if (feature.type !== 2 || feature.properties.subclass === 'junction') continue
    features.push(feature)
  }
  // Highways first, so their numbers and names win a crowded spot.
  const order = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'minor', 'service']
  features.sort((a, b) => order.indexOf(a.properties.class) - order.indexOf(b.properties.class))
  for (const feature of features) {
    const kind = feature.properties.class
    if (!order.includes(kind)) continue
    const pieces = feature.loadGeometry().flatMap((line) => clip(line.map(project(names)), inside))
    if (!pieces.length) continue
    const longest = pieces.reduce((best, piece) => (lengths(piece).at(-1) > lengths(best).at(-1) ? piece : best))
    const number = highwayNumber(feature.properties)
    // Only real numbers are boxed: "48", "148NA", "NE-2", not a bare "MDR" or "NEX".
    if (/\d/.test(number) && z >= (SHIELD_ZOOM[kind] ?? 99) && number.length <= 6) shield(context, longest, number, placed)
    const name = englishName(feature.properties)
    if (name && !/^\d+$/.test(name) && z >= NAME_ZOOM[kind] && !named.has(name) && nameAlong(context, longest, name, kind === 'minor' || kind === 'service' ? 10.5 : 11.5, placed)) named.add(name)
  }
}
