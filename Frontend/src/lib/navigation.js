// Turn-by-turn navigation along a planned route: the words for each OSRM step, and where the device is along
// the route (how far to the next turn, how much is left, whether it has left the route).

export const OFF_ROUTE_M = 80 // further than this from the route line (beyond the GPS accuracy) is off the route
export const ARRIVED_M = 40

const COMPASS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']
const ORDINAL = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth']

export function road(step) {
  const ref = step.ref ? step.ref.split(';')[0].trim() : ''
  if (step.name && ref && !step.name.includes(ref)) return `${step.name} (${ref})`
  return step.name || ref
}

/** What to do at a step, in the words of a maps app ("Turn left onto GS Road (NH6)"). Google's routes carry
 * their own words, which are used as they are. */
export function instruction(step) {
  if (step.instruction) return step.instruction
  const onto = road(step) ? ` onto ${road(step)}` : ''
  const way = step.modifier && step.modifier !== 'straight' ? step.modifier : ''
  switch (step.type) {
    case 'depart': {
      const heading = step.bearing_after == null ? '' : ` ${COMPASS[Math.round(step.bearing_after / 45) % 8]}`
      return `Head${heading}${road(step) ? ` on ${road(step)}` : ''}`
    }
    case 'arrive': return 'Arrive at your destination'
    case 'turn': return way === 'uturn' ? `Make a U-turn${onto}` : way ? `Turn ${way}${onto}` : `Continue straight${onto}`
    case 'end of road': return `At the end of the road, turn ${way || 'onto the road'}${way ? onto : ''}`.trim()
    case 'fork': return `Keep ${way || 'straight'} at the fork${onto}`
    case 'merge': return `Merge${way ? ` ${way}` : ''}${onto}`
    case 'on ramp': return `Take the ramp${way ? ` on the ${way.replace('slight ', '')}` : ''}${onto}`
    case 'off ramp': return `Take the exit${way ? ` on the ${way.replace('slight ', '')}` : ''}${onto}`
    case 'roundabout':
    case 'rotary':
      return step.exit ? `At the roundabout, take the ${ORDINAL[step.exit - 1] || `${step.exit}th`} exit${onto}` : `Enter the roundabout${onto}`
    case 'exit roundabout':
    case 'exit rotary': return `Exit the roundabout${onto}`
    default: return way ? `Continue ${way}${onto}` : `Continue${onto || ' on the road'}`
  }
}

/** A step as Google Maps shows it: the road in large type, the action ("Turn left") above it. */
export function instructionParts(step) {
  if (step.instruction) {
    const at = step.name ? step.instruction.indexOf(step.name) : -1
    if (at <= 0) return { headline: step.instruction, action: '' }
    return { headline: step.name, action: step.instruction.slice(0, at).replace(/\s+(onto|on|to stay on)\s*$/i, '').trim() }
  }
  const name = road(step)
  if (!name || step.type === 'arrive') return { headline: instruction(step), action: '' }
  return { headline: name, action: instruction({ ...step, name: '', ref: '' }).replace(/ on the road$/, '') }
}

/** What the voice says: "In 400 metres, turn left onto GS Road", or just the instruction when it is close. */
export function spoken(step, metres) {
  const words = instruction(step).replace(/\((NH|SH|NE)[-\s]?(\w+)\)/g, '($1 $2)')
  if (metres == null || metres < 150) return words
  const distance = metres < 1000 ? `${Math.round(metres / 50) * 50} metres` : `${(metres / 1000).toFixed(metres < 10000 ? 1 : 0)} kilometres`
  return `In ${distance}, ${words.charAt(0).toLowerCase()}${words.slice(1)}`
}

/** The arrow for a step: left, right, slight-left, uturn, straight, roundabout or arrive. */
export function turnIcon(step) {
  if (!step) return 'straight'
  if (step.type === 'arrive') return 'arrive'
  if (step.type === 'roundabout' || step.type === 'rotary') return 'roundabout'
  const way = step.modifier || 'straight'
  if (way === 'uturn') return 'uturn'
  return way.includes('left') ? (way.startsWith('slight') ? 'slight-left' : 'left') : way.includes('right') ? (way.startsWith('slight') ? 'slight-right' : 'right') : 'straight'
}

// Metres between two [longitude, latitude] points, flat-earth: fine over the few hundred metres compared here.
export function metres([lon1, lat1], [lon2, lat2]) {
  const x = (lon2 - lon1) * 111320 * Math.cos(((lat1 + lat2) / 2) * (Math.PI / 180))
  const y = (lat2 - lat1) * 110540
  return Math.hypot(x, y)
}

/**
 * Prepares a route for following: the cumulative distance at each line point and at each step, so every
 * position update is one pass over the line.
 */
export function prepareRoute(route) {
  const line = route.geometry.coordinates
  const along = [0]
  for (let index = 1; index < line.length; index += 1) along.push(along[index - 1] + metres(line[index - 1], line[index]))
  const scale = along.at(-1) ? route.distance_m / along.at(-1) : 1 // OSRM's distances, measured along our line
  let total = 0
  const stepsAt = route.steps.map((step) => {
    const at = total
    total += step.distance_m
    return at
  })
  return { line, along: along.map((value) => value * scale), steps: route.steps, stepsAt, distance: route.distance_m, duration: route.duration_s }
}

