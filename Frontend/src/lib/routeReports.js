// The reports matched to a route by the API (route.exposure), most relevant first, each with why it matched:
// a reviewer-confirmed location near the route, a town on it that the report names, or a highway it uses.
const km = (metres) => `${(metres / 1000).toFixed(1)} km`

/** Map of report id to the reason it is on this route, in the API's relevance order; null without a route. */
export function routeMatches(route) {
  const exposure = route?.exposure
  if (!exposure) return null
  const reasons = new Map()
  for (const id of exposure.nearby_ids) reasons.set(id, `${km(exposure.nearby_distances[id])} from the route (reviewer-confirmed location)`)
  for (const [place, ids] of Object.entries(exposure.place_matches || {})) {
    for (const id of ids) reasons.set(id, `Names ${place}, ${km(exposure.place_distances[id])} from the route. Placed at the town, not the exact spot.`)
  }
  for (const [road, ids] of Object.entries(exposure.highway_mentions)) {
    for (const id of ids) if (!reasons.has(id)) reasons.set(id, `Names ${road}, which this route uses. Where on ${road} is not known: check the source.`)
  }
  const ranked = (route.impact_reports || []).map((report) => report.id).filter((id) => reasons.has(id))
  return new Map([...ranked, ...reasons.keys()].map((id) => [id, reasons.get(id)]))
}
