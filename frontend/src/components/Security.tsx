import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Report } from '../types'

const TYPES: Record<string, string> = {
  override: 'Instruction override', hidden_document: 'Hidden text in a document',
  secret_extraction: 'Secret extraction', tool_misuse: 'Tool misuse', memory_poisoning: 'Memory poisoning', plausible_fabrication: 'Plausible fabrication',
}
const LAYERS = [
  ['1', 'Input guardrail', 'Bedrock Guardrails scans untrusted text for prompt attacks. Offending sentences are removed, the rest is kept.'],
  ['2', 'Data, not instructions', 'Agent prompts state that the narrative is data. Instructions inside it are reported, never followed.'],
  ['3', 'Least privilege tools', 'Agents can only read this claim. No tool writes money, edits policies or reaches other customers.'],
  ['4', 'Code makes the decision', 'Agents only set judgement flags. A deterministic engine applies the rules, so a hijacked agent cannot invent a payout.'],
  ['5', 'Human in the loop', 'Every recommendation is approved or overridden by an adjuster, and every step is written to the audit log.'],
  ['6', 'Memory is human write only', 'Agents can recall lessons but have no tool to write them. Only a human review, scanned by the guardrail, can add to long term memory.'],
]
const pct = (n: number) => `${Math.round(n * 100)}%`

export default function Security() {
  const [attacks, setAttacks] = useState<{ id: string; type: string; payload: string }[]>([])
  const [text, setText] = useState('The driver was rear ended at a signal. ')
  const [res, setRes] = useState<{ clean: string; alerts: string[]; engine: string } | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.attacks().then(setAttacks).catch(() => undefined)
    api.report().then(setReport).catch(() => undefined)
  }, [])

  const scan = async () => {
    setBusy(true); setErr('')
    try { setRes(await api.scan(text)) } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }
  const pick = (id: string) => {
    const a = attacks.find((x) => x.id === id)
    if (a) { setText('The driver was rear ended at a signal. ' + a.payload); setRes(null) }
  }
  const on = report?.summary.defences_on
  const off = report?.summary.defences_off

  return (
    <div className="sec">
      <div className="sec-grid">
        <section className="panel">
          <div className="panel-title">Attack lab <span className="muted">try to hijack the AI</span></div>
          <div className="lab">
            <label className="lbl">Load a sample attack</label>
            <select onChange={(e) => pick(e.target.value)} defaultValue="" aria-label="Sample attacks">
              <option value="" disabled>Choose from the 30 red team attacks</option>
              {Object.keys(TYPES).map((t) => (
                <optgroup key={t} label={TYPES[t]}>
                  {attacks.filter((a) => a.type === t).map((a) => <option key={a.id} value={a.id}>{a.id}</option>)}
                </optgroup>
              ))}
            </select>
            <label className="lbl">Incident narrative (untrusted customer text)</label>
            <textarea className="note big" value={text} onChange={(e) => { setText(e.target.value); setRes(null) }} />
            <button className="btn btn-primary" onClick={scan} disabled={busy || !text.trim()}>{busy ? 'Scanning…' : 'Scan with guardrail'}</button>
            {err && <p className="err">{err}</p>}
            {res && (
              <div className={`scan ${res.alerts.length ? 'scan-bad' : 'scan-ok'}`} role="status">
                <b>{res.alerts.length ? `Blocked: ${res.alerts.length} sentence(s) removed` : 'Clean: nothing to remove'}</b>
                <span className="muted"> engine: {res.engine}</span>
                <p className="scan-text">{res.clean}</p>
                {res.alerts.map((a) => <blockquote key={a}>Removed: {a}</blockquote>)}
                {res.engine === 'replay-heuristic' && !res.alerts.length && (
                  <p className="muted">The offline heuristic is simple. In live mode Bedrock Guardrails scans with a trained classifier.</p>
                )}
              </div>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">Red team results {report && <span className="muted">{report.n_attacks} attacks · {report.mode}</span>}</div>
          {!report && <p className="muted pad">No report yet. Run <code>python redteam/run.py</code>.</p>}
          {report && on && off && (
            <div className="rt">
              <div className="tiles small-tiles">
                <div className="tile"><span>Attacks detected</span><b>{pct(on.overall.detection_rate)}</b></div>
                <div className="tile"><span>Success, defences on</span><b>{pct(on.overall.attack_success_rate)}</b></div>
                <div className="tile"><span>Success, defences off</span><b>{pct(off.overall.attack_success_rate)}</b></div>
              </div>
              <table className="est small">
                <thead><tr><th>Attack type</th><th className="r">Detected</th><th className="r">Succeeded on</th><th className="r">Succeeded off</th></tr></thead>
                <tbody>
                  {Object.keys(on.by_type).map((t) => (
                    <tr key={t}><td>{TYPES[t] ?? t}</td><td className="r">{on.by_type[t].detected}/{on.by_type[t].attacks}</td>
                      <td className="r">{on.by_type[t].succeeded}</td><td className="r">{off.by_type[t].succeeded}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="muted pad small-note">{report.note}</p>
            </div>
          )}
        </section>
      </div>

      <h3 className="layers-h">Defence in depth</h3>
      <div className="layers">
        {LAYERS.map(([n, t, d]) => <article key={n}><span className="ln">{n}</span><h4>{t}</h4><p>{d}</p></article>)}
      </div>
    </div>
  )
}
