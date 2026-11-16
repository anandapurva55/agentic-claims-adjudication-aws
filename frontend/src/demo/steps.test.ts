import { describe, expect, it } from 'vitest'
import { STEPS, stepStates } from './steps'

const view = (p: { selected: boolean; ran: boolean; reviewed: boolean }) => stepStates(p).map((s) => (s.done ? 'done' : s.current ? 'NEXT' : '-')).join(' ')

describe('the demo "Try it" strip', () => {
  it('has the four steps, in the order a visitor does them', () => {
    expect(STEPS.map((s) => s.title)).toEqual(['Pick a claim', 'Run the agents', 'Make the call', 'Change roles'])
  })
  it('starts by asking for a claim, then a run, then a decision, then a role change', () => {
    expect(view({ selected: false, ran: false, reviewed: false })).toBe('NEXT - - -')
    expect(view({ selected: true, ran: false, reviewed: false })).toBe('done NEXT - -')
    expect(view({ selected: true, ran: true, reviewed: false })).toBe('done done NEXT -')
    expect(view({ selected: true, ran: true, reviewed: true })).toBe('done done done NEXT')
  })
  it('a claim someone already decided counts as run, and the role step is never ticked off', () => {
    expect(view({ selected: true, ran: false, reviewed: true })).toBe('done done done NEXT')
    expect(stepStates({ selected: true, ran: true, reviewed: true })[3].done).toBe(false)
  })
  it('exactly one step is the next one, or none can be next only when all four are done, which never happens', () => {
    for (const selected of [false, true]) for (const ran of [false, true]) for (const reviewed of [false, true]) {
      expect(stepStates({ selected, ran, reviewed }).filter((s) => s.current)).toHaveLength(1)
    }
  })
})
