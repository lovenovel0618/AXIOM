/**
 * 任務事件的 SSE 解析：後端每批回應最多 100 筆後即關閉，由客戶端帶游標續接。
 * 事件內容一律視為不可信輸入，格式不符者直接丟棄而不是補值。
 */

export interface RunEventEnvelope {
  event_id: string
  event_type: string
  sequence: number
  occurred_at: string
  run_id: string | null
  stream_scope: string
  payload: Record<string, unknown>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function toEnvelope(payload: string): RunEventEnvelope | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(payload)
  } catch {
    return null
  }
  if (!isRecord(parsed)) return null
  const sequence = parsed.sequence
  const eventType = parsed.event_type
  if (typeof sequence !== 'number' || !Number.isInteger(sequence) || sequence < 0) return null
  if (typeof eventType !== 'string' || eventType === '') return null
  return {
    event_id: typeof parsed.event_id === 'string' ? parsed.event_id : '',
    event_type: eventType,
    sequence,
    occurred_at: typeof parsed.occurred_at === 'string' ? parsed.occurred_at : '',
    run_id: typeof parsed.run_id === 'string' ? parsed.run_id : null,
    stream_scope: typeof parsed.stream_scope === 'string' ? parsed.stream_scope : '',
    payload: isRecord(parsed.payload) ? parsed.payload : {},
  }
}

/** 解析單批 SSE 文字：忽略註解與 keepalive，只留下可用的 data 框架。 */
export function parseEventBatch(text: string): RunEventEnvelope[] {
  const events: RunEventEnvelope[] = []
  let data: string[] = []
  const flush = (): void => {
    if (data.length > 0) {
      const envelope = toEnvelope(data.join('\n'))
      if (envelope !== null) events.push(envelope)
    }
    data = []
  }
  for (const line of text.split('\n')) {
    const trimmed = line.endsWith('\r') ? line.slice(0, -1) : line
    if (trimmed === '') {
      flush()
      continue
    }
    if (trimmed.startsWith(':')) continue
    const separator = trimmed.indexOf(':')
    const field = separator === -1 ? trimmed : trimmed.slice(0, separator)
    const raw = separator === -1 ? '' : trimmed.slice(separator + 1)
    if (field !== 'data') continue
    data.push(raw.startsWith(' ') ? raw.slice(1) : raw)
  }
  flush()
  return events
}

/** 續接游標必須是後端接受的 `RUN:<run uuid>:<sequence>`，其餘一律拒絕。 */
export function resumeCursor(runId: string, events: RunEventEnvelope[]): string | null {
  const last = events[events.length - 1]
  if (last === undefined) return null
  return `RUN:${runId}:${String(last.sequence)}`
}
