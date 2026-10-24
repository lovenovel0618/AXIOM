import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/client'
import type { RunEventEnvelope } from '../src/lib/events'
import {
  DEFAULT_RETRY_MS,
  EventFollower,
  INITIAL_FOLLOW_STATE,
  MAX_RETRY_MS,
  dedupeBySequence,
  retryDelay,
  type EventBatch,
  type FollowState,
} from '../src/lib/stream'

const RUN_ID = '11111111-1111-1111-1111-111111111111'

function event(sequence: number, eventId = `event-${sequence}`): RunEventEnvelope {
  return {
    event_id: eventId,
    event_type: 'RunPhaseChanged',
    sequence,
    occurred_at: '2026-10-21T00:00:00Z',
    run_id: RUN_ID,
    stream_scope: 'RUN',
    payload: {},
  }
}

describe('dedupeBySequence', () => {
  it('appends only frames that were not delivered before', () => {
    const merged = dedupeBySequence([event(1), event(2)], [event(2), event(3)])
    expect(merged.map((row) => row.sequence)).toEqual([1, 2, 3])
  })

  it('falls back to scope and sequence when the server sends no event id', () => {
    const merged = dedupeBySequence([event(1, '')], [event(1, ''), event(2, '')])
    expect(merged.map((row) => row.sequence)).toEqual([1, 2])
  })

  it('keeps the version that arrived first instead of overwriting it', () => {
    const first = { ...event(1), event_type: 'RunQueued' }
    const redelivered = { ...event(1), event_type: 'RunPhaseChanged' }
    const merged = dedupeBySequence([first], [redelivered])
    expect(merged).toHaveLength(1)
    expect(merged[0]?.event_type).toBe('RunQueued')
  })
})

describe('retryDelay', () => {
  it('backs off exponentially from the server hint', () => {
    expect(retryDelay(1, 1000)).toBe(1000)
    expect(retryDelay(2, 1000)).toBe(2000)
    expect(retryDelay(3, 1000)).toBe(4000)
  })

  it('falls back to the default hint and never exceeds the cap', () => {
    expect(retryDelay(1, null)).toBe(DEFAULT_RETRY_MS)
    expect(retryDelay(20, 1000)).toBe(MAX_RETRY_MS)
    expect(retryDelay(1, 60_000)).toBe(MAX_RETRY_MS)
  })

  it('treats non positive attempts as the first attempt', () => {
    expect(retryDelay(0, 1000)).toBe(1000)
  })
})

function collect(): { states: FollowState[]; onUpdate: (state: FollowState) => void } {
  const states: FollowState[] = []
  return { states, onUpdate: (state) => states.push(state) }
}

