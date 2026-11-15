import type { AgentCost, Metrics, ReviewStats } from '../types'

const usd = (n: number, d = 3) => `$${n.toFixed(d)}`
const sec = (ms: number) => `${(ms / 1000).toFixed(1)} s`
const short = (m: string) => m.replace('global.', '').replace('anthropic.', '').replace('amazon.', '').replace(/-v\d.*$/, '')

const RULES = [
  ['Cost spike', 'A run costs more than 3x the median of the previous 20 runs.'],
  ['Daily budget', "The day's model spend passes the budget."],
  ['Failure rate', 'More than 20% of the last 20 runs failed.'],
]

function Breakdown({ rows, title, note }: { rows: AgentCost[]; title: string; note: string }) {
  return (
    <section className="panel">
      <div className="panel-title">{title} <span className="muted">{note}</span></div>
      {rows.length === 0 ? <p className="muted pad">No model calls recorded yet. Run claims in Live mode.</p> : (
        <table className="est small spend">
          <thead>
            <tr><th>Name</th><th className="r">Calls</th><th className="r">Tokens in</th><th className="r">Tokens out</th><th className="r">Avg latency</th><th className="r">Cost</th><th>Share</th></tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.name}>
                <td><b>{short(a.name)}</b></td>
                <td className="r">{a.calls}</td>
                <td className="r">{a.input_tokens.toLocaleString()}</td>
                <td className="r">{a.output_tokens.toLocaleString()}</td>
                <td className="r">{sec(a.avg_latency_ms)}</td>
                <td className="r">{usd(a.cost_usd, 4)}</td>
                <td><div className="share"><i style={{ width: `${Math.max(3, a.share * 100)}%` }} /><span>{Math.round(a.share * 100)}%</span></div></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export default function MetricsView({ m, r }: { m: Metrics | null; r: ReviewStats | null }) {
  if (!m) return <p className="muted pad">Loading metrics…</p>
  const maxLat = Math.max(1, ...m.recent.map((x) => x.latency_ms))
  const maxCost = Math.max(0.0001, ...m.by_day.map((d) => d.cost_usd))
  const over = m.cost.daily_budget_usd > 0 && m.cost.today_usd > m.cost.daily_budget_usd
  const tiles = [
    { k: 'Cost per claim', v: m.cost.per_claim_avg_usd ? usd(m.cost.per_claim_avg_usd) : 'n/a', sub: m.cost.per_claim_p95_usd ? `p95 ${usd(m.cost.per_claim_p95_usd)}` : '', bad: false },
    { k: 'Spend today', v: usd(m.cost.today_usd, 2), sub: `budget ${usd(m.cost.daily_budget_usd, 2)}`, bad: over },
    { k: 'Median latency', v: sec(m.latency_ms.p50), sub: '', bad: false },
    { k: 'p95 latency', v: sec(m.latency_ms.p95), sub: `slowest ${sec(m.latency_ms.max)}`, bad: false },
    { k: 'Failure rate', v: `${(m.failure_rate * 100).toFixed(1)}%`, sub: `${m.runs} runs`, bad: m.failure_rate > 0.2 },
  ]
  const dec = Object.entries(m.decisions)
  const total = dec.reduce((a, [, v]) => a + v, 0) || 1
  return (
    <div className="metrics">
      {m.alerts.length > 0 && (
        <div className="alert alert-wide" role="alert">
          <b>{m.alerts.length} alert{m.alerts.length > 1 ? 's' : ''}.</b>
          <ul>{m.alerts.slice(0, 3).map((a) => <li key={a.ts + a.rule}><code>{a.rule}</code> {a.detail}</li>)}</ul>
        </div>
      )}
      <div className="tiles">
        {tiles.map((t) => <div key={t.k} className={`tile ${t.bad ? 'tile-bad' : ''}`}><span>{t.k}</span><b>{t.v}</b><em>{t.sub}</em></div>)}
      </div>

      <Breakdown rows={m.by_agent} title="Where the money goes" note="by agent, from every recorded model call" />
      <Breakdown rows={m.by_model} title="By model" note="each model has its own price and speed" />

      <div className="two-col">
        <section className="panel">
          <div className="panel-title">Spend per day</div>
          <div className="bars">
            {m.by_day.length === 0 && <p className="muted pad">No runs yet.</p>}
            {m.by_day.map((d) => (
              <div key={d.day} className="bar" style={{ height: `${Math.max(6, (d.cost_usd / maxCost) * 100)}%` }} title={`${d.day}: ${usd(d.cost_usd)} over ${d.runs} runs`} />
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">Latency of recent runs</div>
          <div className="bars">
            {m.recent.length === 0 && <p className="muted pad">No runs yet. Run a claim from the workbench.</p>}
            {m.recent.map((x, i) => (
              <div key={i} className={`bar ${x.ok ? '' : 'bar-bad'}`} style={{ height: `${Math.max(6, (x.latency_ms / maxLat) * 100)}%` }}
                title={`${x.claim_id}: ${sec(x.latency_ms)}${x.cost_usd ? `, ${usd(x.cost_usd)}` : ''} (${x.mode})`} />
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">Slowest model calls</div>
        {m.slowest_calls.length === 0 ? <p className="muted pad">None recorded yet.</p> : (
          <table className="est small">
            <thead><tr><th>Agent</th><th>Model</th><th>Claim</th><th className="r">Tokens in</th><th className="r">Latency</th></tr></thead>
            <tbody>
              {m.slowest_calls.map((c, i) => (
                <tr key={i}><td>{c.agent}</td><td>{short(c.model)}</td><td>{c.claim_id}</td><td className="r">{c.input_tokens.toLocaleString()}</td><td className="r">{sec(c.latency_ms)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <div className="panel-title">Alert rules <span className="muted">evaluated after every run, sent to CloudWatch</span></div>
        <ul className="rules">{RULES.map(([k, v]) => <li key={k}><b>{k}</b><span>{v}</span></li>)}</ul>
      </section>

      <section className="panel">
        <div className="panel-title">Human in the loop <span className="muted">how often people agree with the AI</span></div>
        <div className="tiles small-tiles">
          <div className="tile"><span>Reviewed</span><b>{r?.reviewed ?? 0}</b></div>
          <div className="tile"><span>Agreement rate</span><b>{r?.agreement_rate == null ? 'n/a' : `${Math.round(r.agreement_rate * 100)}%`}</b></div>
          <div className="tile"><span>Overrides</span><b>{r?.overridden ?? 0}</b></div>
          <div className="tile"><span>Escalated</span><b>{r?.escalated ?? 0}</b></div>
          <div className="tile"><span>New eval candidates</span><b>{r?.override_candidates ?? 0}</b></div>
        </div>
        <p className="muted pad small-note">Every override is saved with its reason as a candidate case for the golden set, and as a lesson in long term memory.</p>
      </section>

      <section className="panel">
        <div className="panel-title">Decision mix</div>
        <div className="mix">
          {dec.map(([k, v]) => <div key={k} className={`mix-seg v-${k}`} style={{ flex: v / total }}>{k} {v}</div>)}
          {dec.length === 0 && <p className="muted pad">No decisions yet.</p>}
        </div>
      </section>
    </div>
  )
}
