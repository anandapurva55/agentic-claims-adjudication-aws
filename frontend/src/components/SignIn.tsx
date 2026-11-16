import { useState } from 'react'
import { PASSWORD_RULES } from '../authlib'
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

/** The demo's stand-in for Cognito's sign-in page, laid out like the real one: the form on the left, the example review card on the right. */
function DemoHostedLogin({ onDemoSignIn }: { onDemoSignIn: (username: string, password: string) => string | null }) {
  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  // The checklist already shows what a password lacks, so only a problem it cannot show (no username) is spelled out.
  const submit = (e: React.FormEvent) => { e.preventDefault(); const problem = onDemoSignIn(user, pass); setError(problem && PASSWORD_RULES.every((r) => r.ok(pass)) ? problem : '') }
  return (
    <div className="signin">
      <section className="signin-form">
        <Logo size="lg" />
        <div className="signin-mid">
          <h1>Sign in</h1>
          <p className="signin-sub">Sign in to your account.</p>
          <form onSubmit={submit} className="signin-form-fields">
            <label>Username<input value={user} onChange={(e) => { setUser(e.target.value); setError('') }} autoComplete="username" placeholder="Enter username" autoFocus /></label>
            <label>Password<input type={show ? 'text' : 'password'} value={pass} onChange={(e) => { setPass(e.target.value); setError('') }} autoComplete="current-password" placeholder="Enter password" /></label>
            <label className="signin-show"><input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />Show password</label>
            {pass.length > 0 && (  // the checklist appears when the person starts typing, not before
              <ul className="pw-rules" aria-label="Password rules" aria-live="polite">
                {PASSWORD_RULES.map((r) => {
                  const ok = r.ok(pass)
                  return <li key={r.need} className={ok ? 'ok' : 'bad'}><span aria-hidden>{ok ? '\u2713' : '\u2717'}</span>{r.need[0].toUpperCase() + r.need.slice(1)}<span className="sr-only">{ok ? ', met' : ', not met'}</span></li>
                })}
              </ul>
            )}
            {error && <p className="signin-error" role="alert">{error}</p>}
            <button type="submit" className="signin-btn signin-primary">Sign in</button>
          </form>
        </div>
        <div className="signin-legal" />
      </section>
      <section className="signin-preview">
        <div className="signin-cap">What you will see</div>
        <PreviewCard />
      </section>
    </div>
  )
}

/** Shown when nobody is signed in, and when someone is signed in with an account that has no role. */
export default function SignIn({ noAccess, onSignIn, onSignOut, onDemoSignIn }: { noAccess: boolean; onSignIn: () => void; onSignOut: () => void; onDemoSignIn?: (u: string, p: string) => string | null }) {
  const [hosted, setHosted] = useState(false)  // the demo's stand-in for Cognito's page, shown after "Continue with your account"
  if (onDemoSignIn && hosted) return <DemoHostedLogin onDemoSignIn={onDemoSignIn} />
  return (
    <div className="signin">
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
              <button className="signin-btn signin-primary" onClick={onDemoSignIn ? () => setHosted(true) : onSignIn}>Continue with your account</button>
              <p className="signin-help">There is no sign up: an administrator provides your credentials. You will go to a secure sign-in page and come straight back.
                {REQUEST_ACCESS && <> {onDemoSignIn ? 'Want a login for the live system?' : 'No account?'} <a href={`mailto:${REQUEST_ACCESS}?subject=${encodeURIComponent('Access request: Claims Adjudication Copilot')}`}>Request access</a>.</>}</p>
            </>
          )}
        </div>
        <div className="signin-legal"><span>{onDemoSignIn ? 'Interactive demo, agents off' : 'Private deployment'}</span><span>Every decision is logged</span></div>
      </section>
      <section className="signin-preview">
        <div className="signin-cap">What you will see</div>
        <PreviewCard />
      </section>
    </div>
  )
}
