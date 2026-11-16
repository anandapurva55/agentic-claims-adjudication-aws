import { useState } from 'react'
import { DEMO_ACCOUNTS } from '../auth'
import Logo from './Logo'

// Where "Request access" writes to. Set at build time (VITE_REQUEST_ACCESS_EMAIL), so no address is stored in the repository. Unset, the link is not shown.
const REQUEST_ACCESS = (import.meta.env.VITE_REQUEST_ACCESS_EMAIL as string | undefined)?.trim()

/** A fixed example of what the reviewer works with. It is not read from any claim, so it can never show real data on a page anyone can reach. */
function PreviewCard() {
  return (
    <div className="pv" aria-hidden>
      <div className="pv-hd"><b>CLM-2026014</b><span className="pv-pill">Awaiting your review</span></div>
      <div className="pv-sec">
        <div className="pv-k">Recommendation</div>
        <div className="pv-big"><strong>Approve with depreciation</strong><span>INR 38,240</span></div>
        <div className="pv-calc"><div><span>Estimate</span><span>52,000</span></div><div><span>Depreciation, 3 years</span><span>- 9,360</span></div><div><span>Deductible</span><span>- 4,400</span></div></div>
      </div>
      <div className="pv-sec">
        <div className="pv-k">Why</div>
        <div className="pv-cite"><i>3.2</i>Own damage is covered for collision with another vehicle.</div>
        <div className="pv-cite"><i>5.1</i>Depreciation applies to parts on a sliding scale.</div>
      </div>
      <div className="pv-sec"><div className="pv-k">Risk signals</div><div className="pv-flag">Repair quote 2.1 times the typical range for a bumper</div></div>
      <div className="pv-act"><span className="on">Accept</span><span>Override</span><span>Escalate</span></div>
    </div>
  )
}

/** The interactive demo's sign-in: a form on this screen, with the demo accounts printed under it. The live site sends people to Cognito's page instead. */
function DemoForm({ onDemoSignIn }: { onDemoSignIn: (username: string, password: string) => boolean }) {
  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [bad, setBad] = useState(false)
  const submit = (e: React.FormEvent) => { e.preventDefault(); setBad(!onDemoSignIn(user, pass)) }
  return (
    <form onSubmit={submit} className="signin-form-fields">
      <label>Username<input value={user} onChange={(e) => { setUser(e.target.value); setBad(false) }} autoComplete="username" placeholder="Enter username" autoFocus /></label>
      <label>Password<input type="password" value={pass} onChange={(e) => { setPass(e.target.value); setBad(false) }} autoComplete="current-password" placeholder="Enter password" /></label>
      {bad && <p className="signin-error" role="alert">That username and password do not match a demo account.</p>}
      <button type="submit" className="signin-btn signin-primary">Sign in</button>
      <div className="signin-demo">
        <div className="signin-demo-title">Demo accounts</div>
        {DEMO_ACCOUNTS.map((a) => (
          <button type="button" key={a.username} className="signin-demo-row" onClick={() => { setUser(a.username); setPass(a.password); setBad(false) }}>
            <span><b>{a.label}</b><small>{a.role === 'senior' ? 'Can approve payouts above INR 200,000' : 'Needs a senior adjuster above INR 200,000'}</small></span>
            <code>{a.username} / {a.password}</code>
          </button>
        ))}
        <p className="signin-help">Click an account to fill it in. These are fixed demo accounts, checked in your browser.</p>
      </div>
    </form>
  )
}

/** Shown when nobody is signed in, and when someone is signed in with an account that has no role. */
export default function SignIn({ noAccess, onSignIn, onSignOut, onDemoSignIn }: { noAccess: boolean; onSignIn: () => void; onSignOut: () => void; onDemoSignIn?: (u: string, p: string) => boolean }) {
  return (
    <div className={`signin${onDemoSignIn ? ' signin-compact' : ''}`}>
      <section className="signin-form">
        <Logo size="lg" />
        <div className="signin-mid">
          {noAccess ? (
            <>
              <h1>You are signed in, but not yet allowed in.</h1>
              <p className="signin-sub">Your account is not in the adjuster or senior adjuster group. Ask an administrator to add you, then sign in again.</p>
              <button className="signin-btn" onClick={onSignOut}>Sign out</button>
            </>
          ) : (
            <>
              <h1>Review claims the agents have already worked up.</h1>
              <p className="signin-sub">Every recommendation arrives with its clauses, its calculation and its risk signals. You make the call.</p>
              {onDemoSignIn && <DemoForm onDemoSignIn={onDemoSignIn} />}
              {!onDemoSignIn && <button className="signin-btn signin-primary" onClick={onSignIn}>Continue with your account</button>}
              {!onDemoSignIn && <p className="signin-help">Accounts are created by an administrator. You will go to a secure sign-in page and come straight back.
                {REQUEST_ACCESS && <> No account? <a href={`mailto:${REQUEST_ACCESS}?subject=${encodeURIComponent('Access request: Claims Adjudication Copilot')}`}>Request access</a>.</>}</p>}
            </>
          )}
        </div>
        <div className="signin-legal"><span>{import.meta.env.VITE_STATIC_DEMO ? 'Interactive demo, agents off' : 'Private deployment'}</span><span>Every decision is logged</span></div>
      </section>
      <section className="signin-preview">
        <div className="signin-cap">What you will see</div>
        <PreviewCard />
      </section>
    </div>
  )
}
