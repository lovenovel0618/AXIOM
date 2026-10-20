import { describe, expect, it } from 'vitest'
import { checkReadiness } from '../src/health'

describe('dependency readiness', () => {
  it('accepts a successful explicit status', async () => {
    expect(await checkReadiness(async () => Response.json({ status: 'ok' }))).toBe('ready')
  })
  it('rejects a dependency failure even with an ok body', async () => {
    expect(await checkReadiness(async () => Response.json({ status: 'ok' }, { status: 503 }))).toBe('unavailable')
  })
  it.each([null, [], { status: 'unknown' }, 'ok'])('rejects an unexpected body %j', async (body) => {
    expect(await checkReadiness(async () => Response.json(body))).toBe('unavailable')
  })
  it('handles invalid JSON', async () => {
    expect(await checkReadiness(async () => new Response('<html>error</html>'))).toBe('unavailable')
  })
  it('handles a network error or timeout', async () => {
    expect(await checkReadiness(() => Promise.reject(new Error('offline')))).toBe('unavailable')
  })
})
