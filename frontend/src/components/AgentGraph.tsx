import { useMemo } from 'react'
import type { NodeKind, NodeState, Pulse, TopoNode, Topology } from '../types'

const W = 1240
const ROW_GAP = 135
const TOP = 70
const CARD_W = 156
const CARD_H = 72
const COLS = 6

const KIND_COLOR: Record<NodeKind, string> = {
  input: '#94a3b8',
  agent: '#a78bfa',
  service: '#fb923c',
  guard: '#34d399',
  tool: '#22d3ee',
  human: '#fbbf24',
  mcp: '#f472b6',
  memory: '#60a5fa',
}
const KIND_LABEL: Record<NodeKind, string> = {
  input: 'INPUT', agent: 'AGENT', service: 'AWS SERVICE', guard: 'GUARDRAIL', tool: 'TOOL', human: 'HUMAN', mcp: 'MCP SERVER', memory: 'MEMORY',
}

export interface NodeInfo { state: NodeState; detail: string }

const pos = (n: TopoNode) => ({
  x: 100 + n.col * ((W - 200) / (COLS - 1)),
  y: TOP + n.row * ROW_GAP,
})

// Cheap deterministic noise so a given bolt keeps its shape for its whole life.
function rand(seed: number) {
  const x = Math.sin(seed * 9301 + 49297) * 233280
  return x - Math.floor(x)
}

type P = { x: number; y: number }
interface Geo { x1: number; y1: number; x2: number; y2: number; c1x: number; c1y: number; c2x: number; c2y: number }

// Connect cards at sensible sides: left to right when moving right, bottom to top when stacked, and a
// curve back into the right side when the dependency points backwards.
function geo(a: P, b: P): Geo {
  const dx = b.x - a.x
  if (Math.abs(dx) < 4) {
    const down = b.y > a.y
    const y1 = a.y + (down ? CARD_H / 2 : -CARD_H / 2)
    const y2 = b.y + (down ? -CARD_H / 2 : CARD_H / 2)
    const m = (y1 + y2) / 2
    return { x1: a.x, y1, x2: b.x, y2, c1x: a.x, c1y: m, c2x: b.x, c2y: m }
  }
  if (dx > 0) {
    const x1 = a.x + CARD_W / 2, x2 = b.x - CARD_W / 2, m = (x1 + x2) / 2
    return { x1, y1: a.y, x2, y2: b.y, c1x: m, c1y: a.y, c2x: m, c2y: b.y }
  }
  const down = b.y > a.y
  const x2 = b.x + CARD_W / 2
  const y1 = a.y + (down ? CARD_H / 2 : -CARD_H / 2)
  return { x1: a.x, y1, x2, y2: b.y, c1x: a.x, c1y: b.y, c2x: x2 + (a.x - x2) * 0.4, c2y: b.y }
}

function curvePath(a: P, b: P) {
  const p = geo(a, b)
  return `M ${p.x1} ${p.y1} C ${p.c1x} ${p.c1y}, ${p.c2x} ${p.c2y}, ${p.x2} ${p.y2}`
}

// A jagged polyline that follows the bezier. This is the lightning.
function boltPath(a: P, b: P, seed: number) {
  const p = geo(a, b)
  const steps = 26
  const pts: string[] = []
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const u = 1 - t
    const x = u ** 3 * p.x1 + 3 * u * u * t * p.c1x + 3 * u * t * t * p.c2x + t ** 3 * p.x2
    const y = u ** 3 * p.y1 + 3 * u * u * t * p.c1y + 3 * u * t * t * p.c2y + t ** 3 * p.y2
    const amp = i === 0 || i === steps ? 0 : 13
    const jx = (rand(seed + i) - 0.5) * amp * 1.4
    const jy = (rand(seed + i * 7) - 0.5) * amp * 1.4
    pts.push(`${i === 0 ? 'M' : 'L'} ${(x + jx).toFixed(1)} ${(y + jy).toFixed(1)}`)
  }
  return pts.join(' ')
}

