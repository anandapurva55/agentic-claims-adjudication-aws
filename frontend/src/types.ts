export type NodeKind = 'input' | 'service' | 'agent' | 'guard' | 'tool' | 'human' | 'mcp' | 'memory'
export type NodeState = 'idle' | 'active' | 'done' | 'alert' | 'waiting' | 'error'

export interface TopoNode { id: string; label: string; sub: string; kind: NodeKind; col: number; row: number }
export interface Topology { nodes: TopoNode[]; edges: { src: string; dst: string }[] }

export interface Claim {
  claim_id: string; holder: string; policy_no: string; vehicle: string; vehicle_reg: string
  incident_date: string; claimed_amount: number
  stage: 'new' | 'ai_recommended' | 'reviewed'
  ai: { decision: string; payable: number; clauses: string[] } | null
  review: { action: string; final: string; role: string; reviewer: string; note: string; ai_decision?: string } | null
}
export type Role = 'adjuster' | 'senior'
export interface ReviewStats { reviewed: number; accepted: number; overridden: number; escalated: number; agreement_rate: number | null; override_candidates: number }

export interface CalcLine { item: string; category: string; cost: number; depreciation_pct: number; net: number }
export interface Calc {
  basis: string; gross_repair: number; idv: number; deductible: number; vehicle_age_years: number
  lines: CalcLine[]; labour: number; salvage: number; payable: number; raw_payable: number
}
export interface Decision {
  decision: 'approve' | 'deny' | 'refer'; clauses: string[]; payable: number; reasons: string[]
  steps: { check: string; result: string }[]
  next_steps: string[]
}
export interface Citation { clause: string; source: string; text: string }
export interface RunResult {
  run_id: string  // the run a review must name, so "accept" means the result the reviewer looked at
  decision: Decision; calc: Calc; memo: string; citations: Citation[]; flags: Record<string, boolean>
  guardrail: { alerts: string[]; engine: string }; latency_ms: number; mode: string
  signals: { kind: string; severity: 'low' | 'medium' | 'high'; detail: string }[]
  lessons: { text: string; score: number; source: string }[]
  notes: { sender: string; to: string; kind: string; text: string }[]
}

export interface TraceLine { id: number; t: number; node: string; text: string; kind: 'log' | 'tool' | 'node' | 'error' }
export interface Pulse { id: number; src: string; dst: string }

export interface AgentCost {
  name: string; calls: number; input_tokens: number; output_tokens: number; cache_read: number; cost_usd: number; share: number
  avg_latency_ms: number; p95_latency_ms: number; errors: number
}
export interface Metrics {
  runs: number; failure_rate: number; latency_ms: { p50: number; p95: number; max: number }
  cost: { total_usd: number; per_claim_avg_usd: number; per_claim_p95_usd: number; today_usd: number; daily_budget_usd: number }
  decisions: Record<string, number>
  by_day: { day: string; runs: number; failures: number; tokens: number; cost_usd: number }[]
  by_agent: AgentCost[]; by_model: AgentCost[]
  slowest_calls: { agent: string; model: string; latency_ms: number; claim_id: string; input_tokens: number }[]
  alerts: { ts: string; rule: string; detail: string; claim_id?: string }[]
  recent: { claim_id: string; latency_ms: number; cost_usd?: number; decision?: string; ok: boolean; mode: string }[]
}

export interface Health { status: string; mode: string; region: string; models: { orchestrator: string; fast: string } }

export interface SecBlock { attacks: number; errors: number; detected: number; detection_rate: number; succeeded: number; attack_success_rate: number }
export interface Report {
  mode: string; generated: string; n_attacks: number; note: string
  summary: Record<'defences_on' | 'defences_off', { overall: SecBlock; by_type: Record<string, SecBlock> }>
}
