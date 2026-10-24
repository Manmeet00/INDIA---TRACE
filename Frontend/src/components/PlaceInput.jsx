import { useEffect, useId, useRef, useState } from 'react'
import { suggestPlaces } from '../services/api.js'

const SUGGEST_DELAY_MS = 250
const LOCATION = { label: 'Your location', detail: 'Use this device’s position', source: 'location' }

// A place field with suggestions as you type, like a maps search box. `value` is { text, query }: text is what
// the field shows ("Your location"), query is what the route planner is sent ("26.14123, 91.73456").
export default function PlaceInput({ id, label, value, onChange, placeholder }) {
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [suggestions, setSuggestions] = useState([])
  const [locating, setLocating] = useState(false)
  const [note, setNote] = useState('')
  const latest = useRef(0)

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

  const choose = (option) => {
    setOpen(false)
    setActive(-1)
    setNote('')
    if (option.source !== 'location') {
      onChange({ text: option.value, query: option.value })
      return
    }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocating(false)
        onChange({ text: LOCATION.label, query: `${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)}` })
      },
      (error) => {
        setLocating(false)
        setNote(error.code === error.PERMISSION_DENIED ? 'Location permission was refused. Type a place instead.' : 'Your location is not available. Type a place instead.')
      },
      { timeout: 10000, maximumAge: 60000 },
    )
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
    <input id={id} value={locating ? 'Finding your location…' : text} placeholder={placeholder} autoComplete="off" spellCheck="false"
      role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={listId}
      aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
      required minLength="2" readOnly={locating}
      onChange={(event) => { onChange({ text: event.target.value, query: event.target.value }); setOpen(true); setActive(-1) }}
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
