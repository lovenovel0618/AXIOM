import { describe, expect, it } from 'vitest'
import { parseEventBatch, resumeCursor } from '../src/lib/events'

const RUN_ID = '11111111-1111-1111-1111-111111111111'

function frame(sequence: number, eventType: string, payload: unknown): string {
  const envelope = {
    event_id: `event-${sequence}`,
    schema_version: '2.0',
    event_type: eventType,
    tenant_id: '22222222-2222-2222-2222-222222222222',
    research_version_id: null,
    run_id: RUN_ID,
    stream_scope: 'RUN',
    stream_id: RUN_ID,
    sequence,
    occurred_at: '2026-10-21T00:00:00Z',
    trace_id: RUN_ID,
    producer_version: 't07-ingest-v1',
    payload,
  }
  return `id: RUN:${RUN_ID}:${sequence}\nevent: ${eventType}\ndata: ${JSON.stringify(envelope)}\n\n`
}

describe('parseEventBatch', () => {
  it('skips the retry hint and keepalive comment', () => {
    const text = `retry: 2000\n\n: keepalive\n\n${frame(1, 'RunQueued', { status: 'QUEUED', stop_reason: null, revision: 1 })}`
    const events = parseEventBatch(text)
    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({ event_type: 'RunQueued', sequence: 1, run_id: RUN_ID })
    expect(events[0]?.payload).toEqual({ status: 'QUEUED', stop_reason: null, revision: 1 })
  })

  it('keeps frames in arrival order and accepts CRLF endings', () => {
    const text = `${frame(1, 'RunQueued', {})}${frame(2, 'RunFinished', { status: 'SUCCEEDED' })}`
      .split('\n')
      .join('\r\n')
    const events = parseEventBatch(text)
    expect(events.map((event) => event.sequence)).toEqual([1, 2])
    expect(events.map((event) => event.event_type)).toEqual(['RunQueued', 'RunFinished'])
  })

  it('joins a payload split across several data lines', () => {
    const text = `data: {"event_type":"RunFinished",\ndata: "sequence":3,"run_id":"${RUN_ID}","payload":{}}\n\n`
    const events = parseEventBatch(text)
    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({ event_type: 'RunFinished', sequence: 3 })
  })

  it('drops frames without a usable envelope instead of inventing values', () => {
    const text = [
      'data: not-json\n\n',
      'data: [1,2,3]\n\n',
      `data: {"event_type":"RunQueued","run_id":"${RUN_ID}"}\n\n`,
      `data: {"event_type":"","sequence":4,"run_id":"${RUN_ID}"}\n\n`,
      `data: {"event_type":"RunQueued","sequence":-1,"run_id":"${RUN_ID}"}\n\n`,
      'event: RunQueued\n\n',
    ].join('')
    expect(parseEventBatch(text)).toEqual([])
  })

  it('returns an empty list for a batch with no frames', () => {
    expect(parseEventBatch('')).toEqual([])
    expect(parseEventBatch('retry: 2000\n\n')).toEqual([])
  })
})

describe('resumeCursor', () => {
  it('builds the RUN cursor from the last delivered sequence', () => {
    const events = parseEventBatch(`${frame(7, 'RunQueued', {})}${frame(8, 'RunFinished', {})}`)
    expect(resumeCursor(RUN_ID, events)).toBe(`RUN:${RUN_ID}:8`)
  })

  it('returns null when nothing was delivered', () => {
    expect(resumeCursor(RUN_ID, [])).toBeNull()
  })
})
