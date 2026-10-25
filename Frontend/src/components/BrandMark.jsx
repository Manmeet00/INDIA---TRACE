// The INDIA-TRACE mark: a folded road map with a route traced across it to a destination pin.
// The same drawing is the browser-tab icon (public/favicon.svg).
export default function BrandMark({ small = false }) {
  return <svg className={`brand-mark${small ? ' small' : ''}`} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <rect width="32" height="32" rx="8" fill="#1f6fd1"/>
    <path d="M5 10.5 12 8v17l-7 2.5z" fill="#fff"/>
    <path d="M12 8l8 2.5v17L12 25z" fill="#d3e3f8"/>
    <path d="M20 10.5 27 8v17l-7 2.5z" fill="#fff"/>
    <path d="M8 22.5c2.5-4.5 5.5 0 8.5-4s4-4 5.5-4.5" fill="none" stroke="#1f6fd1" strokeWidth="1.8" strokeLinecap="round" strokeDasharray="2.2 2"/>
    <path d="M23 17.5s-4.2-3.8-4.2-7.1a4.2 4.2 0 0 1 8.4 0c0 3.3-4.2 7.1-4.2 7.1z" fill="#f2b705" stroke="#1f6fd1" strokeWidth="1.3"/>
    <circle cx="23" cy="10.4" r="1.6" fill="#1f6fd1"/>
  </svg>
}
