import { useCallback, useEffect, useState } from 'react'
import { locationProblem } from '../lib/location.js'

// The device's position, kept up to date as it moves (like the blue dot in a maps app). `problem` explains
// why there is no position and how to fix it; `retry` asks the browser again (after the person allows it).
export function useHere() {
  const supported = typeof navigator !== 'undefined' && 'geolocation' in navigator
  const [here, setHere] = useState(null)
  const [problem, setProblem] = useState(supported ? '' : 'This browser cannot share its location.')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!supported) return undefined
    const watch = navigator.geolocation.watchPosition(
      ({ coords }) => {
        setHere({ latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy })
        setProblem('')
      },
      (error) => setProblem(locationProblem(error)),
      { maximumAge: 30000, timeout: 15000 },
    )
    return () => navigator.geolocation.clearWatch(watch)
  }, [supported, attempt])

  const retry = useCallback(() => {
    setProblem('')
    setAttempt((value) => value + 1)
  }, [])

  return { here, problem, retry }
}
