/**
 * 證據關聯圖（SSOT 26）的閱讀模型：把研究版本、凍結提交、證據包、validation run 與證明產物
 * 串成一張有向圖，並據此評估「證據共享依賴」與獨立性。
 *
 * 圖只由已讀取到的實體與引用關係建立；沒有讀到的節點不會被補上，也不推測不存在的依賴。
 */
import type { ValidationRun } from './evaluation'
import type { VerificationCenter } from './verificationCenter'
import { VERIFICATION_UNKNOWN } from './verificationCenter'

export type EvidenceNodeKind = 'RESEARCH' | 'VERSION' | 'SUBMISSION' | 'BUNDLE' | 'VALIDATION' | 'PROOF_ARTIFACT'

export const EVIDENCE_NODE_LABELS: Record<EvidenceNodeKind, string> = {
  RESEARCH: '研究',
  VERSION: '研究版本',
  SUBMISSION: '凍結提交',
  BUNDLE: '證據包',
  VALIDATION: '驗證執行',
  PROOF_ARTIFACT: '證明產物',
}

export interface EvidenceGraphNode {
  id: string
  kind: EvidenceNodeKind
  label: string
  sublabel: string
}

export interface EvidenceGraphEdge {
  from: string
  to: string
  label: string
}

/** 被兩個以上證據包共同引用的節點，代表證據之間並非彼此獨立。 */
export interface SharedDependency {
  id: string
  kind: EvidenceNodeKind
  label: string
  referrers: string[]
}

export interface EvidenceIndependence {
  bundles: number
  sharedDependencies: number
  /** 只要有任一共享依賴即視為不獨立。 */
  independent: boolean
  reason: string
}

export interface EvidenceGraph {
  nodes: EvidenceGraphNode[]
  edges: EvidenceGraphEdge[]
  shared: SharedDependency[]
  independence: EvidenceIndependence
}

function nodeId(kind: EvidenceNodeKind, id: string): string {
  return `${kind.toLowerCase()}:${id}`
}

