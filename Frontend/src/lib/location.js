// The device's position as a route start: shown as "Your location", sent as "lat, lng" (the API uses it as given).
export const YOUR_LOCATION = 'Your location'

export function locateDevice() {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new Error('This browser cannot share its location. Type a starting point instead.'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({ text: YOUR_LOCATION, query: `${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)}` }),
      (error) => reject(new Error(error.code === error.PERMISSION_DENIED
        ? 'Location permission was refused. Type a starting point instead.'
        : 'Your location is not available. Type a starting point instead.')),
      { timeout: 10000, maximumAge: 60000 },
    )
  })
}
