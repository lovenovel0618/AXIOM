import { describe, expect, it } from 'vitest'
import { ApiError, createApiClient, type Fetcher } from '../src/api/client'
import { artifactContentPath, getArtifact } from '../src/api/artifacts'
import { cancelRun, fetchRunEvents, getRun, isTerminal, type Run, type RunStatus } from '../src/api/runs'
import { describeError } from '../src/lib/messages'

const RUN_ID = '11111111-1111-1111-1111-111111111111'
const ARTIFACT_ID = '33333333-3333-3333-3333-333333333333'
const CSRF = 'csrf-1'

interface Call {
  url: string
  method: string
  headers: Headers
  body: unknown
}

function runDocument(): Run {
  return {
    kind: 'Run',
    id: RUN_ID,
    type: 'PROFILE',
    status: 'RUNNING',
    revision: 7,
    created_at: '2026-10-21T00:00:00Z',
    dataset_id: null,
    research_version_id: '44444444-4444-4444-4444-444444444444',
    current_event_cursor: `RUN:${RUN_ID}:2`,
    phase: 'PROFILING',
  }
}

function sse(): string {
  const envelope = {
    event_id: 'event-3',
    event_type: 'RunPhaseChanged',
    run_id: RUN_ID,
    stream_scope: 'RUN',
    sequence: 3,
    occurred_at: '2026-10-21T00:00:02Z',
    payload: { phase: 'FEASIBILITY' },
  }
  return `retry: 2000\n\nevent: RunPhaseChanged\ndata: ${JSON.stringify(envelope)}\n\n`
}

function scenario(responder: (call: Call) => Response): { calls: Call[]; client: ReturnType<typeof createApiClient> } {
  const calls: Call[] = []
  const fetcher: Fetcher = async (url, init) => {
    const call: Call = { url, method: init?.method ?? 'GET', headers: new Headers(init?.headers), body: init?.body }
    calls.push(call)
    return responder(call)
  }
  return { calls, client: createApiClient(fetcher, () => CSRF) }
}

describe('getRun', () => {
  it('reads the run projection from the documented path', async () => {
    const { calls, client } = scenario(() => Response.json(runDocument()))
    const run = await getRun(client, RUN_ID)
    expect(run.status).toBe('RUNNING')
    expect(calls[0]?.url).toBe(`/api/v2/runs/${RUN_ID}`)
    expect(calls[0]?.method).toBe('GET')
  })
})

describe('cancelRun', () => {
  it('sends the current control revision with an idempotency key and CSRF token', async () => {
    const { calls, client } = scenario(() => Response.json({ ...runDocument(), status: 'CANCEL_REQUESTED' }, { status: 202 }))
    const run = await cancelRun(client, runDocument())
    expect(run.status).toBe('CANCEL_REQUESTED')

    const call = calls[0]
    expect(call?.url).toBe(`/api/v2/runs/${RUN_ID}/cancel`)
    expect(call?.method).toBe('POST')
    expect(call?.headers.get('If-Control-Revision')).toBe('7')
    expect(call?.headers.get('X-CSRFToken')).toBe(CSRF)
    expect(call?.headers.get('Idempotency-Key')).toMatch(/\S/)
    expect(call?.body).toBe('{}')
  })

  it('surfaces the 503 that non-PROFILE runs return', async () => {
    const disabled = Response.json({ code: 'DEPENDENCY_UNAVAILABLE', retryable: true }, { status: 503 })
    const { client } = scenario(() => disabled.clone())
    const error: unknown = await cancelRun(client, runDocument()).catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect(describeError(error)).toContain('未啟用')
  })
})

describe('fetchRunEvents', () => {
  it('starts from zero without a cursor', async () => {
    const { calls, client } = scenario(() => new Response(sse(), { status: 200 }))
    const events = await fetchRunEvents(client, RUN_ID, null)
    expect(calls[0]?.url).toBe(`/api/v2/runs/${RUN_ID}/events`)
    expect(calls[0]?.headers.get('Last-Event-ID')).toBeNull()
    expect(events).toHaveLength(1)
    expect(events[0]?.payload).toEqual({ phase: 'FEASIBILITY' })
  })

  it('resumes from the supplied RUN cursor', async () => {
    const { calls, client } = scenario(() => new Response(': keepalive\n\n', { status: 200 }))
    const events = await fetchRunEvents(client, RUN_ID, `RUN:${RUN_ID}:3`)
    expect(calls[0]?.headers.get('Last-Event-ID')).toBe(`RUN:${RUN_ID}:3`)
    expect(events).toEqual([])
  })
})

describe('isTerminal', () => {
  const terminal: RunStatus[] = ['SUCCEEDED', 'FAILED', 'CANCELLED']
  const active: RunStatus[] = ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']

  it.each(terminal)('treats %s as terminal', (status) => {
    expect(isTerminal(status)).toBe(true)
  })

  it.each(active)('keeps polling for %s', (status) => {
    expect(isTerminal(status)).toBe(false)
  })
})

describe('artifacts', () => {
  it('reads metadata and exposes the same-origin content path', async () => {
    const { calls, client } = scenario(() =>
      Response.json({
        kind: 'Artifact',
        id: ARTIFACT_ID,
        tenant_id: '22222222-2222-2222-2222-222222222222',
        created_at: '2026-10-21T00:00:00Z',
        artifact_uri: 'local://versions/1',
        sha256: 'a'.repeat(64),
        status: 'AVAILABLE',
        owner_id: '55555555-5555-5555-5555-555555555555',
        size_bytes: 12,
        media_type: 'application/json',
        access_class: 'PROJECT',
      }),
    )
    const artifact = await getArtifact(client, ARTIFACT_ID)
    expect(calls[0]?.url).toBe(`/api/v2/artifacts/${ARTIFACT_ID}`)
    expect(artifact.status).toBe('AVAILABLE')
    expect(artifactContentPath(ARTIFACT_ID)).toBe(`/api/v2/artifacts/${ARTIFACT_ID}/content`)
  })
})
