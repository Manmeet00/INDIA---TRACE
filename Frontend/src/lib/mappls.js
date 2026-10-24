// Loads the Mappls (MapmyIndia) Web Maps SDK v3 once per page. The static key travels in the script URL, as
// Mappls requires, so it must be restricted to the dashboard's domains in the Mappls console.
const SDK_URL = 'https://sdk.mappls.com/map/sdk/web?v=3.0&access_token='
const LOAD_TIMEOUT_MS = 15000

let loading = null

export function loadMappls(key) {
  if (window.mappls?.Map) return Promise.resolve(window.mappls)
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement('script')
    const timer = setTimeout(() => reject(new Error('The Mappls map did not load in time.')), LOAD_TIMEOUT_MS)
    script.src = SDK_URL + encodeURIComponent(key)
    script.async = true
    script.onload = () => {
      clearTimeout(timer)
      if (window.mappls?.Map) resolve(window.mappls)
      else reject(new Error('The Mappls map script loaded but did not start.'))
    }
    script.onerror = () => {
      clearTimeout(timer)
      // A rejected key (HTTP 401) and no network look the same to a script tag.
      reject(new Error('The Mappls map could not load: check MAPPLS_STATIC_KEY and the internet connection.'))
    }
    document.head.appendChild(script)
  }).catch((error) => {
    loading = null // allow a later attempt, for example once the network is back
    throw error
  })
  return loading
}

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char])
}
