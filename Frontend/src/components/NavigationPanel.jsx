import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { distanceText, durationText, instructionParts, spoken, turnIcon } from '../lib/navigation.js'
import { placeName } from '../lib/format.js'

const clock = (date) => new Intl.DateTimeFormat('en-IN', { timeStyle: 'short' }).format(date)
const THEN_WITHIN_M = 1000 // the turn after the next one is shown ("Then ↱") when it comes this soon after
const NEAR_M = 150 // close enough to say the instruction again, without a distance
const REROUTE_AFTER = 2 // position updates off the route in a row before a new route is fetched on its own
const REROUTE_EVERY_MS = 20000
const VOICE_KEY = 'india-trace.voice'

function savedVoice() {
  try { return localStorage.getItem(VOICE_KEY) !== 'off' } catch { return true }
}

// Turn-by-turn guidance laid out like Google Maps' navigation: the next turn in a green banner at the top (with
// "Then" when another turn follows soon after), time and distance left in a sheet at the bottom, spoken
// directions with a mute button. now/prepared come from the map (see RouteMap). Times are the routing service's
// estimates: Google's with traffic when the route was planned (traffic), otherwise OSRM's without it, and say so.
// mode 'preview' (away from the route's start): the turns one by one with ‹ ›, no voice and no re-routing.
export default function NavigationPanel({ mode = 'live', traffic = false, prepared, now, here, destination, rerouting, error, onExit, onReroute,
  following, onRecentre, overview, onOverview, previewStep, onPreviewStep }) {
  const [voice, setVoice] = useState(savedVoice)
  const previewing = mode === 'preview' && prepared
  const nextIndex = previewing ? previewStep : now?.step
  const next = nextIndex != null && prepared ? prepared.steps[nextIndex] : null
  const after = next ? prepared.steps[nextIndex + 1] : null
  const thenStep = after && after.type !== 'arrive' && next?.distance_m <= THEN_WITHIN_M ? after : null
  const name = destination ? placeName(destination) : 'your destination'

  // Spoken directions: once when a new turn comes up (with its distance) and again just before it.
  const said = useRef({ step: null, near: false, arrived: false })
  // A new route (after a re-route) starts again: its next turn may have the same index as the old one's. This runs
  // before the effect below, so the new route's first instruction is spoken.
  useEffect(() => { said.current = { step: null, near: false, arrived: false } }, [prepared])
  // Nothing more is said once navigation closes.
  useEffect(() => () => { if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel() }, [])
  const near = now ? now.toStep < NEAR_M : false
  const announcement = !now || previewing ? '' : now.arrived ? `You have arrived at ${name}` : spoken(next, now.toStep)
  useEffect(() => {
    if (!voice || !announcement || rerouting || typeof window === 'undefined' || !('speechSynthesis' in window)) return
    const say = (text) => {
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))
    }
    const heard = said.current
    if (now.arrived) {
      if (!heard.arrived) { heard.arrived = true; say(announcement) }
    } else if (heard.step !== now.step) {
      said.current = { step: now.step, near, arrived: false }
      say(announcement)
    } else if (near && !heard.near) {
      heard.near = true
      say(announcement)
    }
  }, [announcement, near, voice, rerouting, now])
  const toggleVoice = () => setVoice((value) => {
    try { localStorage.setItem(VOICE_KEY, value ? 'off' : 'on') } catch { /* remembered for this visit only */ }
    if (value && typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
    return !value
  })

  // Off the route for a few updates in a row: a new route from here, like a maps app (at most every 20 s).
  // Counted per position update (here), not per render: onReroute is a new function on every render.
  const offCount = useRef(0)
  const lastReroute = useRef(0)
  const reroute = useRef(onReroute)
  useEffect(() => { reroute.current = onReroute })
  const off = Boolean(!previewing && now?.offRoute && !now.arrived)
  useEffect(() => {
    offCount.current = off ? offCount.current + 1 : 0
    if (offCount.current >= REROUTE_AFTER && !rerouting && Date.now() - lastReroute.current > REROUTE_EVERY_MS) {
      lastReroute.current = Date.now()
      offCount.current = 0
      reroute.current()
    }
  }, [off, here, rerouting])

  let banner
  if (previewing) {
    const { headline, action } = instructionParts(next)
    const reach = nextIndex === 0 ? 'Start' : distanceText(prepared.steps[nextIndex - 1].distance_m)
    banner = <div className="nav-banner"><div className="nav-turn"><Icon name={turnIcon(next)} size={44}/><b>{reach}</b></div>
      <div className="nav-road">{action && <span>{action}</span>}<b>{headline}</b></div></div>
  } else if (rerouting) banner = <div className="nav-banner"><div className="nav-turn"><Icon name="refresh" size={40}/></div><div className="nav-road"><b>Rerouting…</b><span>Finding a route from where you are</span></div></div>
  else if (error) banner = <div className="nav-banner problem"><div className="nav-turn"><Icon name="alert" size={40}/></div><div className="nav-road"><b>No new route</b><span>{error}</span><button type="button" className="nav-retry" onClick={onReroute}>Try again</button></div></div>
  else if (!prepared) banner = <div className="nav-banner problem"><div className="nav-turn"><Icon name="alert" size={40}/></div><div className="nav-road"><b>This route cannot be followed</b><span>It has no turn-by-turn steps.</span></div></div>
  else if (!now) banner = <div className="nav-banner"><div className="nav-turn"><Icon name="locate" size={40}/></div><div className="nav-road"><b>Finding your location…</b><span>Guidance starts when the device finds you</span></div></div>
  else if (now.arrived) banner = <div className="nav-banner"><div className="nav-turn"><Icon name="arrive" size={40}/></div><div className="nav-road"><span>You have arrived</span><b>{name}</b></div></div>
  else {
    const { headline, action } = instructionParts(next)
    banner = <div className="nav-banner"><div className="nav-turn"><Icon name={turnIcon(next)} size={44}/><b>{distanceText(now.toStep)}</b></div>
      <div className="nav-road">{action && <span>{action}</span>}<b>{headline}</b></div></div>
  }

  const arrival = now && here?.at ? clock(new Date(here.at + now.remainingTime * 1000)) : ''
  return <div className="navigation" role="region" aria-label="Turn-by-turn navigation">
    <div className="nav-top">
      <div aria-live="polite">{banner}</div>
      {thenStep && !rerouting && !error && <div className="nav-then">Then <Icon name={turnIcon(thenStep)} size={20}/></div>}
      {off && !rerouting && <div className="nav-off-route" role="alert">
        <span>You are off the route · {distanceText(now.gap)} away</span>
        <button type="button" onClick={onReroute}>Re-route</button>
      </div>}
    </div>
    <div className="nav-side">
      {previewing ? <button type="button" className={`nav-round${overview ? ' on' : ''}`} onClick={onOverview} aria-pressed={overview} aria-label="Route overview" title="Route overview"><Icon name="route" size={22}/></button>
        : <button type="button" className="nav-round" onClick={toggleVoice} aria-pressed={voice} aria-label={voice ? 'Mute voice directions' : 'Turn on voice directions'} title={voice ? 'Mute' : 'Unmute'}>
        <Icon name={voice ? 'volume' : 'volume-off'} size={22}/></button>}
    </div>
    {!following && (previewing || (now && !now.arrived)) && <button type="button" className="nav-recentre" onClick={onRecentre}><Icon name="navigate" size={18}/> Re-centre</button>}
    {previewing ? <div className="nav-sheet">
      <button type="button" className="nav-close" onClick={onExit} aria-label="Close preview" title="Close preview"><Icon name="close" size={24}/></button>
      <div className="nav-eta preview"><b>Turn {nextIndex + 1} of {prepared.steps.length}</b>
        <span>{distanceText(prepared.distance - prepared.stepsAt[nextIndex])} · {durationText((prepared.duration * (prepared.distance - prepared.stepsAt[nextIndex])) / (prepared.distance || 1))} from here</span></div>
      <div className="nav-steps">
        <button type="button" className="nav-round" onClick={() => onPreviewStep(nextIndex - 1)} disabled={nextIndex === 0} aria-label="Previous turn" title="Previous turn"><Icon name="chevron-left" size={22}/></button>
        <button type="button" className="nav-round" onClick={() => onPreviewStep(nextIndex + 1)} disabled={nextIndex >= prepared.steps.length - 1} aria-label="Next turn" title="Next turn"><Icon name="chevron-right" size={22}/></button>
      </div>
    </div> : <div className="nav-sheet">
      <button type="button" className="nav-close" onClick={onExit} aria-label={now?.arrived ? 'Done' : 'Exit navigation'} title={now?.arrived ? 'Done' : 'Exit navigation'}><Icon name="close" size={24}/></button>
      {now && !now.arrived ? <div className="nav-eta" title={traffic ? "Google's estimate with traffic when the route was planned" : 'Routing service estimates without live traffic'}>
        <b>{durationText(now.remainingTime)}</b><span>{distanceText(now.remaining)}{arrival && ` · ${arrival}`}</span>
      </div> : <div className="nav-eta"><b>{now?.arrived ? 'Arrived' : 'Navigation'}</b><span>{destination ? placeName(destination) : ''}</span></div>}
      <button type="button" className={`nav-round${overview ? ' on' : ''}`} onClick={onOverview} aria-pressed={overview} aria-label="Route overview" title="Route overview"><Icon name="route" size={22}/></button>
    </div>}
  </div>
}
