import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import PlaceInput from './PlaceInput.jsx'

// Bike gets Google's two-wheeler routes; car and truck a car's (the route notes say trucks are usually slower).
const VEHICLES = [['car', 'Car', 'car'], ['bike', 'Bike', 'motorbike'], ['truck', 'Truck', 'truck']]
const PRIORITIES = [['fastest', 'Fastest'], ['balanced', 'Balanced'], ['shortest', 'Shortest'], ['cautious', 'Cautious']]
const PRIORITY_NOTES = {
  fastest: 'Shortest estimated time first, like a maps app',
  balanced: 'Fastest, unless a route at most 10% slower has fewer reports placed near it',
  shortest: 'Shortest distance first, even when it takes longer',
  cautious: 'Routes with fewer reports nearby first, even when slower',
}

const place = (text) => ({ text, query: text })
// A plan usually takes a few seconds; after this long the form says why it may take longer.
const SLOW_MS = 8000

// Directions in the style of a maps app: start and destination joined by a line, travel mode and preference as
// chips. The form owns its inputs and hands a plan request to onPlan; App decides how to fetch it.
// searched: a destination chosen in the map's search bar ({ text, query, at }); it fills the destination and,
// once the starting point is known, finds routes straight away (otherwise onSearchWithoutStart is told).
// onStart opens the chosen route turn by turn (null when it cannot: startNote says why); startMode is 'live'
// (Start: guidance from where you are) or 'preview' (Preview: step through the turns from anywhere).
export default function RoutePlanner({ loading, error, isSnapshot, onPlan, searched, onSearchWithoutStart, hasPlan, onStart, startMode, startNote }) {
  // The start is the device's position (found when the form opens); the destination is chosen by the person.
  const [origin, setOrigin] = useState(place(''))
  const [destination, setDestination] = useState(place(''))
  const [vehicle, setVehicle] = useState('car')
  const [priority, setPriority] = useState('fastest')
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    if (!loading) return undefined
    const timer = setTimeout(() => setSlow(true), SLOW_MS)
    return () => { clearTimeout(timer); setSlow(false) }
  }, [loading])

  const [shownSearch, setShownSearch] = useState(searched)
  if (searched !== shownSearch) {
    setShownSearch(searched)
    if (searched) setDestination({ text: searched.text, query: searched.query })
  }
  const current = useRef(null)
  useEffect(() => { current.current = { origin, vehicle, priority, onPlan, onSearchWithoutStart } })
  useEffect(() => {
    if (!searched) return
    const { origin: start, vehicle: vehicleType, priority: preference, onPlan: plan, onSearchWithoutStart: noStart } = current.current
    if (start.query.trim().length >= 2) plan({ origin: start.query, destination: searched.query, vehicle_type: vehicleType, priority: preference })
    else noStart?.()
  }, [searched])

  const submit = (event) => {
    event.preventDefault()
    onPlan({ origin: origin.query, destination: destination.query, vehicle_type: vehicle, priority })
  }

  return <article className="panel route-panel" id="route-planning">
    <div className="panel-heading"><div><span className="section-kicker">ROUTE PLANNER</span><h1>Plan your route</h1></div></div>
    <form onSubmit={submit}>
      <div className="stops">
        <div className="stop-rail" aria-hidden="true"><span className="stop-origin"/><span className="stop-line"/><Icon name="pin" size={18}/></div>
        <div className="stop-fields">
          <PlaceInput id="origin" label="Starting point" placeholder="Choose starting point" value={origin} onChange={setOrigin} autoLocate/>
          <PlaceInput id="destination" label="Destination" placeholder="Choose destination" value={destination} onChange={setDestination}/>
        </div>
        <button type="button" className="swap-button" onClick={() => { setOrigin(destination); setDestination(origin) }} aria-label="Swap starting point and destination" title="Swap starting point and destination"><Icon name="swap" size={18}/></button>
      </div>

      <fieldset className="chip-group modes"><legend>Vehicle</legend>
        {VEHICLES.map(([key, label, icon]) => <label key={key} className={`chip${vehicle === key ? ' on' : ''}`}>
          <input type="radio" name="vehicle" value={key} checked={vehicle === key} onChange={() => setVehicle(key)}/><Icon name={icon} size={17}/>{label}
        </label>)}
      </fieldset>
      <fieldset className="chip-group preferences"><legend>Route preference</legend>
        {PRIORITIES.map(([key, label]) => <label key={key} className={`chip${priority === key ? ' on' : ''}`}>
          <input type="radio" name="priority" value={key} checked={priority === key} onChange={() => setPriority(key)}/>{label}
        </label>)}
        <small className="chip-note">{PRIORITY_NOTES[priority]}</small>
      </fieldset>

      <div className={hasPlan ? 'planner-actions' : undefined}>
        {hasPlan && <button type="button" className="start-button" onClick={onStart} disabled={!onStart || loading} title={startNote || 'Follow this route turn by turn'}><Icon name={startMode === 'preview' ? 'route' : 'navigate'} size={17}/> {startMode === 'preview' ? 'Preview' : 'Start'}</button>}
        <button className={`primary-button${hasPlan ? ' secondary' : ''}`} type="submit" disabled={loading}>{loading ? 'Finding routes…' : <><Icon name="route" size={17}/> Find routes</>}</button>
      </div>
      {hasPlan && startNote && <small className="start-note">{startNote}</small>}
      {loading && slow && <small className="start-note" role="status">Still finding routes. After a quiet spell the free server takes up to a minute to start, and the map services can be slow at busy times.</small>}
      {error && <div className={isSnapshot ? 'inline-demo-note' : 'inline-error'} role="status">{error}</div>}
    </form>
    <div className="route-disclaimer"><span>i</span><p>Route estimates do not confirm current road conditions or vehicle restrictions.</p></div>
  </article>
}
