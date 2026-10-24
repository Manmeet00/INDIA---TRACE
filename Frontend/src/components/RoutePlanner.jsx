import { useState } from 'react'
import Icon from './Icon.jsx'

// The route form owns its inputs and hands a plan request to onPlan; App decides how to fetch it.
export default function RoutePlanner({ loading, error, isSnapshot, onPlan }) {
  const [origin, setOrigin] = useState('Guwahati, Assam')
  const [destination, setDestination] = useState('Shillong, Meghalaya')
  const [vehicle, setVehicle] = useState('truck')
  const [priority, setPriority] = useState('cautious')

  const submit = (event) => {
    event.preventDefault()
    onPlan({ origin, destination, vehicle_type: vehicle, priority })
  }

  return <article className="panel route-panel" id="route-planning">
    <div className="panel-heading"><div><span className="section-kicker">ROUTE PLANNER</span><h1>Plan your route</h1></div></div>
    <form onSubmit={submit}>
      <label className="field-label" htmlFor="origin">FROM</label><div className="place-input"><Icon name="pin" size={17}/><input id="origin" value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="City or location" required minLength="2"/></div>
      <div className="field-label-row field-spaced"><label className="field-label" htmlFor="destination">TO</label><button type="button" className="swap-button" onClick={() => { setOrigin(destination); setDestination(origin) }} aria-label="Swap origin and destination" title="Swap origin and destination">⇅ Swap</button></div><div className="place-input"><Icon name="pin" size={17}/><input id="destination" value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="City or location" required minLength="2"/></div>
      <label className="field-label field-spaced" htmlFor="vehicle">VEHICLE TYPE</label><div className="select-wrap"><Icon name="truck" size={17}/><select id="vehicle" value={vehicle} onChange={(event) => setVehicle(event.target.value)}><option value="truck">Delivery truck</option><option value="van">Delivery van</option><option value="ambulance">Ambulance</option></select></div>
      <label className="field-label field-spaced" htmlFor="priority">ROUTE PRIORITY</label><div className="select-wrap"><Icon name="layers" size={17}/><select id="priority" value={priority} onChange={(event) => setPriority(event.target.value)}><option value="cautious">Cautious</option><option value="balanced">Balanced</option><option value="fastest">Fastest</option><option value="shortest">Shortest</option></select></div>
      <button className="primary-button" type="submit" disabled={loading}>{loading ? 'Finding routes…' : <><Icon name="search" size={17}/> Find candidate routes</>}</button>
      {error && <div className={isSnapshot ? 'inline-demo-note' : 'inline-error'} role="status">{error}</div>}
    </form>
    <div className="route-disclaimer"><span>i</span><p>Route estimates do not confirm current road conditions or vehicle restrictions.</p></div>
  </article>
}
