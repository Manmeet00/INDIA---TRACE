import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'

const STORAGE_KEY = 'india-trace.sidebar'
const PHONE = '(max-width: 760px)'

function readOpen() {
  try { return localStorage.getItem(STORAGE_KEY) !== 'hidden' } catch { return true }
}

function subscribePhone(callback) {
  const query = window.matchMedia(PHONE)
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

// Whether the left sidebar is shown. The choice is remembered in this browser. On phones the sidebar is the
// bottom navigation bar and always stays visible.
export function useSidebar() {
  const [open, setOpen] = useState(readOpen)
  const phone = useSyncExternalStore(subscribePhone, () => window.matchMedia(PHONE).matches)
  const toggle = useCallback(() => setOpen((current) => !current), [])
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, open ? 'shown' : 'hidden') } catch { /* private mode: not remembered */ }
    // Leaflet and Mappls resize only with the window, so tell them once the sidebar has finished sliding.
    const timer = setTimeout(() => window.dispatchEvent(new Event('resize')), 250)
    return () => clearTimeout(timer)
  }, [open])
  return { hidden: !open && !phone, toggle }
}
