import type { FlowArtifact, FlowNode, FlowRecord, FlowTone } from './flow'
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

export interface CandidateCollectionLink {
  searchRunId: string
  candidateIds: string[]
  label: string
}

export interface SubmissionCollectionLink {
  submissionIds: string[]
  label: string
}

export interface FocusSummaryBase {
  requestedIds: string[]
  matchedValues: string[]
  matchedNodeIds: string[]
  missingIds: string[]
}

export interface CandidateFocusSummary extends FocusSummaryBase {
  groups: CandidateCollectionLink[]
}

export interface SubmissionFocusSummary extends FocusSummaryBase {
  group: SubmissionCollectionLink | null
}

export interface FocusDetailItem {
  nodeId: string
  title: string
  subtitle: string
  badge: string
  tone: FlowTone
  primaryValue: string
  secondaryValue: string | null
  artifactCount: number
  eventCount: number
}

export interface FocusDetailPanel extends FocusSummaryBase {
  /** 這個集合以哪個欄位辨識成員；供集合彙總沿用同一組成員。 */
  recordLabel: string
  items: FocusDetailItem[]
  totalArtifacts: number
  totalEvents: number
  toneCounts: Record<FlowTone, number>
}

export interface CollectionArtifactItem {
  id: string
  label: string
  sourceNodeId: string
  sourceTitle: string
  sourceValue: string
}

export interface CollectionArtifactGroup {
  label: string
  items: CollectionArtifactItem[]
  /** 這個產物標籤出現在幾個成員上。 */
  memberCount: number
  shared: boolean
}

export interface CollectionEventGroup {
  type: string
  count: number
  latestAt: string
  memberCount: number
  shared: boolean
  recent: RunEventEnvelope[]
}

export interface CollectionMemberStat {
  nodeId: string
  title: string
  value: string
  artifactCount: number
  eventCount: number
  latestEventAt: string
}

export interface CollectionDigest {
  memberStats: CollectionMemberStat[]
  artifactGroups: CollectionArtifactGroup[]
  eventGroups: CollectionEventGroup[]
  sharedArtifactLabels: string[]
  sharedEventTypes: string[]
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter((value) => value !== ''))]
}

function emptyToneCounts(): Record<FlowTone, number> {
  return {
    OK: 0,
    PENDING: 0,
    RUNNING: 0,
    FAILED: 0,
    NEUTRAL: 0,
  }
}

function orderedMatchedNodes(nodes: FlowNode[], label: string, requested: string[]): FlowNode[] {
  const byValue = new Map<string, FlowNode>()
  for (const node of nodes) {
    const value = recordValue(node.records, label)
    if (value === null || byValue.has(value)) continue
    byValue.set(value, node)
  }

  const ordered = requested.map((value) => byValue.get(value)).filter((node): node is FlowNode => node !== undefined)
  if (ordered.length !== 0) return ordered
  return nodes
}

function buildFocusDetailPanel(
  nodes: FlowNode[],
  requestedIds: string[],
  primaryLabel: string,
  secondaryLabel: string | null,
): FocusDetailPanel | null {
  const requested = uniqueValues(requestedIds)
  if (requested.length === 0) return null

  const expected = new Set(requested)
  const matchedNodes = nodes.filter((node) => {
    const value = recordValue(node.records, primaryLabel)
    return value !== null && expected.has(value)
  })
  const orderedNodes = orderedMatchedNodes(matchedNodes, primaryLabel, requested)
  const matchedValues = uniqueValues(
    orderedNodes
      .map((node) => recordValue(node.records, primaryLabel))
      .filter((value): value is string => value !== null),
  )
  const toneCounts = emptyToneCounts()
  const items = orderedNodes.map((node) => {
    toneCounts[node.tone] += 1
    return {
      nodeId: node.id,
      title: node.title,
      subtitle: node.subtitle,
      badge: node.badge,
      tone: node.tone,
      primaryValue: recordValue(node.records, primaryLabel) ?? node.id,
      secondaryValue: secondaryLabel === null ? null : recordValue(node.records, secondaryLabel),
      artifactCount: node.artifacts.length,
      eventCount: node.events.length,
    }
  })

  return {
    requestedIds: requested,
    matchedValues,
    matchedNodeIds: items.map((item) => item.nodeId),
    missingIds: requested.filter((id) => !matchedValues.includes(id)),
    recordLabel: primaryLabel,
    items,
    totalArtifacts: items.reduce((sum, item) => sum + item.artifactCount, 0),
    totalEvents: items.reduce((sum, item) => sum + item.eventCount, 0),
    toneCounts,
  }
}

