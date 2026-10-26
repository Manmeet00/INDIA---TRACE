import { useState } from 'react'
import * as api from '../services/api.js'

// On a public deployment only the project team can collect, re-check and review. A reviewer enters the team's key
// once; the API checks it, and this browser keeps it. Visitors can still view reports and plan routes.
export default function ReviewerSignIn({ signedIn, onChange }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (signedIn) {
    return <div className="reviewer-access on"><span><i/>Signed in as reviewer</span>
      <button type="button" onClick={() => { api.setReviewerToken(''); onChange(false) }}>Sign out</button></div>
  }

  const submit = async (event) => {
    event.preventDefault()
    const value = key.trim()
    if (!value) return
    setBusy(true)
    setError('')
    try {
      await api.checkReviewerToken(value)
      api.setReviewerToken(value)
      setKey('')
      onChange(true)
    } catch (problem) {
      setError(problem.status === 401 ? 'That key is not right.' : problem.message)
    } finally {
      setBusy(false)
    }
  }

  return <details className="reviewer-access">
    <summary>Reviewer sign-in</summary>
    <form onSubmit={submit}>
      <input type="password" aria-label="Reviewer key" placeholder="Team key" autoComplete="current-password"
        value={key} onChange={(event) => setKey(event.target.value)}/>
      <button type="submit" disabled={busy || !key.trim()}>{busy ? 'Checking…' : 'Sign in'}</button>
    </form>
    {error && <small className="reviewer-error" role="alert">{error}</small>}
    <small>Visitors can view reports and plan routes. Collecting and reviewing are for the project team.</small>
  </details>
}
