import { authEnabled, authHeaders, signIn } from './auth'
import { parseSse } from './authlib'
import type { Claim, Health, Metrics, Report, ReviewStats, Topology } from './types'

const BASE = import.meta.env.VITE_API_URL ?? ''

/** One place for every call: adds the identity, and sends a caller whose token has expired back to sign in. */
async function call(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(`${BASE}${path}`, { ...init, headers: { ...(init.headers as Record<string, string>), ...(await authHeaders()) } })
  if (r.status === 401 && authEnabled()) { void signIn(); throw new Error('signing in again') }
  return r
}

const detail = async (r: Response, fallback: string) => {
  const j = await r.json().catch(() => ({}))
  return typeof j.detail === 'string' ? j.detail : fallback
}

async function get<T>(path: string): Promise<T> {
  const r = await call(path)
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json() as Promise<T>
}

export const api = {
  health: () => get<Health>('/api/health'),
  topology: () => get<Topology>('/api/topology'),
  claims: () => get<Claim[]>('/api/claims'),
  claim: (id: string) => get<{ extracted: Record<string, unknown>; audit: { action: string; detail: { message?: string } }[] } & Claim>(`/api/claims/${id}`),
  reviewStats: () => get<ReviewStats>('/api/review-stats'),
  metrics: () => get<Metrics>('/api/metrics'),
  // Who is reviewing, and as what, is decided by the server from the sign-in token. It is not part of this request.
  review: async (id: string, body: { action: string; final_decision?: string; note?: string }) => {
    const r = await call(`/api/claims/${id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    if (!r.ok) throw new Error(await detail(r, 'review failed'))
    return (await r.json()) as { outcome: string; final: string; lesson_stored?: boolean }
  },
  attacks: () => get<{ id: string; type: string; payload: string }[]>('/api/security/attacks'),
  report: () => get<Report>('/api/security/report'),
  scan: async (text: string) => {
    const r = await call('/api/security/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
    if (!r.ok) throw new Error(await detail(r, 'scan failed'))
    return r.json() as Promise<{ clean: string; alerts: string[]; engine: string }>
  },
  /** Start a run and hand each event to the caller as it arrives. A run is a POST (it spends money and writes the audit log), so this reads the
   *  server-sent events from a fetch response instead of using EventSource, which can only send GET and cannot carry the sign-in token. */
  run: async (id: string, mode: string, onEvent: (ev: Record<string, unknown>) => void, signal: AbortSignal): Promise<void> => {
    const r = await call(`/api/claims/${id}/run?mode=${encodeURIComponent(mode)}`, { method: 'POST', signal })
    if (!r.ok || !r.body) throw new Error(await detail(r, `run failed: ${r.status}`))
    const reader = r.body.getReader(), decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (value) buffer += decoder.decode(value, { stream: true })
      const { events, rest } = parseSse(done ? buffer + '\n\n' : buffer)
      buffer = rest
      for (const e of events) {
        if (e.event === 'end') return
        if (e.data && e.data !== '{}') onEvent(JSON.parse(e.data))
      }
      if (done) return
    }
  },
}
