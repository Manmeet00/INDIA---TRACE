// Indian national-highway milestone: a yellow cap carrying the road number over a white stone.
// Every highway reference in the app uses it, so roads read the same way they do on the ground.
export default function Milestone({ road, detail, note, gap = false }) {
  return <span className={`milestone${gap ? ' gap' : ''}${detail ? '' : ' cap-only'}`}>
    <span className="milestone-cap">{road.replace('-', ' ')}</span>
    {detail && <span className="milestone-stone">{detail}{note && <em>{note}</em>}</span>}
  </span>
}
