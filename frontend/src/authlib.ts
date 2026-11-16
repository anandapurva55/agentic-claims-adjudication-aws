// Pure helpers for sign-in and streaming. No browser state here, so they can be tested on their own.
import type { Role } from './types'

const b64url = (bytes: Uint8Array): string => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

/** A random URL-safe string, used for the PKCE code verifier and the state value. */
export const randomString = (bytes = 32): string => b64url(crypto.getRandomValues(new Uint8Array(bytes)))

/** PKCE (RFC 7636) S256: the challenge sent to the sign-in page is the SHA-256 of the secret verifier kept in this browser. */
export async function challengeFor(verifier: string): Promise<string> {
  return b64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))))
}

export type TokenClaims = { exp: number; 'cognito:username'?: string; email?: string; sub: string; 'cognito:groups'?: string[] }

/** Read the claims inside an ID token. This only reads them for display. The API checks the signature on every request, the browser never trusts it. */
export function decodeClaims(token: string): TokenClaims {
  const body = token.split('.')[1] ?? ''
  const json = atob(body.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(body.length / 4) * 4, '='))
  return JSON.parse(json) as TokenClaims
}

export const roleOf = (claims: TokenClaims): Role | null => {
  const groups = claims['cognito:groups'] ?? []
  return groups.includes('senior') ? 'senior' : groups.includes('adjuster') ? 'adjuster' : null
}

/** Split a server-sent-event stream into complete events. Returns the events found and the unfinished tail to keep for the next chunk. */
export function parseSse(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  const events = parts.filter((p) => p.trim()).map((block) => {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    return { event, data: data.join('\n') }
  })
  return { events, rest }
}

/** Up to two capital letters for the avatar: "Apurva Anand" gives AA, "priya.rao" gives PR, "asha" gives A. */
export function initials(name: string): string {
  const words = name.split(/[\s._@-]+/).filter(Boolean)
  const letters = words.length >= 2 ? words[0][0] + words[1][0] : (words[0] ?? '?').slice(0, 1)
  return letters.toUpperCase()
}
