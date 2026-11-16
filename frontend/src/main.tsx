import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { DEMO, DemoBanner } from './components/DemoBanner'
import Logo from './components/Logo'
import SignIn from './components/SignIn'
import type { Role } from './types'
import { type AuthState, demoSignIn, initAuth, signIn, signOut } from './auth'
import './styles.css'
import './observability.css'

// The app only loads once the sign-in state is known. With no sign-in configured (local development) it loads straight away.
function Gate() {
  const [state, setState] = useState<AuthState | 'loading'>('loading')
  useEffect(() => { initAuth().then(setState).catch(() => setState('signed-out')) }, [])

  // Local development only: ?gate=preview and ?gate=noaccess show the two sign-in screens whatever the sign-in state. The buttons are the real ones, so they work when a user pool is configured. A production build ignores this.
  const preview = import.meta.env.DEV ? new URLSearchParams(window.location.search).get('gate') : null
  const demoLogin = DEMO ? (u: string, p: string, r: Role) => { const problem = demoSignIn(u, p, r); if (!problem) setState('signed-in'); return problem } : undefined

  let page
  if (preview === 'preview' || preview === 'noaccess') page = <SignIn noAccess={preview === 'noaccess'} onSignIn={() => void signIn()} onSignOut={signOut} />
  else if (state === 'loading') page = <div className="signin-loading" role="status"><Logo size="lg" /></div>
  else if (state === 'disabled' || state === 'signed-in') page = <App />
  else page = <SignIn noAccess={state === 'no-access'} onSignIn={() => void signIn()} onSignOut={signOut} onDemoSignIn={demoLogin} />
  // The demo's banner sits above every page, the sign-in screen included, so nobody signs in believing the agents are live.
  return <div className="shell">{DEMO && <DemoBanner />}{page}</div>
}

// The GitHub Pages build has no API: its /api calls are answered from a recording, installed before anything renders.
async function start() {
  if (import.meta.env.VITE_STATIC_DEMO) {
    const base = import.meta.env.VITE_API_URL ?? ''
    const { install } = await import('./demo/staticBackend')
    install(base, () => fetch(`${base}/demo-data/demo.json`).then((r) => r.json()))
  }
  createRoot(document.getElementById('root')!).render(<StrictMode><Gate /></StrictMode>)
}
void start()
