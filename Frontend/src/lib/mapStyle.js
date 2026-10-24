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
