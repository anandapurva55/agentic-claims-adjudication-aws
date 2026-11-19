// The interactive demo. GitHub Pages serves files only, so there is no API behind this build. This module answers the app's /api calls from a recording of the real
// backend (scripts/build_static_demo.py) and keeps each visitor's runs and reviews in their own browser. The agents are never called, and nothing here costs money.
// The review rules below are a port of the server's, because the demo has to refuse what the server would refuse. Two differences, both shown in the banner:
// a reason written for an override is not scanned for prompt attacks, and it is not stored as a long term lesson.
import type { Claim, Role } from '../types'

export const AUTHORITY_CLAUSE = 'INT.AUTH'  // the clause the rules engine cites when the payable is above the adjuster's limit

export type Ai = { decision: string; payable: number; clauses: string[]; mode: string; run_id: string }
type Row = { ts: string; actor: string; action: string; detail: Record<string, unknown> }
export type Entry = { ai: Ai | null; review: Record<string, unknown> | null; audit: Row[] }
export type DemoState = { version: string; claims: Record<string, Entry> }
export type Fixtures = {
  generated: string; health: Record<string, unknown>; topology: unknown; claims: Claim[]; details: Record<string, unknown>
  runs: Record<string, { events: Record<string, unknown>[]; ai: Ai }>
  attacks: { id: string; type: string; payload: string }[]; scans: Record<string, unknown>; report: unknown
}
export type Result = { status: number; body: unknown }
export type ReviewBody = { run_id?: string; action?: string; final_decision?: string | null; note?: string }

const fail = (status: number, detail: string): Result => ({ status, body: { detail } })
const entry = (st: DemoState, id: string): Entry => (st.claims[id] ??= { ai: null, review: null, audit: [] })

export const emptyState = (fx: Fixtures): DemoState => ({ version: fx.generated, claims: {} })

/** One claim as the list shows it: the recorded fields, with this visitor's own stage, recommendation and review on top. */
export function summary(fx: Fixtures, st: DemoState, id: string): Claim | null {
  const base = fx.claims.find((c) => c.claim_id === id)
  if (!base) return null
  const e = st.claims[id]
  const stage = e?.review ? 'reviewed' : e?.ai ? 'ai_recommended' : 'new'
  return { ...base, stage, ai: e?.ai ?? null, review: (e?.review as Claim['review']) ?? null }
}

/** A run finished: store its recommendation, as the server writes a decision row. A claim a person already decided stays decided. */
export function recordRun(st: DemoState, id: string, ai: Ai, now = new Date()): void {
  const e = entry(st, id)
  if (e.review) return
  e.ai = ai
  e.audit.push({ ts: now.toISOString(), actor: 'ai', action: 'decision', detail: { decision: ai.decision, payable: ai.payable, clauses: ai.clauses, mode: ai.mode, run_id: ai.run_id } })
}

/** The human sign-off gate, with the server's rules in the server's order. */
export function applyReview(st: DemoState, id: string, body: ReviewBody, who: { role: Role; username: string }, now = new Date()): Result {
  const e = st.claims[id]
  if (!e?.ai) return fail(409, 'run the agents first: there is no AI recommendation to review')
  if (e.review) return fail(409, 'this claim already has a human decision')
  const ai = e.ai
  if (!body.run_id || !/^[A-Za-z0-9_-]{1,64}$/.test(body.run_id)) return fail(422, 'run_id is required')
  if (body.action !== 'accept' && body.action !== 'override' && body.action !== 'escalate') return fail(422, 'action must be accept, override or escalate')
  if (ai.run_id !== body.run_id) return fail(409, 'the recommendation changed since you looked at it (someone ran the agents again): reload the claim and review the new result')
  if (body.action === 'override') {
    if (!body.final_decision) return fail(422, 'override requires final_decision: approve, deny or refer')
    if (!['approve', 'deny', 'refer'].includes(body.final_decision)) return fail(422, 'final_decision must be approve, deny or refer')
    if ((body.note ?? '').trim().length < 10) return fail(422, 'an override needs a reason of at least 10 characters')
  }
  const overLimit = ai.clauses.includes(AUTHORITY_CLAUSE)
  const approving = (body.action === 'accept' && (ai.decision === 'approve' || ai.decision === 'refer')) || (body.action === 'override' && body.final_decision === 'approve')
  if (overLimit && approving && who.role !== 'senior') return fail(403, 'this payable is above the adjuster authority limit: a senior adjuster must approve, or you can escalate')
  // A denial or referral has no payable, so it never carries the limit above. Approving against the AI's call is a senior decision at any size.
  if (body.action === 'override' && body.final_decision === 'approve' && who.role !== 'senior') return fail(403, "approving against the AI's recommendation needs a senior adjuster: you can escalate or refer instead")
  const final = body.action === 'accept' ? ai.decision : body.action === 'override' ? (body.final_decision as string) : 'escalated'
  const outcome = ({
    approve: final === 'approve' && body.action === 'accept' ? `Settlement of INR ${ai.payable.toLocaleString('en-IN')} released for payment.`
      : "Approved by a senior adjuster against the AI's recommendation. No payable was calculated, so the amount must be set before payment.",
    deny: 'Denial confirmed. Letter queued for the policy holder.', refer: 'Referred to a senior adjuster.', escalated: 'Escalated to a senior adjuster.',
  } as Record<string, string>)[final]
  const ts = now.toISOString()
  const detail = { run_id: body.run_id, action: body.action, final_decision: body.final_decision ?? null, note: body.note ?? '', reviewer: who.username, role: who.role,
    ai_decision: ai.decision, ai_payable: ai.payable, ai_clauses: ai.clauses, final }
  e.review = { ...detail, ts }
  e.audit.push({ ts, actor: `${who.role}:${who.username}`, action: 'human_review', detail }, { ts, actor: 'system', action: 'outcome', detail: { final, message: outcome } })
  return { status: 200, body: { ...detail, ts, outcome, lesson_stored: false } }
}

