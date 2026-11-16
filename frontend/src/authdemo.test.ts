import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The demo accounts are checked in the browser. The module reads the demo flag when it loads, so each test loads a fresh copy with the flag set.
let store: Record<string, string>
let reload: ReturnType<typeof vi.fn>
async function load() {
  vi.resetModules()
  vi.stubEnv('VITE_STATIC_DEMO', '1')
  return import('./auth')
}
beforeEach(() => {
  store = {}
  reload = vi.fn()
  vi.stubGlobal('sessionStorage', { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v }, removeItem: (k: string) => { delete store[k] } })
  vi.stubGlobal('window', { location: { reload } })
})
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('demo sign-in', () => {
  it('starts signed out, and a correct login makes the person that account with its role', async () => {
    const a = await load()
    expect(await a.initAuth()).toBe('signed-out')
    expect(a.demoSignIn('demo.senior', 'demo')).toBe(true)
    expect(a.currentSession()).toMatchObject({ username: 'demo.senior', role: 'senior' })
    expect(await a.authHeaders()).toMatchObject({ 'X-Demo-Role': 'senior' })  // the demo's review rules read the role from this header
  })
  it('an adjuster login is an adjuster, so the four eyes rule applies to them', async () => {
    const a = await load()
    a.demoSignIn('demo.adjuster', 'demo')
    expect(a.currentSession()?.role).toBe('adjuster')
    expect(await a.authHeaders()).toMatchObject({ 'X-Demo-Role': 'adjuster' })
  })
  it('refuses a wrong password, an unknown user and an empty form, and signs nobody in', async () => {
    const a = await load()
    expect(a.demoSignIn('demo.senior', 'wrong')).toBe(false)
    expect(a.demoSignIn('demo.senior', 'DEMO')).toBe(false)  // the password is case sensitive
    expect(a.demoSignIn('nobody', 'demo')).toBe(false)
    expect(a.demoSignIn('', '')).toBe(false)
    expect(a.currentSession()).toBeNull()
    expect(store).toEqual({})
  })
  it('ignores case and spaces in the username only', async () => {
    const a = await load()
    expect(a.demoSignIn('  Demo.Adjuster ', 'demo')).toBe(true)
  })
  it('a reload in the same tab stays signed in, and signing out returns to the sign-in screen', async () => {
    const a = await load()
    a.demoSignIn('demo.senior', 'demo')
    const again = await load()  // a page reload: a fresh module reading what the tab kept
    expect(await again.initAuth()).toBe('signed-in')
    expect(again.currentSession()?.username).toBe('demo.senior')
    again.signOut()
    expect(again.currentSession()).toBeNull()
    expect(store).toEqual({})
    expect(reload).toHaveBeenCalled()
    expect(await (await load()).initAuth()).toBe('signed-out')
  })
  it('the demo never looks for a sign-in configuration or the network', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const a = await load()
    await a.initAuth()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
