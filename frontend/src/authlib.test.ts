import { describe, expect, it } from 'vitest'
import { challengeFor, decodeClaims, parseSse, randomString, roleOf } from './authlib'

const enc = (o: object) => btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
const token = (claims: object) => `${enc({ alg: 'RS256' })}.${enc(claims)}.signature`

describe('PKCE', () => {
  it('matches the test vector in RFC 7636 appendix B', async () => {
    expect(await challengeFor('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
  })
  it('makes a random, URL-safe verifier of a valid length', () => {
    const a = randomString(), b = randomString()
    expect(a).not.toBe(b)
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/) // RFC 7636 allows 43 to 128 characters
  })
  it('never puts padding or characters that need escaping in a URL', () => {
    for (let i = 0; i < 50; i++) expect(randomString(31)).toMatch(/^[A-Za-z0-9_-]+$/)
  })
})

describe('reading a token for display', () => {
  it('decodes the claims', () => {
    const c = decodeClaims(token({ sub: 'u', exp: 9999999999, 'cognito:username': 'priya', 'cognito:groups': ['adjuster'] }))
    expect(c['cognito:username']).toBe('priya')
    expect(c.exp).toBe(9999999999)
  })
  it('gives a senior the senior role even when also in the adjuster group', () => {
    expect(roleOf(decodeClaims(token({ sub: 'u', exp: 1, 'cognito:groups': ['adjuster', 'senior'] })))).toBe('senior')
  })
  it('gives an adjuster the adjuster role', () => {
    expect(roleOf(decodeClaims(token({ sub: 'u', exp: 1, 'cognito:groups': ['adjuster'] })))).toBe('adjuster')
  })
  it('gives no role to someone in no known group, or in none', () => {
    expect(roleOf(decodeClaims(token({ sub: 'u', exp: 1, 'cognito:groups': ['visitors'] })))).toBeNull()
    expect(roleOf(decodeClaims(token({ sub: 'u', exp: 1 })))).toBeNull()
  })
  it('throws on something that is not a token, so the caller treats it as signed out', () => {
    expect(() => decodeClaims('not-a-token')).toThrow()
  })
})

describe('server-sent events parser', () => {
  it('returns complete events and keeps the unfinished tail', () => {
    const r = parseSse('data: {"a":1}\n\ndata: {"b":2}\n\nda')
    expect(r.events).toEqual([{ event: 'message', data: '{"a":1}' }, { event: 'message', data: '{"b":2}' }])
    expect(r.rest).toBe('da')
  })
  it('reads a named event', () => {
    expect(parseSse('event: end\ndata: {}\n\n').events).toEqual([{ event: 'end', data: '{}' }])
  })
  it('joins a multi-line data field', () => {
    expect(parseSse('data: one\ndata: two\n\n').events[0].data).toBe('one\ntwo')
  })
  it('handles empty input and a lone blank block', () => {
    expect(parseSse('')).toEqual({ events: [], rest: '' })
    expect(parseSse('\n\n').events).toEqual([])
  })
  it('gives the same events however the stream is cut into chunks', () => {
    const whole = 'data: {"n":1}\n\nevent: x\ndata: {"n":2}\n\ndata: {"n":3}\n\n'
    for (let cut = 1; cut < whole.length; cut++) {
      const first = parseSse(whole.slice(0, cut))
      const second = parseSse(first.rest + whole.slice(cut))
      expect([...first.events, ...second.events].map((e) => e.data)).toEqual(['{"n":1}', '{"n":2}', '{"n":3}'])
    }
  })
})
