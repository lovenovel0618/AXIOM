import type { FlowGraph, FlowNode, FlowNodeKind, FlowTone } from './flow'

export interface FlowFilterState {
  kind: 'ALL' | FlowNodeKind
  tone: 'ALL' | FlowTone
  query: string
}

function normalize(value: string): string {
  return value.trim().toLowerCase()
}

function includesQuery(node: FlowNode, query: string): boolean {
  const needle = normalize(query)
  if (needle === '') return true
  return [node.title, node.subtitle, node.badge, node.kind, ...node.records.map((record) => `${record.label} ${record.value}`)]
    .map(normalize)
    .some((value) => value.includes(needle))
}

export function matchesFlowNode(node: FlowNode, filters: FlowFilterState): boolean {
  if (filters.kind !== 'ALL' && node.kind !== filters.kind) return false
  if (filters.tone !== 'ALL' && node.tone !== filters.tone) return false
  return includesQuery(node, filters.query)
}

export function filterFlowGraph(graph: FlowGraph, filters: FlowFilterState): FlowGraph {
  const nodes = graph.nodes.filter((node) => matchesFlowNode(node, filters))
  const visible = new Set(nodes.map((node) => node.id))
  const edges = graph.edges.filter((edge) => visible.has(edge.from) && visible.has(edge.to))

  const rowsByColumn = new Map<number, number>()
  const reflowed = nodes.map((node) => {
    const row = rowsByColumn.get(node.column) ?? 0
    rowsByColumn.set(node.column, row + 1)
    return { ...node, row }
  })

  return {
    nodes: reflowed,
    edges,
    columns: graph.columns,
    rows: reflowed.reduce((best, node) => Math.max(best, node.row + 1), 0),
  }
}

export function highlightFlowNodes(graph: FlowGraph, selectedId: string | null): Set<string> {
  if (selectedId === null) return new Set()
  const highlighted = new Set<string>([selectedId])
  for (const edge of graph.edges) {
    if (edge.from === selectedId) highlighted.add(edge.to)
    if (edge.to === selectedId) highlighted.add(edge.from)
  }
  return highlighted
}
