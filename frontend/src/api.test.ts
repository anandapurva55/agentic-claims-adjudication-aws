import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

const stream = (chunks: string[]) => new ReadableStream({ start(c) { chunks.forEach((x) => c.enqueue(new TextEncoder().encode(x))); c.close() } })
const json = (body: unknown, status: number) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const signal = () => new AbortController().signal

let fetchMock: ReturnType<typeof vi.fn>
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock) })
afterEach(() => vi.unstubAllGlobals())

describe('api.run', () => {
  it('is a POST that carries the identity header', async () => {
    fetchMock.mockResolvedValue(new Response(stream(['event: end\ndata: {}\n\n']), { status: 200 }))
    await api.run('CLM-1', 'replay', () => {}, signal())
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/api\/claims\/CLM-1\/run\?mode=replay$/)
    expect(init.method).toBe('POST')
    expect(init.headers['X-Demo-Role']).toBe('adjuster') // sign-in is off in tests, so the development identity is sent
  })
  it('puts events split across chunks back together and stops at the end event', async () => {
    fetchMock.mockResolvedValue(new Response(stream(['data: {"type":"node","id":"intake"}\n', '\ndata: {"type":"res', 'ult","n":2}\n\nevent: end\ndata: {}\n\ndata: {"type":"late"}\n\n']), { status: 200 }))
    const seen: unknown[] = []
    await api.run('CLM-1', 'replay', (e) => seen.push(e), signal())
    expect(seen).toEqual([{ type: 'node', id: 'intake' }, { type: 'result', n: 2 }]) // nothing after the end event
  })
  it('finishes when the stream closes without an end event', async () => {
    fetchMock.mockResolvedValue(new Response(stream(['data: {"type":"x"}\n\n']), { status: 200 }))
    const seen: unknown[] = []
    await api.run('CLM-1', 'replay', (e) => seen.push(e), signal())
    expect(seen).toEqual([{ type: 'x' }])
  })
  it('reads a final event that arrives without a closing blank line', async () => {
    fetchMock.mockResolvedValue(new Response(stream(['data: {"type":"last"}']), { status: 200 }))
    const seen: unknown[] = []
    await api.run('CLM-1', 'replay', (e) => seen.push(e), signal())
    expect(seen).toEqual([{ type: 'last' }])
  })
  it('shows the server message when the daily spend limit is reached', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'the daily spend limit of $5.00 has been reached' }, 429))
    await expect(api.run('CLM-1', 'live', () => {}, signal())).rejects.toThrow('daily spend limit of $5.00')
  })
  it('falls back to a generic message when the error has no JSON body', async () => {
    fetchMock.mockResolvedValue(new Response('boom', { status: 500 }))
    await expect(api.run('CLM-1', 'live', () => {}, signal())).rejects.toThrow('run failed: 500')
  })
  it('encodes the mode so it cannot add query parameters', async () => {
    fetchMock.mockResolvedValue(new Response(stream([]), { status: 200 }))
    await api.run('CLM-1', 'live&x=1', () => {}, signal())
    expect(fetchMock.mock.calls[0][0]).toContain('mode=live%26x%3D1')
  })
})

describe('api.review', () => {
  it('sends the decision without a role or reviewer, which the server takes from the token', async () => {
    fetchMock.mockResolvedValue(json({ outcome: 'ok', final: 'approve' }, 200))
    await api.review('CLM-1', { action: 'override', final_decision: 'deny', note: 'because' })
    expect(Object.keys(JSON.parse(fetchMock.mock.calls[0][1].body)).sort()).toEqual(['action', 'final_decision', 'note'])
  })
  it('surfaces the server message, such as a claim that already has a decision', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'this claim already has a human decision' }, 409))
    await expect(api.review('CLM-1', { action: 'accept' })).rejects.toThrow('already has a human decision')
  })
})

describe('reads', () => {
  it('reports the status when a read fails', async () => {
    fetchMock.mockResolvedValue(new Response('no', { status: 401 }))
    await expect(api.claims()).rejects.toThrow('/api/claims: 401')
  })
})
