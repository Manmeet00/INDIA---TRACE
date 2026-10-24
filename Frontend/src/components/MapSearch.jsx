import { useState } from 'react'
import Icon from './Icon.jsx'
import PlaceInput from './PlaceInput.jsx'

// A small search bar on the map, like a maps app's: the place chosen (or typed, then Enter) becomes the route
// planner's destination, and routes are found from the planner's starting point. status ({ tone, text }) says
// what happened to the last search right under the bar, since the planner is out of sight in full screen.
export default function MapSearch({ onSearch, status }) {
  const [value, setValue] = useState({ text: '', query: '' })
  const submit = (event) => {
    event.preventDefault()
    if (value.query.trim().length >= 2) onSearch(value)
  }
  return <form className="map-search" role="search" onSubmit={submit}>
    <Icon name="search" size={18}/>
    <PlaceInput id="map-search" label="Search destination" placeholder="Search destination" value={value} onChange={setValue} onPick={onSearch} offerLocation={false}/>
    {status && <p className={`map-search-status ${status.tone}`} role="status">{status.text}</p>}
  </form>
}
