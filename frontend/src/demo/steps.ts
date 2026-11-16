// The demo's "Try it" strip: which of the four steps a visitor has done, and which one to do next.
export type StepState = { done: boolean; current: boolean }

export const STEPS = [
  { title: 'Pick a claim', text: 'Choose one in the queue, left.', hint: 'Try CLM-2026044 (injected instruction) or CLM-2026043 (needs a senior).' },
  { title: 'Run the agents', text: 'Press Run agents and watch the graph.' },
  { title: 'Make the call', text: 'Accept, override or escalate, right.' },
  { title: 'Change roles', text: 'Open your initials, top right, and switch to senior adjuster.' },
] as const

/** Steps are done in order. A claim someone already decided counts as run, and the last step is an invitation, so it is never done. */
export function stepStates(p: { selected: boolean; ran: boolean; reviewed: boolean }): StepState[] {
  const done = [p.selected, p.ran || p.reviewed, p.reviewed, false]
  const current = done.findIndex((d) => !d)
  return done.map((d, i) => ({ done: d, current: i === current }))
}
