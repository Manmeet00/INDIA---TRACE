import { useEffect, useState } from 'react'

// The device's position, kept up to date as it moves (like the blue dot in a maps app). `problem` explains
// why there is no position: no support, permission refused, or no fix yet.
export function useHere() {
  const supported = typeof navigator !== 'undefined' && 'geolocation' in navigator
  const [here, setHere] = useState(null)
  const [problem, setProblem] = useState(supported ? '' : 'This browser cannot share its location.')

  useEffect(() => {
    if (!supported) return undefined
    const watch = navigator.geolocation.watchPosition(
      ({ coords }) => {
        setHere({ latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy })
        setProblem('')
      },
      (error) => setProblem(error.code === error.PERMISSION_DENIED ? 'Location permission was refused.' : 'Your location is not available yet.'),
      { maximumAge: 30000, timeout: 15000 },
    )
    return () => navigator.geolocation.clearWatch(watch)
  }, [supported])

  return { here, problem }
}
