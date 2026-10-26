import type { FlowArtifact, FlowNode, FlowRecord } from './flow'
import type { RunEventEnvelope } from './events'

export interface GroupedArtifacts {
  label: string
  items: FlowArtifact[]
}

export interface GroupedEvents {
  type: string
  count: number
  latestAt: string
  events: RunEventEnvelope[]
}

export function recordValue(records: FlowRecord[], label: string): string | null {
  return records.find((record) => record.label === label)?.value ?? null
}

export function groupNodeArtifacts(artifacts: FlowArtifact[]): GroupedArtifacts[] {
  const map = new Map<string, FlowArtifact[]>()
  for (const artifact of artifacts) {
    const items = map.get(artifact.label) ?? []
    items.push(artifact)
    map.set(artifact.label, items)
  }
  return [...map.entries()].map(([label, items]) => ({ label, items }))
}

export function groupNodeEvents(events: RunEventEnvelope[]): GroupedEvents[] {
  const map = new Map<string, RunEventEnvelope[]>()
  for (const event of events) {
    const items = map.get(event.event_type) ?? []
    items.push(event)
    map.set(event.event_type, items)
  }
  return [...map.entries()]
    .map(([type, items]) => ({
      type,
      count: items.length,
      latestAt: [...items].sort((left, right) => (left.occurred_at < right.occurred_at ? 1 : -1))[0]?.occurred_at ?? '',
      events: [...items].sort((left, right) => right.sequence - left.sequence),
    }))
    .sort((left, right) => (left.latestAt < right.latestAt ? 1 : -1))
}

export function recentNodeEvents(events: RunEventEnvelope[], limit: number): RunEventEnvelope[] {
  return [...events].sort((left, right) => right.sequence - left.sequence).slice(0, limit)
}

export function summarizeEventPayload(payload: Record<string, unknown>): string {
  const text = JSON.stringify(payload)
  if (text.length <= 160) return text
  return `${text.slice(0, 160)}...`
}

export interface NodeActionLink {
  label: string
  to: {
    name: string
    params?: Record<string, string>
    query?: Record<string, string>
  }
}

export function buildNodeActionLinks(
  node: FlowNode,
  queryFactory: (extra?: Record<string, string | undefined>) => Record<string, string>,
): NodeActionLink[] {
  const links: NodeActionLink[] = []
  if (node.runId !== null) {
    links.push({
      label: '查看任務詳情',
      to: { name: 'run', params: { id: node.runId }, query: queryFactory() },
    })
  }

  const candidateId = recordValue(node.records, '候選識別碼')
  const searchRunId = recordValue(node.records, '所屬搜尋任務')
  if (candidateId !== null && searchRunId !== null) {
    links.push({
      label: '回到發現頁',
      to: {
        name: 'discoveries',
        query: queryFactory({ run: searchRunId, pins: candidateId }),
      },
    })
  }

  const submissionId = recordValue(node.records, '提交識別碼')
  if (submissionId !== null) {
    links.push({
      label: '前往驗證頁',
      to: {
        name: 'verification',
        query: queryFactory({ submission: submissionId }),
      },
    })
  }

  if (node.kind === 'VERSION') {
    links.push({
      label: '回到研究版本',
      to: {
        name: 'researches',
        query: queryFactory(),
      },
    })
  }

  return links
}
