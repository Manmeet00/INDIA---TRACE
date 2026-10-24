// The device's position as a route start: shown as "Your location", sent as "lat, lng" (the API uses it as given).
export const YOUR_LOCATION = 'Your location'

// Why the browser gave no position, and what fixes it. Browsers only share location with https pages and
// localhost; a blocked site is unblocked from the icon beside the address; a Mac also needs Location Services.
export function locationProblem(error) {
  if (typeof window !== 'undefined' && !window.isSecureContext) return 'Location only works on https or localhost; open the dashboard at http://localhost:5173.'
  if (error?.code === 1) return 'Location is blocked for this site: allow it from the icon beside the address bar.'
  if (error?.code === 2) return 'This device could not find its position: check that Location Services is on for your browser.'
  return 'Your location is taking a while.'
}

export function locateDevice() {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new Error('This browser cannot share its location. Type a starting point instead.'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({ text: YOUR_LOCATION, query: `${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)}` }),
      (error) => reject(new Error(`${locationProblem(error)} Or type a starting point.`)),
      { timeout: 10000, maximumAge: 60000 },
    )
  })
}
