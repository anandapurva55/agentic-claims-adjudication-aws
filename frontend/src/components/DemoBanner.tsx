// Shown on the GitHub Pages build only. It says what this site is, because a visitor who thinks they are watching live agents has been misled.
const BASE = import.meta.env.VITE_API_URL ?? ''

export const DEMO = Boolean(import.meta.env.VITE_STATIC_DEMO)

export function DemoBanner() {
  const reset = () => { try { localStorage.removeItem('claims.demo') } catch { /* nothing saved */ } window.location.reload() }
  return (
    <div className="demo-banner" role="note">
      <span><b>Recorded demo.</b> The AI agents are not running here, to avoid cost. Each run replays a recording of the rule baseline on real claim data, and your reviews stay
        in this browser. The live system, with the agents on Amazon Bedrock, is shown in the demos in the <a href="https://github.com/anandapurva55/agentic-claims-adjudication-aws#readme">README</a>.</span>
      <button className="btn" onClick={reset}>Reset demo</button>
    </div>
  )
}

/** The Observability tab needs a running system, so the demo shows screenshots taken on the live deployment instead of invented numbers. */
export function RecordedObservability() {
  return (
    <main className="page">
      <h2>Observability</h2>
      <p className="lead">These are screenshots from the live deployment, where the agents ran on Amazon Bedrock. A recorded demo has no model calls to measure.</p>
      <img className="recorded-shot" alt="Observability tab on the live deployment: run cost, latency and decisions" src={`${BASE}/demo-data/observability_top.png`} />
      <img className="recorded-shot" alt="Observability tab on the live deployment: where the money goes, by agent and by model" src={`${BASE}/demo-data/observability_cost.png`} />
    </main>
  )
}
