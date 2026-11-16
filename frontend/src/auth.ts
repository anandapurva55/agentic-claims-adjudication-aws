// Sign-in with Amazon Cognito's hosted page, authorization code flow with PKCE. No password is ever typed into this application and no token appears in a URL.
// When the site has no /config.json (local development) sign-in is off and the API runs in its open development mode.
import { challengeFor, decodeClaims, randomString, roleOf } from './authlib'
import type { Role } from './types'

type Config = { region: string; userPoolId: string; clientId: string; hostedUi: string }
export type Session = { idToken: string; refreshToken?: string; expiresAt: number; username: string; role: Role }
export type AuthState = 'disabled' | 'signed-out' | 'signed-in' | 'no-access'

const STORE = 'claims.session'
const VERIFIER = 'claims.pkce'
const STATE = 'claims.state'
const BASE = import.meta.env.VITE_API_URL ?? ''
let config: Config | null = null
let session: Session | null = null
let demoRole: Role = 'adjuster'

const redirectUri = () => `${window.location.origin}/`
const keep = (key: string, value: string | null) => { try { value === null ? sessionStorage.removeItem(key) : sessionStorage.setItem(key, value) } catch { /* private mode */ } }
const stored = (key: string) => { try { return sessionStorage.getItem(key) } catch { return null } }

function toSession(idToken: string, refreshToken?: string): Session | null {
  const claims = decodeClaims(idToken)
  const role = roleOf(claims)
  if (!role) return null
  return { idToken, refreshToken, expiresAt: claims.exp * 1000, username: claims['cognito:username'] ?? claims.email ?? claims.sub, role }
}

function remember(s: Session | null) {
  session = s
  keep(STORE, s ? JSON.stringify(s) : null)
  // Images and links cannot send a header, so the read-only file endpoint also reads the token from this cookie. It is scoped to that path and never sent cross-site.
  document.cookie = s ? `claims_token=${s.idToken}; Path=/api/claims; SameSite=Strict; Secure` : 'claims_token=; Path=/api/claims; Max-Age=0; SameSite=Strict; Secure'
}

async function tokenRequest(body: Record<string, string>): Promise<{ id_token: string; refresh_token?: string }> {
  const r = await fetch(`${config!.hostedUi}/oauth2/token`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ client_id: config!.clientId, ...body }),
  })
  if (!r.ok) throw new Error('sign-in failed')
  return r.json()
}

export async function initAuth(): Promise<AuthState> {
  try {
    const r = await fetch(`${BASE}/config.json`)
    const c = r.ok ? await r.json() : null
    if (c?.hostedUi && c?.clientId) config = c as Config
  } catch { /* no config: local development */ }
  if (!config) return 'disabled'

  const q = new URLSearchParams(window.location.search)
  if (q.has('code')) {
    const verifier = stored(VERIFIER)
    const ok = verifier && q.get('state') === stored(STATE)
    keep(VERIFIER, null); keep(STATE, null)
    window.history.replaceState({}, '', window.location.pathname)
    if (!ok) return 'signed-out'
    try {
      const t = await tokenRequest({ grant_type: 'authorization_code', code: q.get('code')!, redirect_uri: redirectUri(), code_verifier: verifier! })
      const s = toSession(t.id_token, t.refresh_token)
      remember(s)
      return s ? 'signed-in' : 'no-access'
    } catch { return 'signed-out' }
  }
  const saved = stored(STORE)
  if (saved) {
    try {
      const s = JSON.parse(saved) as Session
      if (s.expiresAt > Date.now()) { remember(s); return 'signed-in' }
      if (s.refreshToken && await refresh(s.refreshToken)) return 'signed-in'
    } catch { /* fall through */ }
  }
  remember(null)
  return 'signed-out'
}

async function refresh(refreshToken: string): Promise<boolean> {
  try {
    const t = await tokenRequest({ grant_type: 'refresh_token', refresh_token: refreshToken })
    const s = toSession(t.id_token, refreshToken)
    remember(s)
    return !!s
  } catch { remember(null); return false }
}

export async function signIn(): Promise<void> {
  if (!config) return
  const verifier = randomString(), state = randomString(16)
  keep(VERIFIER, verifier); keep(STATE, state)
  const params = new URLSearchParams({ response_type: 'code', client_id: config.clientId, redirect_uri: redirectUri(), scope: 'openid email', state,
    code_challenge: await challengeFor(verifier), code_challenge_method: 'S256' })
  window.location.assign(`${config.hostedUi}/oauth2/authorize?${params}`)
}

export function signOut(): void {
  const hosted = config?.hostedUi, id = config?.clientId
  remember(null)
  if (hosted && id) window.location.assign(`${hosted}/logout?${new URLSearchParams({ client_id: id, logout_uri: redirectUri() })}`)
}

export const currentSession = (): Session | null => session
export const authEnabled = (): boolean => config !== null
export const setDemoRole = (r: Role): void => { demoRole = r }

/** Headers for every API call: the ID token when signed in, the development identity when sign-in is off. Refreshes an expiring token first. */
export async function authHeaders(): Promise<Record<string, string>> {
  if (!config) return { 'X-Demo-Role': demoRole, 'X-Demo-User': demoRole === 'senior' ? 'S. Rao' : 'A. Iyer' }
  if (session && session.expiresAt - 60_000 < Date.now() && session.refreshToken) await refresh(session.refreshToken)
  return session ? { Authorization: `Bearer ${session.idToken}` } : {}
}