// ---- the fetch layer ------------------------------------------------------------------------------------------------------------------------------------

/** How long each kind of recorded event waits before the next, so a run plays as it would live. The recording itself has no pauses. */
export const PACE_MS: Record<string, number> = { node: 260, edge: 130, log: 230, tool: 170, note: 250, result: 500 }

type Store = { get: () => string | null; set: (s: string) => void; clear: () => void }
const browserStore = (): Store => ({
  get: () => { try { return localStorage.getItem('claims.demo') } catch { return null } },
  set: (s) => { try { localStorage.setItem('claims.demo', s) } catch { /* private mode: the demo still works, it just forgets on reload */ } },
  clear: () => { try { localStorage.removeItem('claims.demo') } catch { /* nothing to clear */ } },
})

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

export function install(base: string, loadFixtures: () => Promise<Fixtures>, opts: { store?: Store; paceScale?: number; fetchImpl?: typeof fetch } = {}): { reset: () => void } {
  const store = opts.store ?? browserStore()
  const scale = opts.paceScale ?? 1
  const realFetch = opts.fetchImpl ?? window.fetch.bind(window)
  let fx: Fixtures | null = null
  let state: DemoState | null = null
  const ready = async () => {
    fx ??= await loadFixtures()
    if (!state) {
      let saved: DemoState | null = null
      try { saved = JSON.parse(store.get() ?? 'null') } catch { /* corrupt: start again */ }
      state = saved && saved.version === fx.generated ? saved : emptyState(fx)  // a new recording invalidates an old browser's saved runs
    }
    return { fx, st: state }
  }
  const save = () => { if (state) store.set(JSON.stringify(state)) }

  const run = (f: Fixtures, st: DemoState, id: string, signal?: AbortSignal | null) => {
    const rec = f.runs[id]
    const enc = new TextEncoder()
    return new Response(new ReadableStream({
      async start(c) {
        const stop = () => c.error(new DOMException('The operation was aborted.', 'AbortError'))
        if (signal?.aborted) return stop()
        signal?.addEventListener('abort', stop, { once: true })
        const began = Date.now()
        try {
          for (const ev of rec.events) {
            await new Promise((r) => setTimeout(r, (PACE_MS[ev.type as string] ?? 40) * scale))
            if (signal?.aborted) return
            // The recording has no pauses, so its own timestamps are all zero. The trace shows the time this visitor's replay has actually taken.
            const shown = typeof ev.t === 'number' ? { ...ev, t: Math.round((Date.now() - began) / 100) / 10 } : ev
            c.enqueue(enc.encode(`data: ${JSON.stringify(shown)}\n\n`))
            if (ev.type === 'result') { recordRun(st, id, rec.ai); save() }
          }
          c.enqueue(enc.encode('event: end\ndata: {}\n\n'))
          c.close()
        } catch { /* the reader went away */ }
      },
    }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  }

  window.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, window.location.href)
    const prefix = `${base}/api/`
    if (url.origin !== window.location.origin || !url.pathname.startsWith(prefix)) return realFetch(input, init)
    const path = url.pathname.slice(base.length)  // "/api/claims/..." with the deployment's base path removed
    const method = (init.method ?? 'GET').toUpperCase()
    const headers = new Headers(init.headers)
    const who = { role: (headers.get('X-Demo-Role') === 'senior' ? 'senior' : 'adjuster') as Role, username: headers.get('X-Demo-User') ?? 'demo' }
    const parts = path.split('/').filter(Boolean)  // ["api", "claims", id, ...]
    const { fx: f, st } = await ready()

    if (method === 'GET' && path === '/api/health') return json(200, f.health)
    if (method === 'GET' && path === '/api/topology') return json(200, f.topology)
    if (method === 'GET' && path === '/api/claims') return json(200, f.claims.map((c) => summary(f, st, c.claim_id)))
    if (method === 'GET' && path === '/api/security/attacks') return json(200, f.attacks)
    if (method === 'GET' && path === '/api/security/report') return f.report ? json(200, f.report) : json(404, { detail: 'no red team report in this recording' })
    if (method === 'POST' && path === '/api/security/scan') {
      const text = (JSON.parse(String(init.body ?? '{}')) as { text?: string }).text ?? ''
      const known = f.scans[text]
      return known ? json(200, known) : json(422, { detail: 'This demo can only scan the sample attacks. The live system runs any text through the guardrail.' })
    }
    if (parts[0] === 'api' && parts[1] === 'claims' && parts[2]) {
      const id = parts[2]
      const s = summary(f, st, id)
      if (!s) return json(404, { detail: 'unknown claim' })
      if (method === 'GET' && parts.length === 3) return json(200, { ...s, extracted: f.details[id], audit: st.claims[id]?.audit ?? [] })
      if (method === 'GET' && parts[3] === 'files') return realFetch(input, init)  // the photos and PDFs are files next to the page
      if (method === 'POST' && parts[3] === 'run') {
        const mode = url.searchParams.get('mode') ?? 'replay'
        if (mode !== 'replay') return json(409, { detail: `this deployment runs in replay mode, so a ${mode} run is not allowed` })
        return run(f, st, id, init.signal)
      }
      if (method === 'POST' && parts[3] === 'review') {
        const r = applyReview(st, id, JSON.parse(String(init.body ?? '{}')) as ReviewBody, who)
        if (r.status === 200) save()
        return json(r.status, r.body)
      }
    }
    return json(404, { detail: 'not part of the demo' })
  }) as typeof fetch

  return { reset: () => { store.clear(); state = null } }
}
