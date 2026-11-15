import type { Claim } from '../types'

interface Extracted {
  narrative?: string; lines?: { name: string; category: string; cost: number }[]; labour?: number
  estimate_total?: number; report_date?: string; police_fir?: boolean | null; estimate_reg?: string; salvage?: number
  photo?: { parts: string[]; severity?: string; description?: string; engine?: string } | null
}
const inr = (n?: number) => (n === undefined ? '' : `₹${n.toLocaleString('en-IN')}`)

export default function PacketView({ claim, extracted, apiBase }: { claim: Claim | null; extracted: Extracted | null; apiBase: string }) {
  if (!claim) return <section className="panel"><div className="panel-title">Claim packet</div><p className="muted pad">Select a claim.</p></section>
  const ex = extracted ?? {}
  return (
    <section className="panel packet">
      <div className="panel-title">Claim packet <span className="muted">extracted by Bedrock Data Automation</span></div>
      <div className="packet-grid">
        <dl className="fields">
          <dt>Claim</dt><dd>{claim.claim_id}</dd>
          <dt>Policy</dt><dd>{claim.policy_no}</dd>
          <dt>Holder</dt><dd>{claim.holder}</dd>
          <dt>Vehicle</dt><dd>{claim.vehicle} · {claim.vehicle_reg}</dd>
          <dt>Incident</dt><dd>{claim.incident_date}{ex.report_date ? ` (reported ${ex.report_date})` : ''}</dd>
          <dt>Claimed</dt><dd>{inr(claim.claimed_amount)}</dd>
          <dt>Police FIR</dt><dd>{ex.police_fir === null || ex.police_fir === undefined ? 'Not applicable' : ex.police_fir ? 'Filed' : 'Not filed'}</dd>
        </dl>
        <div className="evidence">
          {ex.photo ? (
            <>
              <img className="photo" alt="Damage evidence" src={`${apiBase}/api/claims/${claim.claim_id}/files/damage_photo.jpg`} />
              <div className="chips">
                {ex.photo.parts.length ? ex.photo.parts.map((p) => <span key={p} className="chip">{p.replace('_', ' ')}</span>) : <span className="chip">no listed part</span>}
                {ex.photo.severity && <span className="chip sev">{ex.photo.severity}</span>}
              </div>
              <span className="muted small">Read by Bedrock Data Automation and a vision model</span>
            </>
          ) : <div className="nophoto">No damage photo on this claim</div>}
        </div>
      </div>
      <div className="narr"><span className="lbl">Incident narrative</span>{ex.narrative ?? ''}</div>
      {ex.lines && (
        <table className="est">
          <thead><tr><th>Estimate line</th><th>Type</th><th className="r">Cost</th></tr></thead>
          <tbody>
            {ex.lines.map((l) => <tr key={l.name}><td>{l.name}</td><td>{l.category}</td><td className="r">{inr(l.cost)}</td></tr>)}
            <tr><td>Labour and paint</td><td></td><td className="r">{inr(ex.labour)}</td></tr>
            <tr className="tot"><td>Estimate total</td><td></td><td className="r">{inr(ex.estimate_total)}</td></tr>
          </tbody>
        </table>
      )}
    </section>
  )
}
