import { incidentStyle } from '../lib/incidentIcons.js'

// A report type's symbol, the same one the map draws for it. The glyphs are this app's own static SVG.
export default function ReportSymbol({ type, size = 40 }) {
  const style = incidentStyle(type)
  const glyph = Math.round(size * 0.55)
  return <span className="report-symbol" style={{ '--tone': style.color, width: size, height: size }} aria-hidden="true"
    dangerouslySetInnerHTML={{ __html: `<svg width="${glyph}" height="${glyph}" viewBox="0 0 24 24">${style.glyph}</svg>` }}/>
}
