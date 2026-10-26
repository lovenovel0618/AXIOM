/**
 * SSOT 21「研究推演」的依賴推導：以流程圖已存在的邊為唯一依據，計算某一節點的依賴前提與後續推演。
 *
 * 只有契約明載的歸屬關係才會被畫成邊（任務→候選、候選→驗證、版本→提交…）；
 * 因此「沒有邊」就是「後端沒有揭露依賴」，不得用節點順序或命名回推關係。
 */
import type { FlowGraph, FlowNode, FlowNodeKind } from './flow'

export interface DerivationTrace {
  /** 被選取的節點本身。 */
  node: FlowNode
  /** 依賴前提：沿邊回溯可達的祖先節點（越上游越前面）。 */
  upstream: FlowNode[]
  /** 後續推演：沿邊前進可達的後代節點（越下游越後面）。 */
  downstream: FlowNode[]
}

function buildAdjacency(graph: FlowGraph): { forward: Map<string, string[]>; backward: Map<string, string[]> } {
  const forward = new Map<string, string[]>()
  const backward = new Map<string, string[]>()
  for (const edge of graph.edges) {
    forward.set(edge.from, [...(forward.get(edge.from) ?? []), edge.to])
    backward.set(edge.to, [...(backward.get(edge.to) ?? []), edge.from])
  }
  return { forward, backward }
}

/** 廣度優先走訪；只走實際存在的邊，遇到同一節點重複可達時只記一次。 */
function walk(graph: FlowGraph, links: Map<string, string[]>, start: string): FlowNode[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]))
  const seen = new Set<string>([start])
  const queue = [...(links.get(start) ?? [])]
  const result: FlowNode[] = []

  while (queue.length > 0) {
    const id = queue.shift()
    if (id === undefined || seen.has(id)) continue
    seen.add(id)
    const node = byId.get(id)
    if (node !== undefined) result.push(node)
    queue.push(...(links.get(id) ?? []))
  }

  return result
}

/** 找不到節點時回 null，畫面據此顯示「未取得」而不是顯示空依賴。 */
export function buildDerivationTrace(graph: FlowGraph, nodeId: string): DerivationTrace | null {
  const node = graph.nodes.find((row) => row.id === nodeId)
  if (node === undefined) return null
  const { forward, backward } = buildAdjacency(graph)
  return {
    node,
    upstream: walk(graph, backward, nodeId),
    downstream: walk(graph, forward, nodeId),
  }
}

export interface DerivationCount {
  kind: FlowNodeKind
  count: number
}

/** 依實際出現的節點種類統計，供頁首摘要；缺的種類不會出現 0 筆假資料。 */
export function summarizeDerivationKinds(graph: FlowGraph): DerivationCount[] {
  const counts = new Map<FlowNodeKind, number>()
  for (const node of graph.nodes) counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1)
  return [...counts.entries()].map(([kind, count]) => ({ kind, count }))
}

/** 分支節點：從同一父節點分出多條邊的來源；代表後端揭露了並行的候選分支。 */
export function findBranchSources(graph: FlowGraph): string[] {
  const outgoing = new Map<string, number>()
  for (const edge of graph.edges) outgoing.set(edge.from, (outgoing.get(edge.from) ?? 0) + 1)
  return [...outgoing.entries()].filter(([, count]) => count > 1).map(([id]) => id)
}
