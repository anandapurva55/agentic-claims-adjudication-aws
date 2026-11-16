import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { type AuthState, initAuth, signIn, signOut } from './auth'
import './styles.css'
import './observability.css'

// The app only loads once the sign-in state is known. With no sign-in configured (local development) it loads straight away.
function Gate() {
  const [state, setState] = useState<AuthState | 'loading'>('loading')
  useEffect(() => { initAuth().then(setState).catch(() => setState('signed-out')) }, [])

  if (state === 'loading') return <div className="gate"><p className="muted">Loading…</p></div>
  if (state === 'disabled' || state === 'signed-in') return <App />
  return (
    <div className="gate">
      <div className="gate-card">
        <h1>Claims Adjudication Copilot</h1>
        {state === 'no-access'
          ? <><p>You are signed in, but your account is not in the adjuster or senior adjuster group. Ask an administrator to add you.</p>
              <button className="btn" onClick={signOut}>Sign out</button></>
          : <><p>Sign in to review motor claims. Accounts are created by an administrator.</p>
              <button className="btn btn-primary" onClick={() => void signIn()}>Sign in</button></>}
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><Gate /></StrictMode>)