// Metres of gap that one metre of jump along the route is worth when matching a position: on a hairpin road a later
// stretch can lie within GPS noise of the one being driven, and it should not win just by being a few metres closer.
// Only a jump longer than the vehicle could have driven since the last position (at up to 40 m/s) costs anything.
const JUMP_COST = 0.05
const MAX_SPEED_MPS = 40
const REACH_WITHOUT_TIME_M = 200

/**
 * Where a position is on a prepared route: { travelled, remaining, offRoute (metres from the line), step (the
 * next maneuver's index), toStep (metres to it), arrived }. previous is the last result on this route, if any:
 * the match then prefers to continue from it.
 */
export function progress(prepared, { latitude, longitude, accuracy = 0, at = null }, previous = null) {
  const point = [longitude, latitude]
  const seconds = previous?.at != null && at != null ? Math.max(0, (at - previous.at) / 1000) : null
  const reach = seconds == null ? REACH_WITHOUT_TIME_M : MAX_SPEED_MPS * seconds + 50
  let nearest = { gap: Infinity, travelled: 0, segment: 1, point: [longitude, latitude] }
  let likely = nearest
  let likelyScore = Infinity
  const { line, along } = prepared
  for (let index = 1; index < line.length; index += 1) {
    const a = line[index - 1]
    const b = line[index]
    const length = metres(a, b)
    // The closest point on this segment, as a fraction of it.
    const t = length ? Math.max(0, Math.min(1, ((point[0] - a[0]) * (b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180) ** 2 + (point[1] - a[1]) * (b[1] - a[1]))
      / ((b[0] - a[0]) ** 2 * Math.cos((a[1] * Math.PI) / 180) ** 2 + (b[1] - a[1]) ** 2))) : 0
    const closest = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
    const gap = metres(point, closest)
    const travelled = along[index - 1] + t * (along[index] - along[index - 1])
    const candidate = { gap, travelled, segment: index, point: closest }
    if (gap < nearest.gap) nearest = candidate
    const score = gap + (previous ? JUMP_COST * Math.max(0, Math.abs(travelled - previous.travelled) - reach) : 0)
    if (score < likelyScore) { likely = candidate; likelyScore = score }
  }
  // Continuing from the last position wins unless it is off the route while another stretch is on it.
  const tolerance = Math.max(OFF_ROUTE_M, accuracy)
  const best = likely.gap > tolerance && nearest.gap <= tolerance ? nearest : likely
  const remaining = Math.max(0, prepared.distance - best.travelled)
  let step = prepared.stepsAt.findIndex((at) => at > best.travelled + 5)
  if (step === -1) step = prepared.steps.length - 1
  const [a, b] = [line[best.segment - 1], line[best.segment]]
  const bearing = (Math.atan2((b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180), b[1] - a[1]) * 180) / Math.PI
  return {
    at, // when the position was taken, so the next match knows how far the vehicle could have gone
    travelled: best.travelled,
    segment: best.segment, // the route line continues from this point index
    snapped: best.point, // [longitude, latitude] on the route, where the arrow is drawn while on it
    bearing: (bearing + 360) % 360, // direction of travel along the route, degrees from north
    remaining,
    remainingTime: prepared.distance ? (prepared.duration * remaining) / prepared.distance : 0,
    offRoute: best.gap > tolerance,
    gap: best.gap,
    step,
    toStep: Math.max(0, (prepared.stepsAt[step] ?? prepared.distance) - best.travelled),
    // Near the end of the route and on it: far from the line, the nearest point is often the end itself.
    arrived: best.gap <= tolerance && remaining <= Math.max(ARRIVED_M, Math.min(accuracy, 100)),
  }
}

/** The direction of travel, degrees from north, at a distance along a prepared route (for steps without a bearing). */
export function bearingAt(prepared, distance) {
  const { line, along } = prepared
  let index = along.findIndex((value) => value > distance)
  if (index < 1) index = index === 0 ? 1 : line.length - 1
  const [a, b] = [line[index - 1], line[index]]
  return ((Math.atan2((b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180), b[1] - a[1]) * 180) / Math.PI + 360) % 360
}

/** The [lon, lat] point at a distance (metres from the start) along a prepared route. */
export function pointAlong({ line, along }, distance) {
  const index = along.findIndex((value) => value >= distance)
  if (index === -1) return line.at(-1)
  if (index === 0) return line[0]
  const [from, to] = [along[index - 1], along[index]]
  const share = to > from ? (distance - from) / (to - from) : 0
  const [a, b] = [line[index - 1], line[index]]
  return [a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share]
}

/** The route's line between two distances along it, as [lon, lat] points. */
export function sliceRoute(prepared, from, to) {
  const inner = prepared.line.filter((_, index) => prepared.along[index] > from && prepared.along[index] < to)
  return [pointAlong(prepared, from), ...inner, pointAlong(prepared, to)]
}

/** "400 m", "1.2 km", "12 km". */
export function distanceText(value) {
  if (value < 50) return `${Math.max(0, Math.round(value / 5) * 5)} m`
  if (value < 1000) return `${Math.round(value / 10) * 10} m`
  return value < 10000 ? `${(value / 1000).toFixed(1)} km` : `${Math.round(value / 1000)} km`
}

/** "45 min", "3 h 20 min". */
export function durationText(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60))
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ''}`
}
