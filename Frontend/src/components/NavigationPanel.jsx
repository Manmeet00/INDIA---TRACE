import { useMemo } from 'react'
import Icon from './Icon.jsx'
import { distanceText, durationText, instruction, prepareRoute, progress, turnIcon } from '../lib/navigation.js'
import { inIndia } from '../lib/mapStyle.js'
import { placeName } from '../lib/format.js'

const clock = (date) => new Intl.DateTimeFormat('en-IN', { timeStyle: 'short' }).format(date)

// Turn-by-turn guidance over the map while a route is followed: the next turn at the top, time and distance left
// at the bottom. Times are the routing service's estimates without live traffic, and say so.
export default function NavigationPanel({ route, here, destination, rerouting, error, onExit, onReroute }) {
  const prepared = useMemo(() => (route?.steps?.length ? prepareRoute(route) : null), [route])
  const now = prepared && inIndia(here) ? progress(prepared, here) : null
  const next = now ? prepared.steps[now.step] : null

  let banner
  if (rerouting) banner = <div className="nav-banner"><Icon name="refresh" size={28}/><div><b>Finding a new route…</b><span>From where you are now</span></div></div>
  else if (error) banner = <div className="nav-banner problem"><Icon name="alert" size={28}/><div><b>No new route</b><span>{error}</span></div></div>
  else if (!prepared) banner = <div className="nav-banner problem"><Icon name="alert" size={28}/><div><b>This route cannot be followed</b><span>It has no turn-by-turn steps.</span></div></div>
  else if (!now) banner = <div className="nav-banner"><Icon name="locate" size={28}/><div><b>Waiting for your location…</b><span>Guidance starts when the device finds you</span></div></div>
  else if (now.arrived) banner = <div className="nav-banner arrived"><Icon name="arrive" size={30}/><div><b>You have arrived</b><span>{destination ? placeName(destination) : 'Destination'}</span></div></div>
  else banner = <div className="nav-banner"><Icon name={turnIcon(next)} size={34}/><div><b>{distanceText(now.toStep)}</b><span>{instruction(next)}</span></div></div>

  // When the position was taken, plus the estimated time left.
  const arrival = now && here.at ? clock(new Date(here.at + now.remainingTime * 1000)) : ''
  return <div className="navigation" role="region" aria-label="Turn-by-turn navigation">
    <div aria-live="polite">{banner}</div>
    {now?.offRoute && !now.arrived && !rerouting && <div className="nav-off-route" role="alert">
      <span>You are off the route · {distanceText(now.gap)} away</span>
      <button type="button" onClick={onReroute}>Re-route from here</button>
    </div>}
    <div className="nav-bar">
      {now && !now.arrived ? <div className="nav-eta" title="Routing service estimates without live traffic">
        <b>{durationText(now.remainingTime)}</b><span>{distanceText(now.remaining)}{arrival && ` · arrive ${arrival}`}</span>
      </div> : <div className="nav-eta"><b>{now?.arrived ? 'Arrived' : 'Navigation'}</b><span>{destination ? placeName(destination) : ''}</span></div>}
      <button type="button" className="nav-exit" onClick={onExit}>{now?.arrived ? 'Done' : 'Exit'}</button>
    </div>
  </div>
}
