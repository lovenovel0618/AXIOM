import { describe, expect, it } from 'vitest'
import { ApiError, createApiClient, toRelativePath, type Fetcher } from '../src/api/client'

interface Recorded {
  url: string
  method: string
  headers: Headers
  body: unknown
}

function recorder(responses: Response[]): { fetcher: Fetcher; calls: Recorded[] } {
  const calls: Recorded[] = []
  const fetcher: Fetcher = async (url, init) => {
    calls.push({ url, method: init?.method ?? 'GET', headers: new Headers(init?.headers), body: init?.body })
    const next = responses.shift()
    if (next === undefined) throw new Error(`unexpected request ${url}`)
    return next
  }
  return { fetcher, calls }
}

describe('api client', () => {
  it('attaches the csrf header to unsafe methods', async () => {
    const { fetcher, calls } = recorder([new Response(null, { status: 204 })])
    const client = createApiClient(fetcher, () => 'token-1')
    await client.request('POST', '/api/v2/datasets', { json: { name: 'demo' } })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('token-1')
    expect(calls[0]?.headers.get('Content-Type')).toBe('application/json')
    expect(calls[0]?.body).toBe(JSON.stringify({ name: 'demo' }))
  })

  it('leaves the csrf header off safe reads', async () => {
    const { fetcher, calls } = recorder([Response.json({ items: [], next_cursor: null })])
    const client = createApiClient(fetcher, () => 'token-1')
    await client.request('GET', '/api/v2/datasets')
    expect(calls[0]?.headers.get('X-CSRFToken')).toBeNull()
  })

  it('seeds the csrf cookie through the login page when it is missing', async () => {
    let cookie: string | null = null
    const { fetcher, calls } = recorder([
      new Response('<html></html>', { status: 200 }),
      new Response(null, { status: 204 }),
    ])
    const stateful: Fetcher = async (url, init) => {
      const response = await fetcher(url, init)
      if (url === '/auth/login') cookie = 'seeded'
      return response
    }
    const client = createApiClient(stateful, () => cookie)
    await client.request('POST', '/api/v2/datasets', { json: { name: 'demo' } })
    expect(calls.map((call) => call.url)).toEqual(['/auth/login', '/api/v2/datasets'])
    expect(calls[1]?.headers.get('X-CSRFToken')).toBe('seeded')
  })

  it('maps a stable error body onto ApiError', async () => {
    const { fetcher } = recorder([Response.json({ code: 'RATE_LIMITED', retryable: true }, { status: 429 })])
    const client = createApiClient(fetcher, () => 'token-1')
    await expect(client.request('GET', '/api/v2/datasets')).rejects.toMatchObject({
      code: 'RATE_LIMITED',
      status: 429,
      retryable: true,
    })
  })

  it('keeps the status code when the error body is not JSON', async () => {
    const { fetcher } = recorder([new Response('<html>502</html>', { status: 502 })])
    const client = createApiClient(fetcher, () => 'token-1')
    const error: unknown = await client.request('GET', '/api/v2/datasets').catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'INTERNAL_ERROR', status: 502 })
  })

  it('returns undefined for an empty 204 body', async () => {
    const { fetcher } = recorder([new Response(null, { status: 204 })])
    const client = createApiClient(fetcher, () => 'token-1')
    await expect(client.request('POST', '/auth/logout', { csrf: 'token-1' })).resolves.toBeUndefined()
  })
})

describe('toRelativePath', () => {
  it('drops the backend origin so requests stay same-origin', () => {
    expect(toRelativePath('http://127.0.0.1:18000/storage/uploads/abc')).toBe('/storage/uploads/abc')
  })

  it('keeps query strings', () => {
    expect(toRelativePath('http://web:8000/api/v2/datasets?limit=1')).toBe('/api/v2/datasets?limit=1')
  })

  it('accepts an already relative path', () => {
    expect(toRelativePath('/storage/uploads/abc')).toBe('/storage/uploads/abc')
  })
})
