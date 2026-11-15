import { useMemo, useState } from 'react'
import type { Claim } from '../types'

interface Props { claims: Claim[]; selected: string | null; onSelect: (id: string) => void }

const inr = (n: number) => `₹${n.toLocaleString('en-IN')}`

export default function ClaimQueue({ claims, selected, onSelect }: Props) {
  const [q, setQ] = useState('')
  const [f, setF] = useState<'all' | 'open' | 'done'>('all')
  const rows = useMemo(
    () => claims.filter((c) => `${c.claim_id} ${c.holder} ${c.vehicle}`.toLowerCase().includes(q.toLowerCase()))
      .filter((c) => f === 'all' || (f === 'done' ? c.stage === 'reviewed' : c.stage !== 'reviewed')),
    [claims, q, f],
  )
  const done = claims.filter((c) => c.stage === 'reviewed').length
  const waiting = claims.filter((c) => c.stage === 'ai_recommended').length
  return (
    <aside className="queue">
      <div className="panel-title">Claim queue <span className="muted">{done}/{claims.length} reviewed</span></div>
      {waiting > 0 && <div className="waiting-banner">{waiting} awaiting human sign-off</div>}
      <div className="filters" role="tablist">
        {([['all', 'All'], ['open', 'Open'], ['done', 'Reviewed']] as const).map(([k, l]) => (
          <button key={k} className={f === k ? 'on' : ''} onClick={() => setF(k)}>{l}</button>))}
      </div>
      <input className="search" placeholder="Search claim, holder, vehicle" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search claims" />
      <ul className="queue-list">
        {rows.map((c) => (
          <li key={c.claim_id}>
            <button className={`queue-item ${selected === c.claim_id ? 'sel' : ''}`} onClick={() => onSelect(c.claim_id)}>
              <span className="qi-top">
                <b>{c.claim_id}</b>
                {c.stage === 'reviewed' ? <span className="chip chip-ok">{c.review?.action === 'accept' ? 'accepted' : c.review?.action === 'override' ? 'overridden' : 'escalated'}</span>
                  : c.stage === 'ai_recommended' ? <span className="chip chip-wait">needs you</span> : <span className="chip">new</span>}
              </span>
              <span className="qi-mid">{c.holder}</span>
              <span className="qi-bot">{c.vehicle} · {inr(c.claimed_amount)}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}
