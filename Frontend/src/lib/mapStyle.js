// Shared by the OpenStreetMap and Mappls views. Only India is shown: everything outside its official
// boundary is covered in the map's background colour, and the boundary is outlined.
export const MASK_COLOR = '#e2ece7'
export const BORDER_COLOR = '#0e1a2b'


// The device's position: a blue dot, centred at town level when no route is planned.
export const HERE_COLOR = '#1a73e8'
export const HERE_ZOOM = 12
export const INDIA_BOUNDS = [[5.5, 67], [38, 98.5]]

export function inIndia(here) {
  const [[south, west], [north, east]] = INDIA_BOUNDS
  return Boolean(here) && here.latitude >= south && here.latitude <= north && here.longitude >= west && here.longitude <= east
}

// Whether a point lies inside India's boundary (outer rings of its land parts, [lng, lat]). Ray casting with a
// bounding-box check per ring, so a few hundred labels per view are quick to test.
const ringBoxes = new WeakMap()

function box(ring) {
  if (!ringBoxes.has(ring)) {
    const lngs = ring.map((point) => point[0])
    const lats = ring.map((point) => point[1])
    ringBoxes.set(ring, [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)])
  }
  return ringBoxes.get(ring)
}

export function insideBoundary(boundary, latitude, longitude) {
  return boundary.some((ring) => {
    const [west, south, east, north] = box(ring)
    if (longitude < west || longitude > east || latitude < south || latitude > north) return false
    let inside = false
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i]
      const [xj, yj] = ring[j]
      if ((yi > latitude) !== (yj > latitude) && longitude < ((xj - xi) * (latitude - yi)) / (yj - yi) + xi) inside = !inside
    }
    return inside
  })
}
