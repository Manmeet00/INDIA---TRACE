import { useEffect, useId, useRef, useState } from 'react'
import { YOUR_LOCATION, locateDevice } from '../lib/location.js'
import { suggestPlaces } from '../services/api.js'

const SUGGEST_DELAY_MS = 250
const LOCATION = { label: YOUR_LOCATION, detail: 'Use this device’s position', source: 'location' }

// A place field with suggestions as you type, like a maps search box. `value` is { text, query }: text is what
// the field shows ("Your location"), query is what the route planner is sent ("26.14123, 91.73456").
// With autoLocate, an empty field fills itself with the device's position when it first appears.
export default function PlaceInput({ id, label, value, onChange, placeholder, autoLocate = false }) {
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [suggestions, setSuggestions] = useState([])
  const [locating, setLocating] = useState(false)
  const [note, setNote] = useState('')
  const latest = useRef(0)
  // autoLocate: 'pending' until the device answers or the person types or picks a place themselves.
  const [autoState, setAutoState] = useState(autoLocate ? 'pending' : 'done')

  const text = value.text
  const typed = text.trim().length >= 2 && text !== LOCATION.label
  const options = typed ? suggestions : ('geolocation' in navigator ? [LOCATION] : [])

  useEffect(() => {
    if (!open || !typed) return undefined
    const request = ++latest.current
    const timer = setTimeout(() => {
      suggestPlaces(text.trim())
        .then((items) => { if (request === latest.current) setSuggestions(items) })
        .catch(() => { if (request === latest.current) setSuggestions([]) })
    }, SUGGEST_DELAY_MS)
    return () => clearTimeout(timer)
  }, [open, typed, text])

  const fillFromDevice = () => {
    setLocating(true)
    setNote('')
    locateDevice()
      .then((place) => onChange(place))
      .catch((error) => setNote(error.message))
      .finally(() => setLocating(false))
  }

  // Fills the empty field with the device's position once; a place typed or picked before it answers is kept.
  useEffect(() => {
    if (autoState !== 'pending' || value.text) return undefined
    let current = true
    locateDevice()
      .then((place) => { if (current) onChange(place) })
      .catch((error) => { if (current) setNote(error.message) })
      .finally(() => { if (current) setAutoState('done') })
    return () => { current = false }
  }, [autoState, value.text, onChange])

  const choose = (option) => {
    setOpen(false)
    setActive(-1)
    setNote('')
    setAutoState('done')
    if (option.source === 'location') fillFromDevice()
    else onChange({ text: option.value, query: option.value })
  }

  const onKeyDown = (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((current) => options.length ? (current + step + options.length) % options.length : -1)
    } else if (event.key === 'Enter' && open && active >= 0 && options[active]) {
      event.preventDefault() // choose the highlighted place rather than submitting the form
      choose(options[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  const expanded = open && options.length > 0
  return <div className="place-field">
    <label className="sr-only" htmlFor={id}>{label}</label>
    <input id={id} className={text === YOUR_LOCATION ? 'is-location' : undefined} value={locating ? 'Finding your location…' : text} placeholder={autoState === 'pending' ? 'Finding your location…' : placeholder} autoComplete="off" spellCheck="false"
      role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={listId}
      aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
      required minLength="2" readOnly={locating}
      onChange={(event) => { setAutoState('done'); onChange({ text: event.target.value, query: event.target.value }); setOpen(true); setActive(-1) }}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={onKeyDown}/>
    {expanded && <ul className="place-suggestions" id={listId} role="listbox" aria-label={`${label} suggestions`}>
      {options.map((option, index) => <li key={`${option.source}-${option.value || option.label}`} id={`${listId}-${index}`} role="option"
        aria-selected={index === active} className={`${option.source}${index === active ? ' active' : ''}`}
        onMouseDown={(event) => event.preventDefault()} onClick={() => choose(option)}>
        <b>{option.label}</b>{option.detail && <small>{option.detail}</small>}
      </li>)}
    </ul>}
    {note && <small className="place-note" role="status">{note}</small>}
  </div>
}
