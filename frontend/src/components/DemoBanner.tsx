import { STEPS, stepStates } from '../demo/steps'

// Shown on the GitHub Pages build only, on every page including sign-in. It says what is switched off, because a visitor who thinks the agents are live has been misled.
const BASE = import.meta.env.VITE_API_URL ?? ''

export const DEMO = Boolean(import.meta.env.VITE_STATIC_DEMO)

export function DemoBanner() {
  const reset = () => { try { localStorage.removeItem('claims.demo') } catch { /* nothing saved */ } window.location.reload() }
  return (
    <div className="demo-banner" role="note">
      <span><b>Interactive demo.</b> The AI agents are switched off here to avoid cost, so each run replays the rule baseline on real claim data. Sign in with any username, run a claim, review it, and switch between adjuster and senior adjuster in the account menu to try the approval rule. The live system, with the agents on Amazon Bedrock, is shown in the <a href="https://github.com/anandapurva55/agentic-claims-adjudication-aws#readme">README</a>.</span>
      <button className="btn" onClick={reset}>Reset demo</button>
    </div>
  )
}

/** A visitor does not know to pick a claim first, so the workbench opens with the four steps, ticked off as they are done, and the next one highlighted. */
export function DemoSteps({ selected, ran, reviewed }: { selected: boolean; ran: boolean; reviewed: boolean }) {
  const states = stepStates({ selected, ran, reviewed })
  return (
    <section className="demo-steps" aria-label="How to try the demo">
      <div className="demo-steps-title">Try it</div>
      <ol>
        {STEPS.map((s, i) => (
          <li key={s.title} className={`${states[i].done ? 'done' : ''} ${states[i].current ? 'current' : ''}`} aria-current={states[i].current ? 'step' : undefined}>
            <span className="demo-step-n" aria-hidden>{states[i].done ? '\u2713' : i + 1}</span>
            <span><b>{s.title}.</b> {s.text}{'hint' in s && states[i].current && <small>{s.hint}</small>}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** The Observability tab needs real model calls to measure, so the demo shows screenshots taken on the live deployment instead of invented numbers. */
export function DemoObservability() {
  return (
    <main className="page">
      <h2>Observability</h2>
      <p className="lead">These are screenshots from the live deployment, where the agents ran on Amazon Bedrock. A recorded demo has no model calls to measure.</p>
      <img className="demo-shot" alt="Observability tab on the live deployment: run cost, latency and decisions" src={`${BASE}/demo-data/observability_top.png`} />
      <img className="demo-shot" alt="Observability tab on the live deployment: where the money goes, by agent and by model" src={`${BASE}/demo-data/observability_cost.png`} />
    </main>
  )
}
