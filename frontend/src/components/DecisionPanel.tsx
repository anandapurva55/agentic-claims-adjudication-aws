import { useEffect, useRef, useState } from 'react'
import type { Claim, Role, RunResult } from '../types'

const inr = (n: number) => `₹${n.toLocaleString('en-IN')}`
const LABEL = { approve: 'Approve', deny: 'Deny', refer: 'Refer to senior adjuster' } as const
const LIMIT = 200000

interface Props {
  claim: Claim | null
  result: RunResult | null
  error: string
  running?: boolean
  role: Role
  outcome: string
  onReview: (b: { action: string; final_decision?: string; note?: string }) => Promise<void>
}

export default function DecisionPanel({ claim, result, error, running, role, outcome, onReview }: Props) {
  const root = useRef<HTMLElement>(null)
  const [note, setNote] = useState('')
  const [override, setOverride] = useState('deny')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { setNote(''); setMsg('') }, [claim?.claim_id])
  useEffect(() => { if (result) root.current?.scrollTo({ top: 0, behavior: 'smooth' }) }, [result])

  const act = async (b: { action: string; final_decision?: string }) => {
    setBusy(true); setMsg('')
    try { await onReview({ ...b, note }) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  if (!result && claim?.stage === 'reviewed' && claim.review) {
    return <section className="panel decision"><div className="panel-title">Human decision</div><Done claim={claim} outcome={outcome} /></section>
  }
  if (error && !result) return <section className="panel decision"><div className="panel-title">Decision</div><p className="err pad">{error}</p></section>
  if (!result && running) return <section className="panel decision" ref={root}><div className="panel-title">Agents working</div><div className="skel skel-big" /><div className="skel" /><div className="skel" style={{ width: '70%' }} /><div className="skel" style={{ width: '85%' }} /></section>
  if (!result) return <section className="panel decision" ref={root}><div className="panel-title">Decision</div><p className="muted pad">Run the agents. Their recommendation, evidence and a human sign-off step appear here.</p></section>

  const d = result.decision
  const overLimit = d.clauses.includes('INT.AUTH')
  const blocked = overLimit && role !== 'senior'
  const reviewed = claim?.stage === 'reviewed'

  return (
    <section className="panel decision" ref={root}>
      <div className="panel-title">AI recommendation <span className="muted">{result.mode === 'live' ? 'live on Bedrock' : 'replay baseline'}</span></div>
      <div className={`verdict v-${d.decision}`}>
        <span className="v-word">{LABEL[d.decision]}</span>
        {d.payable > 0 && <span className="v-amt">{inr(d.payable)}</span>}
      </div>
      <div className="cites">{d.clauses.map((c) => <span key={c} className="chip chip-cite">{c}</span>)}</div>

      <div className={`next next-${d.decision}`}>
        <span className="lbl">{d.decision === 'refer' ? 'Why this needs a person, and what to do' : 'Next step'}</span>
        <ul>{d.next_steps.map((n) => <li key={n}>{n}</li>)}</ul>
      </div>

      <Gate stage={reviewed ? 'reviewed' : 'waiting'} overLimit={overLimit} />

      {result.guardrail.alerts.length > 0 && (
        <div className="alert" role="alert">
          <b>Prompt injection blocked.</b> {result.guardrail.alerts.length} sentence(s) in the narrative tried to instruct the AI.
          They were removed before any agent read them.
          <blockquote>{result.guardrail.alerts[0]}</blockquote>
        </div>
      )}

      <h4>Human decision</h4>
      {reviewed && claim?.review ? (
        <Done claim={claim} outcome={outcome} />
      ) : (
        <div className="hitl">
          <p className="hitl-rule">
            {overLimit
              ? <>Payable is above <b>{inr(LIMIT)}</b>. A <b>senior adjuster</b> must approve. You are signed in as <b>{role}</b>.</>
              : <>Nothing is paid or denied until you decide. You are signed in as <b>{role}</b>.</>}
          </p>
          <textarea className="note" placeholder="Reason (required if you override, kept in the audit trail)" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="actions">
            <button className="btn btn-primary" disabled={busy || blocked} onClick={() => act({ action: 'accept' })}
              title={blocked ? 'Needs a senior adjuster' : 'Agree with the AI recommendation'}>
              {blocked ? 'Needs senior approval' : 'Accept recommendation'}
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => act({ action: 'escalate' })}>Escalate</button>
          </div>
          <div className="override">
            <span className="lbl">Disagree? Override with</span>
            <select value={override} onChange={(e) => setOverride(e.target.value)} aria-label="Override decision">
              <option value="approve">approve</option><option value="deny">deny</option><option value="refer">refer</option>
            </select>
            <button className="btn" disabled={busy || note.trim().length < 10} onClick={() => act({ action: 'override', final_decision: override })}
              title={note.trim().length < 10 ? 'Write a reason first' : ''}>Override</button>
          </div>
          {msg && <p className="err" role="alert">{msg}</p>}
        </div>
      )}

      <h4>Adjudicator memo</h4>
      <details className="cite memo" open={result.mode === 'live'}>
        <summary><b>{result.mode === 'live' ? 'Written by the adjudicator agent' : 'Generated from the rules engine'}</b></summary>
        <pre className="memo-text">{result.memo}</pre>
      </details>

      {result.signals?.length > 0 && (
        <>
          <h4>Risk signals <span className="muted tiny">advisory, they inform you and never decide</span></h4>
          <ul className="signals">
            {result.signals.map((g) => <li key={g.detail} className={`sig sig-${g.severity}`}><b>{g.severity}</b> {g.kind.replace('_', ' ')}<span>{g.detail}</span></li>)}
          </ul>
        </>
      )}

      {result.lessons?.length > 0 && (
        <>
          <h4>Memory the AI recalled <span className="muted tiny">lessons from human adjusters</span></h4>
          {result.lessons.map((l) => <div key={l.text} className="lesson">{l.text}</div>)}
        </>
      )}

      {result.notes?.length > 0 && (
        <>
          <h4>Agent conversation <span className="muted tiny">short term memory for this claim</span></h4>
          <ul className="convo">
            {result.notes.map((n, i) => <li key={i} className={`c-${n.kind}`}><b>{n.sender} to {n.to}</b> <i>{n.kind}</i><span>{n.text}</span></li>)}
          </ul>
        </>
      )}

      <h4>Checks performed</h4>
      <ol className="steps">{d.steps.map((s) => <li key={s.check}><b>{s.check}</b><span>{s.result}</span></li>)}</ol>

      {result.calc.lines.length > 0 && d.payable > 0 && (
        <>
          <h4>How the amount was calculated</h4>
          <table className="est small">
            <thead><tr><th>Item</th><th className="r">Cost</th><th className="r">Dep.</th><th className="r">Net</th></tr></thead>
            <tbody>
              {result.calc.basis === 'partial_loss' && result.calc.lines.map((l) => (
                <tr key={l.item}><td>{l.item}</td><td className="r">{inr(l.cost)}</td><td className="r">{l.depreciation_pct}%</td><td className="r">{inr(l.net)}</td></tr>))}
              {result.calc.basis !== 'partial_loss' && <tr><td>{result.calc.basis === 'theft' ? 'Theft: IDV' : 'Total loss: IDV'}</td><td className="r" colSpan={3}>{inr(result.calc.idv)}</td></tr>}
              {result.calc.basis === 'partial_loss' && <tr><td>Labour</td><td className="r" colSpan={3}>{inr(result.calc.labour)}</td></tr>}
              {result.calc.salvage > 0 && <tr><td>Less salvage</td><td className="r" colSpan={3}>-{inr(result.calc.salvage)}</td></tr>}
              <tr><td>Less deductible</td><td className="r" colSpan={3}>-{inr(result.calc.deductible)}</td></tr>
              <tr className="tot"><td>Payable</td><td className="r" colSpan={3}>{inr(result.calc.payable)}</td></tr>
            </tbody>
          </table>
        </>
      )}

      <h4>Policy clauses relied on</h4>
      {result.citations.map((c) => (
        <details key={c.clause} className="cite"><summary><b>{c.clause}</b> <span className="muted">{c.source}</span></summary><p>{c.text}</p></details>
      ))}
    </section>
  )
}

