import { useEffect, useRef } from 'react'
import type { TraceLine } from '../types'

export default function Trace({ lines, running }: { lines: TraceLine[]; running: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  // Follow new lines inside the trace box only, and only while the reader is already at the bottom.
  useEffect(() => {
    const el = box.current
    if (!el) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [lines.length])
  return (
    <section className="panel trace">
      <div className="panel-title">Reasoning trace {running && <span className="live"><i />live</span>}</div>
      <div className="trace-body" role="log" aria-live="polite" ref={box}>
        {lines.length === 0 && <p className="muted pad">Run a claim to watch the agents work.</p>}
        {lines.map((l) => (
          <div key={l.id} className={`tl tl-${l.kind}`}>
            <span className="tl-t">{l.t.toFixed(1)}s</span>
            <span className="tl-n">{l.node}</span>
            <span className="tl-x">{l.text}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