interface Props {
  topology: Topology
  states: Record<string, NodeInfo>
  pulses: Pulse[]
  title?: string
  still?: boolean
}

export default function AgentGraph({ topology, states, pulses, title, still }: Props) {
  const byId = useMemo(() => Object.fromEntries(topology.nodes.map((n) => [n.id, n])), [topology])
  const litEdges = new Set(pulses.map((p) => `${p.src}>${p.dst}`))
  const H = TOP + (Math.max(...topology.nodes.map((n) => n.row)) + 1) * ROW_GAP - 30

  return (
    <div className="graph-wrap">
      {title && <div className="panel-title">{title}</div>}
      <svg viewBox={`0 0 ${W} ${H}`} className={`graph ${still ? 'still' : ''}`} role="img" aria-label="Agent graph">
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="softglow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="6" />
          </filter>
          <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M 32 0 L 0 0 0 32" fill="none" stroke="rgba(148,163,184,0.06)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={W} height={H} fill="url(#grid)" />

        {/* wires */}
        {topology.edges.map((e) => {
          const a = byId[e.src]
          const b = byId[e.dst]
          if (!a || !b) return null
          const lit = litEdges.has(`${e.src}>${e.dst}`)
          return (
            <path key={`${e.src}>${e.dst}`} d={curvePath(pos(a), pos(b))}
              className={`wire ${lit ? 'wire-lit' : ''}`} fill="none" />
          )
        })}

        {/* lightning */}
        {pulses.map((p) => {
          const a = byId[p.src]
          const b = byId[p.dst]
          if (!a || !b) return null
          const color = KIND_COLOR[a.kind]
          const d = boltPath(pos(a), pos(b), p.id * 13)
          return (
            <g key={p.id} className="bolt">
              <path d={d} pathLength={1000} stroke={color} strokeWidth="7" fill="none" filter="url(#softglow)" className="bolt-glow" />
              <path d={d} pathLength={1000} stroke={color} strokeWidth="3" fill="none" filter="url(#glow)" className="bolt-mid" />
              <path d={d} pathLength={1000} stroke="#ffffff" strokeWidth="1.6" fill="none" className="bolt-core" />
            </g>
          )
        })}

        {/* nodes */}
        {topology.nodes.map((n) => {
          const { x, y } = pos(n)
          const info = states[n.id] ?? { state: 'idle', detail: '' }
          const color = KIND_COLOR[n.kind]
          const s = info.state
          return (
            <g key={n.id} transform={`translate(${x - CARD_W / 2}, ${y - CARD_H / 2})`} className={`node node-${s}`}
              style={{ ['--c' as string]: color }}>
              {s === 'active' && <rect className="node-halo" x="-6" y="-6" width={CARD_W + 12} height={CARD_H + 12} rx="18" />}
              <rect className="node-card" width={CARD_W} height={CARD_H} rx="14" />
              <rect className="node-bar" x="0" y="0" width="5" height={CARD_H} rx="2.5" />
              <text className="node-kind" x="16" y="19">{KIND_LABEL[n.kind]}</text>
              <text className="node-label" x="16" y="39">{n.label}</text>
              <text className="node-sub" x="16" y="56">{info.detail ? trim(info.detail, 22) : n.sub}</text>
              <StatusDot state={s} />
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function trim(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

function StatusDot({ state }: { state: NodeState }) {
  const x = CARD_W - 16
  if (state === 'done') return <path d={`M ${x - 5} 19 l 4 4 l 7 -8`} className="dot-done" fill="none" />
  if (state === 'alert') return <text x={x - 3} y="24" className="dot-alert">!</text>
  if (state === 'waiting') return <circle cx={x} cy="19" r="4.5" className="dot-wait" />
  if (state === 'error') return <text x={x - 3} y="24" className="dot-alert">×</text>
  if (state === 'active') return <circle cx={x} cy="19" r="4.5" className="dot-active" />
  return <circle cx={x} cy="19" r="3" className="dot-idle" />
}
