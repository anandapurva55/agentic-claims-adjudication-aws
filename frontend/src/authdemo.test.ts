import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { passwordProblems } from './authlib'

// The demo has no accounts: any username works with a password that meets the real rule, and the person picks a role. The module reads the demo flag when it
// loads, so each test loads a fresh copy with the flag set.
const GOOD = 'Demo-Pass-2026!'
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

describe('the password rule', () => {
  it('passes a password that has everything, and names each thing a password is missing', () => {
    expect(passwordProblems(GOOD)).toEqual([])
    expect(passwordProblems('Short1!')).toEqual(['at least 12 characters'])
    expect(passwordProblems('lowercase-only-1!')).toEqual(['an upper case letter'])
    expect(passwordProblems('UPPERCASE-ONLY-1!')).toEqual(['a lower case letter'])
    expect(passwordProblems('NoDigitsHere-ok!')).toEqual(['a digit'])
    expect(passwordProblems('NoSymbolsHere123')).toEqual(['a symbol'])
    expect(passwordProblems('')).toHaveLength(5)
  })
  it('counts exactly 12 characters as enough and 11 as not', () => {
    expect(passwordProblems('Abcdefgh1!xy')).toEqual([])
    expect(passwordProblems('Abcdefgh1!x')).toEqual(['at least 12 characters'])
  })
})

describe('demo sign-in', () => {
  it('starts signed out, and any username with a good password signs in as the role that was picked', async () => {
    const a = await load()
    expect(await a.initAuth()).toBe('signed-out')
    expect(a.demoSignIn('Some Recruiter', GOOD, 'senior')).toBeNull()
    expect(a.currentSession()).toMatchObject({ username: 'Some Recruiter', role: 'senior' })
    expect(await a.authHeaders()).toMatchObject({ 'X-Demo-Role': 'senior' })  // the demo's review rules read the role from this header
  })
  it('an adjuster is an adjuster, so the four eyes rule applies to them', async () => {
    const a = await load()
    a.demoSignIn('asha', GOOD, 'adjuster')
    expect(a.currentSession()?.role).toBe('adjuster')
    expect(await a.authHeaders()).toMatchObject({ 'X-Demo-Role': 'adjuster' })
  })
  it('refuses a password that breaks the rule and says what it needs, and signs nobody in', async () => {
    const a = await load()
    expect(a.demoSignIn('asha', 'password', 'adjuster')).toBe('The password needs at least 12 characters, an upper case letter, a digit, a symbol.')
    expect(a.demoSignIn('asha', 'Short1!', 'adjuster')).toContain('at least 12 characters')
    expect(a.currentSession()).toBeNull()
    expect(store).toEqual({})
  })
  it('refuses an empty username, including one that is only spaces and control characters', async () => {
    const a = await load()
    expect(a.demoSignIn('', GOOD, 'adjuster')).toBe('Enter a username.')
    expect(a.demoSignIn('  \n\t ', GOOD, 'adjuster')).toBe('Enter a username.')
    expect(a.currentSession()).toBeNull()
  })
  it('cleans the username before it is shown: markup characters are dropped and the length is capped', async () => {
    const a = await load()
    a.demoSignIn('  <b>asha</b>\n' + 'x'.repeat(100), GOOD, 'adjuster')
    const name = a.currentSession()!.username
    expect(name.startsWith('basha')).toBe(true)
    expect(name).not.toMatch(/[<>\n]/)
    expect(name).toHaveLength(40)
  })
  it('a reload in the same tab stays signed in as the same person and role, and signing out returns to the sign-in screen', async () => {
    const a = await load()
    a.demoSignIn('priya', GOOD, 'senior')
    const again = await load()  // a page reload: a fresh module reading what the tab kept
    expect(await again.initAuth()).toBe('signed-in')
    expect(again.currentSession()).toMatchObject({ username: 'priya', role: 'senior' })
    again.signOut()
    expect(again.currentSession()).toBeNull()
    expect(store).toEqual({})
    expect(reload).toHaveBeenCalled()
    expect(await (await load()).initAuth()).toBe('signed-out')
  })
  it('a damaged saved login is ignored', async () => {
    store['claims.demo.session'] = '{broken'
    expect(await (await load()).initAuth()).toBe('signed-out')
    store['claims.demo.session'] = JSON.stringify({ username: 'x', role: 'admin' })  // a role the demo does not have
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
