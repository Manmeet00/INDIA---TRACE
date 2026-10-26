import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { BASE_LAYERS, OVERLAYS } from '../lib/mapLayers.js'

// Map type and map details, opened from the layers button on the map, like a maps app.
// mappls: the Mappls map is available. It is the Default map type (with street, colony and galli names, and its own
// traffic button); satellite, terrain and the other details are drawn on OpenStreetMap, so choosing one switches to it.
// showingMappls: the Mappls map is on screen; onMappls switches back to it.
export default function LayersPanel({ base, overlays, onBase, onToggle, mappls, showingMappls, onMappls }) {
  const [open, setOpen] = useState(false)
  const panel = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const close = (event) => { if (event.key === 'Escape' || (event.type === 'pointerdown' && !panel.current?.contains(event.target))) setOpen(false) }
    document.addEventListener('keydown', close)
    document.addEventListener('pointerdown', close)
    return () => {
      document.removeEventListener('keydown', close)
      document.removeEventListener('pointerdown', close)
    }
  }, [open])

  const unavailable = (key) => (key === 'traffic' && !mappls ? 'Needs the Mappls map (MAPPLS_STATIC_KEY)' : '')
  const hint = (key) => key === 'traffic' ? (showingMappls ? 'Use the traffic button on the map' : mappls ? 'Switches to the Mappls map' : '')
    : showingMappls ? 'Switches to OpenStreetMap' : ''

  return <div className="layers" ref={panel}>
    <button type="button" className="layers-button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="map-layers" title="Map type and details">
      <Icon name="stack" size={18}/><span>Layers</span>
    </button>
    {open && <div className="layers-panel" id="map-layers" role="dialog" aria-label="Map type and details">
      <div className="layers-head"><b>Map type</b><button type="button" className="layers-close" onClick={() => setOpen(false)} aria-label="Close map layers"><Icon name="close" size={18}/></button></div>
      <div className="layers-grid types" role="radiogroup" aria-label="Map type">
        {Object.entries(BASE_LAYERS).map(([key, layer]) => <button type="button" key={key} role="radio" aria-checked={base === key}
          className={`layer-tile${base === key ? ' on' : ''}`} onClick={() => (key === 'default' && mappls ? onMappls() : onBase(key))}>
          <span className="layer-thumb"><img src={layer.thumb} alt=""/></span>{layer.label}
          {mappls && <small>{key === 'default' ? 'Mappls street names' : 'OpenStreetMap labels'}</small>}
        </button>)}
      </div>
      <b className="layers-title">Map details</b>
      <div className="layers-grid details">
        {Object.entries(OVERLAYS).map(([key, layer]) => {
          const reason = unavailable(key)
          const on = key === 'traffic' ? Boolean(showingMappls) : overlays.includes(key)
          const note = reason || hint(key)
          return <button type="button" key={key} aria-pressed={on} disabled={Boolean(reason)} title={reason || layer.credit}
            className={`layer-tile${on ? ' on' : ''}`} onClick={() => (key === 'traffic' ? onMappls() : onToggle(key))}>
            <span className={`layer-thumb icon ${key}`}><Icon name={layer.icon} size={26}/></span>{layer.label}
            {note && <small>{note}</small>}
          </button>
        })}
      </div>
      {mappls && <p className="layers-note">Default is the Mappls map, with colony and galli names and its own traffic button. Satellite, terrain and the other details are drawn on OpenStreetMap.</p>}
    </div>}
  </div>
}
