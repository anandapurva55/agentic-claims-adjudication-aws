import type { Claim, Health, Metrics, Report, ReviewStats, Topology } from './types'

const BASE = import.meta.env.VITE_API_URL ?? ''

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
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
  review: async (id: string, body: { action: string; final_decision?: string; note?: string; role: string; reviewer: string }) => {
    const r = await fetch(`${BASE}/api/claims/${id}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'review failed')
    return j as { outcome: string; final: string; lesson_stored?: boolean }
  },
  attacks: () => get<{ id: string; type: string; payload: string }[]>('/api/security/attacks'),
  report: () => get<Report>('/api/security/report'),
  scan: async (text: string) => {
    const r = await fetch(`${BASE}/api/security/scan`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<{ clean: string; alerts: string[]; engine: string }>
  },
  runUrl: (id: string, mode: string) => `${BASE}/api/claims/${id}/run?mode=${mode}`,
}