/** 建立證據關聯圖；只有實際上被引用到的版本、提交、驗證與產物才會成為節點。 */
export function buildEvidenceGraph(center: VerificationCenter): EvidenceGraph {
  const nodes = new Map<string, EvidenceGraphNode>()
  const edges: EvidenceGraphEdge[] = []
  const edgeKeys = new Set<string>()

  const addNode = (kind: EvidenceNodeKind, id: string, label: string, sublabel: string): string => {
    const key = nodeId(kind, id)
    if (!nodes.has(key)) nodes.set(key, { id: key, kind, label, sublabel })
    return key
  }
  const addEdge = (from: string, to: string, label: string): void => {
    const key = `${from}->${to}`
    if (edgeKeys.has(key)) return
    edgeKeys.add(key)
    edges.push({ from, to, label })
  }

  const validationReferrers = new Map<string, { validation: ValidationRun | null; bundleIds: string[] }>()
  const proofReferrers = new Map<string, string[]>()

  for (const item of center.evidenceItems) {
    const versionId = item.version.id
    const researchId = item.research?.id ?? null
    const versionNode = addNode('VERSION', versionId, '研究版本', versionId)
    if (researchId !== null) {
      const researchNode = addNode('RESEARCH', researchId, item.research?.name ?? '未命名研究', researchId)
      addEdge(researchNode, versionNode, '擁有版本')
    }

    const validations = center.submissionRows
      .filter((row) => row.version.id === versionId)
      .flatMap((row) => row.validations)
    const validationsById = new Map(validations.map((validation) => [validation.id, validation]))

    for (const submissionId of item.version.frozen_submission_ids) {
      const submissionNode = addNode('SUBMISSION', submissionId, '凍結提交', submissionId)
      addEdge(versionNode, submissionNode, '凍結提交')
    }

    for (const bundle of item.bundles) {
      const bundleNode = addNode('BUNDLE', bundle.id, '證據包', `${bundle.status} / r${String(bundle.revision)}`)
      addEdge(versionNode, bundleNode, '證據包')

      for (const validationId of bundle.validationIds) {
        const validationNode = addNode(
          'VALIDATION',
          validationId,
          validationsById.get(validationId)?.outcome ?? VERIFICATION_UNKNOWN,
          validationId,
        )
        addEdge(bundleNode, validationNode, '引用驗證')
        const entry = validationReferrers.get(validationId) ?? { validation: validationsById.get(validationId) ?? null, bundleIds: [] }
        if (!entry.bundleIds.includes(bundle.id)) entry.bundleIds.push(bundle.id)
        validationReferrers.set(validationId, entry)
      }

      for (const artifactId of bundle.proofArtifactIds) {
        const artifact = center.proofArtifacts[artifactId] ?? null
        const artifactNode = addNode(
          'PROOF_ARTIFACT',
          artifactId,
          artifact?.status ?? VERIFICATION_UNKNOWN,
          artifactId,
        )
        addEdge(bundleNode, artifactNode, '引用證明產物')
        const referrers = proofReferrers.get(artifactId) ?? []
        if (!referrers.includes(bundle.id)) referrers.push(bundle.id)
        proofReferrers.set(artifactId, referrers)
      }
    }
  }

  const shared: SharedDependency[] = []
  for (const [validationId, entry] of validationReferrers) {
    if (entry.bundleIds.length < 2) continue
    shared.push({
      id: nodeId('VALIDATION', validationId),
      kind: 'VALIDATION',
      label: entry.validation?.outcome ?? VERIFICATION_UNKNOWN,
      referrers: [...entry.bundleIds],
    })
  }
  for (const [artifactId, referrers] of proofReferrers) {
    if (referrers.length < 2) continue
    shared.push({
      id: nodeId('PROOF_ARTIFACT', artifactId),
      kind: 'PROOF_ARTIFACT',
      label: '證明產物',
      referrers: [...referrers],
    })
  }

  const bundles = [...nodes.values()].filter((node) => node.kind === 'BUNDLE').length
  // 少於兩個證據包時無從比較獨立性；Fail-Closed 下不宣告獨立。
  const independent = bundles >= 2 && shared.length === 0

  return {
    nodes: [...nodes.values()],
    edges,
    shared,
    independence: {
      bundles,
      sharedDependencies: shared.length,
      independent,
      reason:
        bundles < 2
          ? '少於兩個證據包，尚無從比較獨立性（不視為獨立）。'
          : independent
            ? '目前讀到的證據包之間沒有共同的 validation 或證明產物。'
            : `有 ${String(shared.length)} 個節點被多個證據包共同引用，證據之間存在共享依賴。`,
    },
  }
}

export interface EvidenceTrace {
  node: EvidenceGraphNode
  upstream: EvidenceGraphNode[]
  downstream: EvidenceGraphNode[]
}

/** 以圖中實際存在的邊回推來源與後續；節點不存在時回 null，不捏造關聯。 */
export function findEvidenceTrace(graph: EvidenceGraph, nodeId: string): EvidenceTrace | null {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]))
  const target = byId.get(nodeId)
  if (target === undefined) return null

  const incoming = new Map<string, string[]>()
  const outgoing = new Map<string, string[]>()
  for (const edge of graph.edges) {
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge.to])
    incoming.set(edge.to, [...(incoming.get(edge.to) ?? []), edge.from])
  }

  const collect = (next: (id: string) => string[]): EvidenceGraphNode[] => {
    const seen = new Set<string>([nodeId])
    const queue = [...next(nodeId)]
    const result: EvidenceGraphNode[] = []
    while (queue.length > 0) {
      const id = queue.shift()
      if (id === undefined || seen.has(id)) continue
      seen.add(id)
      const node = byId.get(id)
      if (node === undefined) continue
      result.push(node)
      queue.push(...next(id))
    }
    return result
  }

  return {
    node: target,
    upstream: collect((id) => incoming.get(id) ?? []),
    downstream: collect((id) => outgoing.get(id) ?? []),
  }
}

export function summarizeEvidenceNodes(graph: EvidenceGraph): Array<{ kind: EvidenceNodeKind; count: number }> {
  const counts = new Map<EvidenceNodeKind, number>()
  for (const node of graph.nodes) counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1)
  return [...counts.entries()].map(([kind, count]) => ({ kind, count }))
}