export function buildNodeActionLinks(
  node: FlowNode,
  queryFactory: (extra?: Record<string, string | undefined>) => Record<string, string>,
  /** 目前工作台所屬的研究容器；缺少時無法組出工作台路徑，該連結一律不產生。 */
  researchId?: string,
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

  if (node.kind === 'VERSION' && researchId !== undefined && researchId !== '') {
    links.push({
      label: '回到研究版本',
      to: {
        name: 'research-workbench',
        params: { id: researchId },
        query: queryFactory(),
      },
    })
  }

  return links
}

export function collectCandidateCollectionLinks(nodes: FlowNode[]): CandidateCollectionLink[] {
  const groups = new Map<string, { ids: string[]; titles: string[] }>()
  for (const node of nodes) {
    if (node.kind !== 'CANDIDATE') continue
    const candidateId = recordValue(node.records, '候選識別碼')
    const searchRunId = recordValue(node.records, '所屬搜尋任務')
    if (candidateId === null || searchRunId === null) continue
    const current = groups.get(searchRunId) ?? { ids: [], titles: [] }
    current.ids.push(candidateId)
    current.titles.push(node.title)
    groups.set(searchRunId, current)
  }

  return [...groups.entries()]
    .map(([searchRunId, current]) => ({
      searchRunId,
      candidateIds: current.ids,
      label:
        current.ids.length === 1
          ? `${current.titles[0] ?? '候選'}`
          : `${current.ids.length} 個候選節點`,
    }))
    .sort((left, right) => right.candidateIds.length - left.candidateIds.length)
}

export function collectSubmissionCollectionLink(nodes: FlowNode[]): SubmissionCollectionLink | null {
  const submissionIds = nodes
    .filter((node) => node.kind === 'SUBMISSION')
    .map((node) => recordValue(node.records, '提交識別碼'))
    .filter((value): value is string => value !== null)

  if (submissionIds.length === 0) return null
  return {
    submissionIds,
    label: submissionIds.length === 1 ? '1 個提交節點' : `${submissionIds.length} 個提交節點`,
  }
}

export function findNodeIdsByRecordValues(nodes: FlowNode[], label: string, values: string[]): string[] {
  if (values.length === 0) return []
  const expected = new Set(values)
  return nodes
    .filter((node) => {
      const value = recordValue(node.records, label)
      return value !== null && expected.has(value)
    })
    .map((node) => node.id)
}

export function buildCandidateFocusSummary(nodes: FlowNode[], requestedIds: string[]): CandidateFocusSummary | null {
  const requested = uniqueValues(requestedIds)
  if (requested.length === 0) return null

  const expected = new Set(requested)
  const matchedNodes = nodes.filter((node) => {
    if (node.kind !== 'CANDIDATE') return false
    const candidateId = recordValue(node.records, '候選識別碼')
    return candidateId !== null && expected.has(candidateId)
  })
  const matchedValues = uniqueValues(
    matchedNodes
      .map((node) => recordValue(node.records, '候選識別碼'))
      .filter((value): value is string => value !== null),
  )

  return {
    requestedIds: requested,
    matchedValues,
    matchedNodeIds: matchedNodes.map((node) => node.id),
    missingIds: requested.filter((candidateId) => !matchedValues.includes(candidateId)),
    groups: collectCandidateCollectionLinks(matchedNodes),
  }
}

