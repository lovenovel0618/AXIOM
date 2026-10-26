/**
 * 事件串流的續接與重連（AX-44 的「SSE 中斷」狀態）。
 * 後端每批回應有界並以 retry 欄位提示節奏；本模組只管理游標、去重與重連節奏，
 * 畫面不因連線中斷而凍結成仍在正常更新的假象：狀態一律來自這裡回報的事實。
 * 游標過期（400 INVALID_CURSOR）時依 AX-21 重新讀取權威 snapshot 取得目前序號，
 * 再續接；已顯示的事件不重播，並誠實標記曾發生缺口。
 */
import { ApiError } from '../api/client'
import { resumeScopedCursor, type RunEventEnvelope } from './events'
import { describeError } from './messages'

export const DEFAULT_RETRY_MS = 2000
export const MAX_RETRY_MS = 30_000

export interface EventBatch {
  events: RunEventEnvelope[]
  retryMs: number | null
}

export type BatchFetcher = (cursor: string | null) => Promise<EventBatch>
export type FollowStatus = 'FOLLOWING' | 'RECONNECTING' | 'STOPPED'

export interface FollowState {
  status: FollowStatus
  events: RunEventEnvelope[]
  cursor: string | null
  lastSyncedAt: string | null
  attempts: number
  error: string
  gapDetected: boolean
}

export interface FollowerOptions {
  scope: 'RUN' | 'RESEARCH'
  streamId: string
  fetchBatch: BatchFetcher
  /** 重新讀取權威資源（run／研究版本投影），終態判定只認這份結果。 */
  sync: () => Promise<void>
  isTerminal: () => boolean
  /** 游標過期時取得目前序號；失敗時維持原游標並繼續重連。 */
  snapshotCursor: () => Promise<string | null>
  onUpdate: (state: FollowState) => void
}

export const INITIAL_FOLLOW_STATE: FollowState = {
  status: 'STOPPED',
  events: [],
  cursor: null,
  lastSyncedAt: null,
  attempts: 0,
  error: '',
  gapDetected: false,
}

function identity(event: RunEventEnvelope): string {
  return event.event_id !== '' ? event.event_id : `${event.stream_scope}:${String(event.sequence)}`
}

/** 依事件身分去重；重送的框架不重複顯示，也不覆蓋先到的版本。 */
export function dedupeBySequence(
  existing: RunEventEnvelope[],
  incoming: RunEventEnvelope[],
): RunEventEnvelope[] {
  const seen = new Set(existing.map(identity))
  const merged = [...existing]
  for (const event of incoming) {
    const key = identity(event)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(event)
  }
  return merged
}

/** 指數退避但有上限；伺服器給的 retry 為基準，其餘用預設值。 */
export function retryDelay(attempt: number, retryMs: number | null): number {
  const base = Math.min(retryMs ?? DEFAULT_RETRY_MS, MAX_RETRY_MS)
  const step = Math.max(1, Math.trunc(attempt))
  return Math.min(base * 2 ** Math.min(step - 1, 20), MAX_RETRY_MS)
}

export const FOLLOW_STATUS_LABELS: Record<FollowStatus, string> = {
  FOLLOWING: '正在追蹤事件…',
  RECONNECTING: '連線中斷，重連中…',
  STOPPED: '事件追蹤已停止。',
}

export class EventFollower {
  private readonly options: FollowerOptions
  private state: FollowState = INITIAL_FOLLOW_STATE
  private timer: ReturnType<typeof setTimeout> | null = null
  private running = false
  private retryMs: number | null = null

  constructor(options: FollowerOptions) {
    this.options = options
  }

  snapshot(): FollowState {
    return { ...this.state, events: [...this.state.events] }
  }

  start(): void {
    this.stopTimer()
    this.running = true
    this.retryMs = null
    this.state = { ...INITIAL_FOLLOW_STATE, events: [], status: 'FOLLOWING' }
    this.publish()
    void this.attempt()
  }

  stop(): void {
    this.running = false
    this.stopTimer()
    this.state.status = 'STOPPED'
    this.publish()
  }

  private publish(): void {
    this.options.onUpdate(this.snapshot())
  }

  private stopTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }

  private schedule(delayMs: number): void {
    this.stopTimer()
    if (!this.running) return
    this.timer = setTimeout(() => {
      void this.attempt()
    }, delayMs)
  }

  private async recoverCursor(cause: unknown): Promise<void> {
    if (!(cause instanceof ApiError) || cause.code !== 'INVALID_CURSOR') return
    this.state.gapDetected = true
    try {
      this.state.cursor = await this.options.snapshotCursor()
    } catch {
      this.state.error = '游標已失效且無法重新取得同步點；將繼續重連。'
    }
  }

  private async attempt(): Promise<void> {
    if (!this.running) return
    try {
      const batch = await this.options.fetchBatch(this.state.cursor)
      if (!this.running) return
      const events = dedupeBySequence(this.state.events, batch.events)
      this.state.events = events
      const advanced = resumeScopedCursor(this.options.scope, this.options.streamId, events)
      if (advanced !== null) this.state.cursor = advanced
      if (batch.retryMs !== null) this.retryMs = batch.retryMs
      this.state.status = 'FOLLOWING'
      this.state.attempts = 0
      this.state.error = ''
      await this.options.sync()
      if (!this.running) return
      this.state.lastSyncedAt = new Date().toISOString()
      this.publish()
      if (this.options.isTerminal()) {
        this.running = false
        this.state.status = 'STOPPED'
        this.publish()
        return
      }
      this.schedule(this.retryMs ?? DEFAULT_RETRY_MS)
    } catch (cause) {
      if (!this.running) return
      this.state.attempts += 1
      this.state.status = 'RECONNECTING'
      this.state.error = describeError(cause)
      await this.recoverCursor(cause)
      if (!this.running) return
      this.publish()
      this.schedule(retryDelay(this.state.attempts, this.retryMs))
    }
  }
}
