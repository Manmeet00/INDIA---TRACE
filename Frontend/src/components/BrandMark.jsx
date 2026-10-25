// The INDIA-TRACE mark: a route traced from origin to a destination pin, with a disruption flagged on it.
// The same drawing is the browser-tab icon (public/favicon.svg).
export default function BrandMark({ small = false }) {
  return <svg className={`brand-mark${small ? ' small' : ''}`} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <rect width="32" height="32" rx="8" fill="#1f6fd1"/>
    <path d="M7.5 25v-4.5a3 3 0 0 1 3-3h11a3 3 0 0 0 3-3V14" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round"/>
    <circle cx="7.5" cy="25" r="2.4" fill="#1f6fd1" stroke="#fff" strokeWidth="2"/>
    <path d="M24.5 15.5s-5-4.6-5-8.5a5 5 0 0 1 10 0c0 3.9-5 8.5-5 8.5z" fill="#fff"/>
    <circle cx="24.5" cy="7" r="1.9" fill="#1f6fd1"/>
    <rect x="12.4" y="14" width="7.2" height="7.2" rx="1.3" transform="rotate(45 16 17.6)" fill="#f2b705" stroke="#1f6fd1" strokeWidth="1.6"/>
  </svg>
}