export function buildSubmissionFocusSummary(nodes: FlowNode[], requestedIds: string[]): SubmissionFocusSummary | null {
  const requested = uniqueValues(requestedIds)
  if (requested.length === 0) return null

  const expected = new Set(requested)
  const matchedNodes = nodes.filter((node) => {
    if (node.kind !== 'SUBMISSION') return false
    const submissionId = recordValue(node.records, '提交識別碼')
    return submissionId !== null && expected.has(submissionId)
  })
  const matchedValues = uniqueValues(
    matchedNodes
      .map((node) => recordValue(node.records, '提交識別碼'))
      .filter((value): value is string => value !== null),
  )

  return {
    requestedIds: requested,
    matchedValues,
    matchedNodeIds: matchedNodes.map((node) => node.id),
    missingIds: requested.filter((submissionId) => !matchedValues.includes(submissionId)),
    group: collectSubmissionCollectionLink(matchedNodes),
  }
}

export function buildCandidateFocusDetailPanel(nodes: FlowNode[], requestedIds: string[]): FocusDetailPanel | null {
  return buildFocusDetailPanel(
    nodes.filter((node) => node.kind === 'CANDIDATE'),
    requestedIds,
    '候選識別碼',
    '所屬搜尋任務',
  )
}

export function buildSubmissionFocusDetailPanel(nodes: FlowNode[], requestedIds: string[]): FocusDetailPanel | null {
  return buildFocusDetailPanel(nodes.filter((node) => node.kind === 'SUBMISSION'), requestedIds, '提交識別碼', null)
}

/**
 * 把一組焦點成員的產物與事件彙總成集合層級檢視。
 * 只依節點已揭露的產物與事件計算，並標示哪些項目跨成員共用，不補任何推測內容。
 */
export function buildFocusCollectionDigest(nodes: FlowNode[], panel: FocusDetailPanel): CollectionDigest | null {
  if (panel.items.length === 0) return null
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const members = panel.items
    .map((item) => ({ item, node: byId.get(item.nodeId) }))
    .filter((entry): entry is { item: FocusDetailItem; node: FlowNode } => entry.node !== undefined)
  if (members.length === 0) return null

  const artifactMap = new Map<string, CollectionArtifactItem[]>()
  const eventMap = new Map<string, { count: number; latestAt: string; events: RunEventEnvelope[]; memberIds: Set<string> }>()

  const memberStats: CollectionMemberStat[] = members.map(({ item, node }) => {
    for (const artifact of node.artifacts) {
      const items = artifactMap.get(artifact.label) ?? []
      items.push({
        id: artifact.id,
        label: artifact.label,
        sourceNodeId: node.id,
        sourceTitle: node.title,
        sourceValue: item.primaryValue,
      })
      artifactMap.set(artifact.label, items)
    }
    for (const event of node.events) {
      const current =
        eventMap.get(event.event_type) ?? { count: 0, latestAt: '', events: [], memberIds: new Set<string>() }
      current.count += 1
      current.events.push(event)
      current.memberIds.add(node.id)
      if (current.latestAt === '' || current.latestAt < event.occurred_at) current.latestAt = event.occurred_at
      eventMap.set(event.event_type, current)
    }
    const latestEventAt =
      [...node.events].map((event) => event.occurred_at).sort((left, right) => (left < right ? 1 : -1))[0] ?? ''
    return {
      nodeId: node.id,
      title: node.title,
      value: item.primaryValue,
      artifactCount: node.artifacts.length,
      eventCount: node.events.length,
      latestEventAt,
    }
  })

  const artifactGroups: CollectionArtifactGroup[] = [...artifactMap.entries()]
    .map(([label, items]) => {
      const memberCount = new Set(items.map((item) => item.sourceNodeId)).size
      return { label, items, memberCount, shared: memberCount > 1 }
    })
    .sort((left, right) => right.memberCount - left.memberCount || right.items.length - left.items.length)

  const eventGroups: CollectionEventGroup[] = [...eventMap.entries()]
    .map(([type, current]) => ({
      type,
      count: current.count,
      latestAt: current.latestAt,
      memberCount: current.memberIds.size,
      shared: current.memberIds.size > 1,
      recent: [...current.events].sort((left, right) => right.sequence - left.sequence).slice(0, 5),
    }))
    .sort((left, right) => right.memberCount - left.memberCount || right.count - left.count)

  return {
    memberStats,
    artifactGroups,
    eventGroups,
    sharedArtifactLabels: artifactGroups.filter((group) => group.shared).map((group) => group.label),
    sharedEventTypes: eventGroups.filter((group) => group.shared).map((group) => group.type),
  }
}
