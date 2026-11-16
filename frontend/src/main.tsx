import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import Logo from './components/Logo'
import SignIn from './components/SignIn'
import { type AuthState, initAuth, signIn, signOut } from './auth'
import './styles.css'
import './observability.css'

// The app only loads once the sign-in state is known. With no sign-in configured (local development) it loads straight away.
function Gate() {
  const [state, setState] = useState<AuthState | 'loading'>('loading')
  // The recorded demo has no accounts: nothing to sign in to, so it never looks for a sign-in configuration.
  useEffect(() => { if (import.meta.env.VITE_STATIC_DEMO) setState('disabled'); else initAuth().then(setState).catch(() => setState('signed-out')) }, [])

  // Local development only: ?gate=preview and ?gate=noaccess show the two sign-in screens whatever the sign-in state. The buttons are the real ones, so they work when a user pool is configured. A production build ignores this.
  const preview = import.meta.env.DEV ? new URLSearchParams(window.location.search).get('gate') : null
  if (preview === 'preview' || preview === 'noaccess') return <SignIn noAccess={preview === 'noaccess'} onSignIn={() => void signIn()} onSignOut={signOut} />

  if (state === 'loading') return <div className="signin-loading" role="status"><Logo size="lg" /></div>
  if (state === 'disabled' || state === 'signed-in') return <App />
  return <SignIn noAccess={state === 'no-access'} onSignIn={() => void signIn()} onSignOut={signOut} />
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