function Gate({ stage, overLimit }: { stage: 'waiting' | 'reviewed'; overLimit: boolean }) {
  const steps = [
    { k: 'AI recommends', done: true },
    { k: overLimit ? 'Senior sign-off' : 'Human sign-off', done: stage === 'reviewed' },
    { k: 'Outcome released', done: stage === 'reviewed' },
  ]
  return (
    <ol className="gate" aria-label="Approval progress">
      {steps.map((s, i) => (
        <li key={s.k} className={s.done ? 'g-done' : i === 1 ? 'g-wait' : ''}>
          <span className="g-dot">{s.done ? '✓' : i + 1}</span>{s.k}
        </li>
      ))}
    </ol>
  )
}

function Done({ claim, outcome }: { claim: Claim; outcome: string }) {
  const r = claim.review
  if (!r) return null
  const verb = r.action === 'accept' ? 'accepted the AI recommendation' : r.action === 'override' ? `overrode the AI (${r.ai_decision ?? claim.ai?.decision ?? ''}) and decided ${r.final}` : 'escalated this claim'
  return (
    <div className="decided">
      <p className="ok-note"><b>{r.reviewer}</b> ({r.role}) {verb}.</p>
      {outcome && <p className="outcome">{outcome}</p>}
      {r.note && <blockquote className="reason">{r.note}</blockquote>}
      <p className="muted small-note">Recorded in the audit trail. {r.action === 'override' ? 'This override is now a candidate case for the next eval run.' : ''}</p>
    </div>
  )
}
