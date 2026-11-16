import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { currentSession, demoSwitchRole, setDemoRole, signOut } from './auth'
import AgentGraph, { type NodeInfo } from './components/AgentGraph'
import ClaimQueue from './components/ClaimQueue'
import { DEMO, DemoObservability } from './components/DemoBanner'
import Logo from './components/Logo'
import UserMenu from './components/UserMenu'
import DecisionPanel from './components/DecisionPanel'
import MetricsView from './components/Metrics'
import Security from './components/Security'
import PacketView from './components/PacketView'
import Trace from './components/Trace'
import type { Claim, Health, Metrics, Pulse, ReviewStats, Role, RunResult, TraceLine, Topology } from './types'

type Tab = 'workbench' | 'architecture' | 'security' | 'observability'
const BASE = import.meta.env.VITE_API_URL ?? ''
const PULSE_MS = 1500

export default function App() {
  const [tab, setTab] = useState<Tab>('workbench')
  const [topo, setTopo] = useState<Topology | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [claims, setClaims] = useState<Claim[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [extracted, setExtracted] = useState<Record<string, unknown> | null>(null)
  const [states, setStates] = useState<Record<string, NodeInfo>>({})
  const [pulses, setPulses] = useState<Pulse[]>([])
  const [trace, setTrace] = useState<TraceLine[]>([])
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [mode, setMode] = useState('replay')
  const [queued, setQueued] = useState<number | null>(null)  // this run's place in the line behind other runs, when it has to wait for its turn
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const session = currentSession()
  const [role, setRole] = useState<Role>(session?.role ?? 'adjuster')
  const [outcome, setOutcome] = useState('')
  const [rstats, setRstats] = useState<ReviewStats | null>(null)
  const [autorun, setAutorun] = useState(false)
  const [still, setStill] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const ids = useRef(0)

  const loadClaims = useCallback(() => api.claims().then(setClaims).catch((e) => setError(String(e))), [])

  useEffect(() => {
    api.topology().then(setTopo).catch((e) => setError(String(e)))
    api.health().then((h) => { setHealth(h); setMode(h.mode) }).catch(() => undefined)
    loadClaims()
  }, [loadClaims])

  // Deep link for demos and screenshots: ?claim=CLM-2026001&autorun=1
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    const tb = q.get('tab')
    if (tb === 'workbench' || tb === 'architecture' || tb === 'security' || tb === 'observability') setTab(tb)
    if (q.get('demo') === 'bolts') {
      // Frozen mid-run frame: used for the README hero image and visual checks.
      setStill(true)
      setStates({
        upload: { state: 'done', detail: '3 files received' }, bda: { state: 'done', detail: 'fields extracted' },
        guardrail: { state: 'alert', detail: 'prompt attack blocked' }, intake: { state: 'done', detail: 'intoxicated' },
        policy: { state: 'active', detail: 'matching clauses' }, fraud: { state: 'active', detail: 'cross checking' },
        kb: { state: 'active', detail: 'retrieving clauses' }, calc: { state: 'idle', detail: '' },
      })
      setPulses([{ id: 1, src: 'intake', dst: 'policy' }, { id: 2, src: 'intake', dst: 'fraud' }, { id: 3, src: 'policy', dst: 'kb' }, { id: 4, src: 'guardrail', dst: 'intake' }])
      return
    }
    const id = q.get('claim')
    if (!id) return
    select(id)
    if (q.get('autorun')) { setTimeout(() => setAutorun(true), 400) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { if (tab === 'observability') { api.metrics().then(setMetrics).catch(() => undefined); api.reviewStats().then(setRstats).catch(() => undefined) } }, [tab, running, claims])

  const select = (id: string) => {
    abort.current?.abort()
    setRunning(false); setSelected(id); setResult(null); setError(''); setStates({}); setPulses([]); setTrace([]); setOutcome('')
    api.claim(id).then((c) => {
      setExtracted(c.extracted)
      const o = [...c.audit].reverse().find((a) => a.action === 'outcome')
      if (o?.detail.message) setOutcome(o.detail.message)
      if (c.stage === 'reviewed') setStates({ human: { state: 'done', detail: c.review?.action ?? '' } })
    }).catch((e) => setError(String(e)))
  }

  const addTrace = (t: number, node: string, text: string, kind: TraceLine['kind']) =>
    setTrace((l) => [...l, { id: ++ids.current, t, node, text, kind }])

  const run = () => {
    if (!selected) return
    abort.current?.abort()
    setResult(null); setError(''); setStates({}); setPulses([]); setTrace([]); setRunning(true)
    const ctl = new AbortController()
    abort.current = ctl
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const onEvent = (ev: any) => {
      switch (ev.type) {
        case 'node':
          setStates((s) => ({ ...s, [ev.id]: { state: ev.state, detail: ev.detail ?? '' } }))
          if (ev.state === 'active' || ev.state === 'alert') addTrace(ev.t, ev.id, ev.detail || ev.state, 'node')
          break
        case 'edge': {
          const p = { id: ++ids.current, src: ev.src, dst: ev.dst }
          setPulses((x) => [...x, p])
          setTimeout(() => setPulses((x) => x.filter((q) => q.id !== p.id)), PULSE_MS)
          break
        }
        case 'log': addTrace(ev.t, ev.node, ev.text, 'log'); break
        case 'tool': addTrace(ev.t, ev.node, `tool ${ev.tool}`, 'tool'); break
        case 'note': addTrace(ev.t, ev.sender, `${ev.kind} to ${ev.to}: ${ev.text}`, 'tool'); break
        case 'queued':
          setQueued((q) => { if (q === null) addTrace(0, 'system', `Waiting for another run to finish (place ${ev.position} in line)`, 'log'); return ev.position })
          break
        case 'start': setQueued(null); break
        case 'result': setResult(ev as RunResult); break
        case 'error': setError(ev.message); addTrace(ev.t, 'system', ev.message, 'error'); break
      }
    }
    api.run(selected, mode, onEvent, ctl.signal)
      .catch((e: Error) => { if (!ctl.signal.aborted) setError(e.message) })  // includes the 429 text when the daily spend limit is reached
      .finally(() => { if (abort.current === ctl) { setRunning(false); setQueued(null) } })
  }

  useEffect(() => { if (autorun) { setAutorun(false); run() } }, [autorun]) // eslint-disable-line react-hooks/exhaustive-deps

  const review = async (b: { action: string; final_decision?: string; note?: string }) => {
    if (!selected || !result) return
    const r = await api.review(selected, { ...b, run_id: result.run_id })  // the run the reviewer is looking at
    setOutcome(r.outcome + (r.lesson_stored ? ' Your reason was saved to long term memory, so the agents can recall it on similar claims.' : ''))
    setStates((s) => ({ ...s, human: { state: 'done', detail: b.action === 'accept' ? 'accepted' : b.action } }))
    // The human decision is written back to the audit store: show it as a bolt.
    const p = { id: ++ids.current, src: 'human', dst: 'ddb' }
    setPulses((x) => [...x, p])
    setStates((s) => ({ ...s, ddb: { state: 'done', detail: 'decision logged' } }))
    setTimeout(() => setPulses((x) => x.filter((q) => q.id !== p.id)), PULSE_MS)
    addTrace(0, 'human', `${role} ${b.action}${b.final_decision ? ' as ' + b.final_decision : ''}: ${r.outcome}`, 'node')
    await loadClaims()
  }

  const claim = claims.find((c) => c.claim_id === selected) ?? null

  return (
    <div className="app">
      <header className="top">
        <div className="brand"><Logo /></div>
        <nav>
          {(['workbench', 'architecture', 'security', 'observability'] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
        <div className="env">
          {!session && (
            // Local development only: sign-in is off, so the role is picked here and sent as a demo header.
            <label className="role" title="Development mode: sign-in is off. Payouts above the authority limit need a senior adjuster.">
              <span className="muted">Demo role</span>
              <select value={role} onChange={(e) => { setDemoRole(e.target.value as Role); setRole(e.target.value as Role) }} aria-label="Role">
                <option value="adjuster">Adjuster</option><option value="senior">Senior adjuster</option>
              </select>
            </label>
          )}
          {health && <><span className="chip">{health.region}</span><span className={`chip ${health.mode === 'live' ? 'chip-ok' : ''}`}>{health.mode}</span></>}
          {session && <UserMenu name={session.username} role={role} onSignOut={signOut} onSwitchRole={DEMO ? (r) => { demoSwitchRole(r); setRole(r) } : undefined} />}
        </div>
      </header>

      {tab === 'workbench' && topo && (
        <main className="wb">
          <ClaimQueue claims={claims} selected={selected} onSelect={select} />
          <div className="center">
            <div className="toolbar">
              <div><b>{claim ? claim.claim_id : 'Select a claim'}</b>{claim && <span className="muted"> · {claim.holder}</span>}</div>
              <div className="ctrls">
                <span className={`chip ${mode === 'live' ? 'chip-ok' : ''}`} title="A deployment runs in one mode, set by whoever deployed it">{mode === 'live' ? 'Live (Bedrock agents)' : 'Replay (rule baseline)'}</span>
                <button className="btn btn-primary" disabled={!selected || running} onClick={run}>{running ? (queued !== null ? `Waiting, place ${queued} in line…` : 'Running…') : 'Run agents'}</button>
              </div>
            </div>
            <AgentGraph topology={topo} states={states} pulses={pulses} still={still} />
            <div className="two">
              <PacketView claim={claim} extracted={extracted as never} apiBase={BASE} />
              <Trace lines={trace} running={running} />
            </div>
          </div>
          <DecisionPanel claim={claim} result={result} error={error} running={running} role={role} outcome={outcome} onReview={review} />
        </main>
      )}

      {tab === 'architecture' && topo && (
        <main className="page">
          <h2>How a claim flows</h2>
          <p className="lead">Every box below is a real component. In the workbench the same graph lights up as the claim moves through it.
            Agents judge the text. Deterministic tools do the arithmetic. A human makes the final call.</p>
          <AgentGraph topology={topo} states={{}} pulses={[]} />
          <div className="cards">
            <article><h3>Agents decide, code calculates</h3><p>Language models read the narrative and apply policy wording. Depreciation, deductibles and total loss rules run as exact code, so money is never guessed.</p></article>
            <article><h3>Untrusted text is quarantined</h3><p>The incident narrative is customer controlled. A guardrail removes injected instructions before any agent reads it.</p></article>
            <article><h3>Humans stay in charge</h3><p>Every recommendation carries clause citations and a calculation trail. Approve, override or escalate, all written to an audit log.</p></article>
          </div>
        </main>
      )}

      {tab === 'security' && <main className="page"><h2>Security</h2><p className="lead">Customer text is untrusted. Try to hijack the AI below, then see how the layers contain it.</p><Security /></main>}

      {tab === 'observability' && DEMO && <DemoObservability />}
      {tab === 'observability' && !DEMO && <main className="page"><h2>Observability</h2><MetricsView m={metrics} r={rstats} /></main>}
    </div>
  )
}
