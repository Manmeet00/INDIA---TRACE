import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { BASE_LAYERS, OVERLAYS } from '../lib/mapLayers.js'

// Map type and map details, opened from the layers button on the map, like a maps app.
// On the Mappls map only traffic applies (Mappls draws its own map types); everything else is for OpenStreetMap.
export default function LayersPanel({ base, overlays, onBase, onToggle, mappls }) {
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

  const unavailable = (key) => key === 'traffic' ? (mappls ? '' : 'Needs the Mappls map (MAPPLS_STATIC_KEY)') : mappls ? 'On the OpenStreetMap view only' : ''

  return <div className="layers" ref={panel}>
    <button type="button" className="layers-button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="map-layers" title="Map type and details">
      <Icon name="stack" size={18}/><span>Layers</span>
    </button>
    {open && <div className="layers-panel" id="map-layers" role="dialog" aria-label="Map type and details">
      <div className="layers-head"><b>Map type</b><button type="button" className="layers-close" onClick={() => setOpen(false)} aria-label="Close map layers"><Icon name="close" size={18}/></button></div>
      <div className="layers-grid types" role="radiogroup" aria-label="Map type">
        {Object.entries(BASE_LAYERS).map(([key, layer]) => <button type="button" key={key} role="radio" aria-checked={base === key} disabled={mappls}
          className={`layer-tile${base === key ? ' on' : ''}`} onClick={() => onBase(key)}>
          <span className="layer-thumb"><img src={layer.thumb} alt="" referrerPolicy="no-referrer"/></span>{layer.label}
        </button>)}
      </div>
      <b className="layers-title">Map details</b>
      <div className="layers-grid details">
        {Object.entries(OVERLAYS).map(([key, layer]) => {
          const reason = unavailable(key)
          const on = key === 'traffic' ? Boolean(mappls) : overlays.includes(key)
          return <button type="button" key={key} aria-pressed={on} disabled={Boolean(reason) || key === 'traffic'} title={reason || layer.credit}
            className={`layer-tile${on ? ' on' : ''}`} onClick={() => onToggle(key)}>
            <span className={`layer-thumb icon ${key}`}><Icon name={layer.icon} size={26}/></span>{layer.label}
            {reason && <small>{reason}</small>}
            {key === 'traffic' && mappls && <small>Use the traffic button on the Mappls map</small>}
          </button>
        })}
      </div>
      {mappls && <p className="layers-note">Mappls draws its own map style; satellite, terrain and the other details are on the OpenStreetMap view.</p>}
    </div>}
  </div>
}
