import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import PlaceInput from './PlaceInput.jsx'

const VEHICLES = [['truck', 'Truck', 'truck'], ['van', 'Van', 'van'], ['ambulance', 'Ambulance', 'ambulance']]
const PRIORITIES = [['cautious', 'Cautious'], ['balanced', 'Balanced'], ['fastest', 'Fastest'], ['shortest', 'Shortest']]
const PRIORITY_NOTES = {
  cautious: 'Routes with fewer reports nearby first',
  balanced: 'The routing service’s order',
  fastest: 'Shortest estimated time first',
  shortest: 'Shortest distance first',
}

const place = (text) => ({ text, query: text })

// Directions in the style of a maps app: start and destination joined by a line, travel mode and preference as
// chips. The form owns its inputs and hands a plan request to onPlan; App decides how to fetch it.
// searched: a destination chosen in the map's search bar ({ text, query, at }); it fills the destination and,
// once the starting point is known, finds routes straight away.
export default function RoutePlanner({ loading, error, isSnapshot, onPlan, searched }) {
  // The start is the device's position (found when the form opens); the destination is chosen by the person.
  const [origin, setOrigin] = useState(place(''))
  const [destination, setDestination] = useState(place(''))
  const [vehicle, setVehicle] = useState('truck')
  const [priority, setPriority] = useState('cautious')

  const [shownSearch, setShownSearch] = useState(searched)
  if (searched !== shownSearch) {
    setShownSearch(searched)
    if (searched) setDestination({ text: searched.text, query: searched.query })
  }
  const current = useRef(null)
  useEffect(() => { current.current = { origin, vehicle, priority, onPlan } })
  useEffect(() => {
    if (!searched) return
    const { origin: start, vehicle: vehicleType, priority: preference, onPlan: plan } = current.current
    if (start.query.trim().length >= 2) plan({ origin: start.query, destination: searched.query, vehicle_type: vehicleType, priority: preference })
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

      <button className="primary-button" type="submit" disabled={loading}>{loading ? 'Finding routes…' : <><Icon name="route" size={17}/> Find routes</>}</button>
      {error && <div className={isSnapshot ? 'inline-demo-note' : 'inline-error'} role="status">{error}</div>}
    </form>
    <div className="route-disclaimer"><span>i</span><p>Route estimates do not confirm current road conditions or vehicle restrictions.</p></div>
  </article>
}