describe('EventFollower', () => {
  it('exposes the initial state before it starts', () => {
    const { onUpdate } = collect()
    const follower = new EventFollower({
      scope: 'RUN',
      streamId: RUN_ID,
      fetchBatch: async () => ({ events: [], retryMs: null }),
      sync: async () => {},
      isTerminal: () => false,
      snapshotCursor: async () => null,
      onUpdate,
    })
    expect(follower.snapshot()).toEqual(INITIAL_FOLLOW_STATE)
  })

  it('publishes delivered events and stops once the resource is terminal', async () => {
    vi.useFakeTimers()
    const { states, onUpdate } = collect()
    let terminal = false
    const fetchBatch = vi.fn(
      async (): Promise<EventBatch> => ({ events: [event(1), event(2)], retryMs: 500 }),
    )
    const follower = new EventFollower({
      scope: 'RUN',
      streamId: RUN_ID,
      fetchBatch,
      sync: async () => {
        terminal = true
      },
      isTerminal: () => terminal,
      snapshotCursor: async () => null,
      onUpdate,
    })
    follower.start()
    await vi.advanceTimersByTimeAsync(0)

    const last = states.at(-1)
    expect(fetchBatch).toHaveBeenCalledTimes(1)
    expect(last?.status).toBe('STOPPED')
    expect(last?.events.map((row) => row.sequence)).toEqual([1, 2])
    expect(last?.cursor).toBe(`RUN:${RUN_ID}:2`)
    expect(last?.lastSyncedAt).not.toBeNull()
    vi.useRealTimers()
  })

  it('resumes from the cursor and dedupes redelivered events', async () => {
    vi.useFakeTimers()
    const { states, onUpdate } = collect()
    const cursors: (string | null)[] = []
    let round = 0
    let synced = 0
    let terminal = false
    const follower = new EventFollower({
      scope: 'RUN',
      streamId: RUN_ID,
      fetchBatch: async (from) => {
        cursors.push(from)
        round += 1
        if (round === 1) return { events: [event(1), event(2)], retryMs: 500 }
        return { events: [event(2), event(3)], retryMs: 500 }
      },
      sync: async () => {
        synced += 1
        if (synced === 2) terminal = true
      },
      isTerminal: () => terminal,
      snapshotCursor: async () => null,
      onUpdate,
    })
    follower.start()
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(500)

    expect(cursors).toEqual([null, `RUN:${RUN_ID}:2`])
    const last = states.at(-1)
    expect(last?.status).toBe('STOPPED')
    expect(last?.events.map((row) => row.sequence)).toEqual([1, 2, 3])
    vi.useRealTimers()
  })

  it('reports reconnecting with the attempt count and recovers on the next try', async () => {
    vi.useFakeTimers()
    const { states, onUpdate } = collect()
    let round = 0
    const follower = new EventFollower({
      scope: 'RUN',
      streamId: RUN_ID,
      fetchBatch: async () => {
        round += 1
        if (round === 1) throw new ApiError('INTERNAL_ERROR', 500, true)
        return { events: [event(1)], retryMs: 400 }
      },
      sync: async () => {},
      isTerminal: () => false,
      snapshotCursor: async () => null,
      onUpdate,
    })
    follower.start()
    await vi.advanceTimersByTimeAsync(0)

    const reconnecting = states.at(-1)
    expect(reconnecting?.status).toBe('RECONNECTING')
    expect(reconnecting?.attempts).toBe(1)
    expect(reconnecting?.error).toBe('伺服器發生未預期的錯誤。')
    expect(reconnecting?.events).toEqual([])

    await vi.advanceTimersByTimeAsync(DEFAULT_RETRY_MS)
    const recovered = states.at(-1)
    expect(recovered?.status).toBe('FOLLOWING')
    expect(recovered?.attempts).toBe(0)
    expect(recovered?.error).toBe('')
    expect(recovered?.events.map((row) => row.sequence)).toEqual([1])
    follower.stop()
    vi.useRealTimers()
  })

  it('resyncs from an authoritative snapshot when the cursor expires', async () => {
    vi.useFakeTimers()
    const { states, onUpdate } = collect()
    const cursors: (string | null)[] = []
    let round = 0
    const follower = new EventFollower({
      scope: 'RESEARCH',
      streamId: RUN_ID,
      fetchBatch: async (from) => {
        cursors.push(from)
        round += 1
        if (round === 1) return { events: [event(1)], retryMs: 300 }
        if (round === 2) throw new ApiError('INVALID_CURSOR', 400, false)
        return { events: [event(5)], retryMs: 300 }
      },
      sync: async () => {},
      isTerminal: () => false,
      snapshotCursor: async () => `RESEARCH:${RUN_ID}:4`,
      onUpdate,
    })
    follower.start()
    await vi.advanceTimersByTimeAsync(0)
    expect(cursors).toEqual([null])

    await vi.advanceTimersByTimeAsync(300)
    const expired = states.at(-1)
    expect(expired?.status).toBe('RECONNECTING')
    expect(expired?.gapDetected).toBe(true)
    expect(expired?.cursor).toBe(`RESEARCH:${RUN_ID}:4`)
    expect(expired?.error).toBe('分頁資料已失效，請重新載入。')

    await vi.advanceTimersByTimeAsync(300)
    expect(cursors.at(-1)).toBe(`RESEARCH:${RUN_ID}:4`)
    const resumed = states.at(-1)
    expect(resumed?.status).toBe('FOLLOWING')
    expect(resumed?.events.map((row) => row.sequence)).toEqual([1, 5])
    expect(resumed?.cursor).toBe(`RESEARCH:${RUN_ID}:5`)
    follower.stop()
    vi.useRealTimers()
  })

  it('stops fetching after stop is called', async () => {
    vi.useFakeTimers()
    const { states, onUpdate } = collect()
    const fetchBatch = vi.fn(async (): Promise<EventBatch> => ({ events: [], retryMs: 500 }))
    const follower = new EventFollower({
      scope: 'RUN',
      streamId: RUN_ID,
      fetchBatch,
      sync: async () => {},
      isTerminal: () => false,
      snapshotCursor: async () => null,
      onUpdate,
    })
    follower.start()
    await vi.advanceTimersByTimeAsync(0)
    follower.stop()
    await vi.advanceTimersByTimeAsync(5000)

    expect(fetchBatch).toHaveBeenCalledTimes(1)
    expect(states.at(-1)?.status).toBe('STOPPED')
    vi.useRealTimers()
  })
})
