import { describe, expect, it } from 'vitest'
import type { FlowEdge, FlowGraph, FlowNode, FlowNodeKind } from '../src/lib/flow'
import { buildDerivationTrace, findBranchSources, summarizeDerivationKinds } from '../src/lib/derivationGraph'

function node(id: string, kind: FlowNodeKind, column: number): FlowNode {
  return {
    id,
    kind,
    column,
    row: 0,
    title: id,
    subtitle: '',
    badge: '—',
    tone: 'NEUTRAL',
    records: [],
    artifacts: [],
    events: [],
    runId: null,
  }
}

function edge(from: string, to: string): FlowEdge {
  return { from, to, branch: false }
}

/** 資料集 → 研究版本 → SEARCH 任務 → 兩條候選分支。 */
function graph(): FlowGraph {
  return {
    nodes: [
      node('dataset:1', 'DATASET', 0),
      node('version:1', 'VERSION', 1),
      node('run:1', 'RUN', 2),
      node('candidate:1', 'CANDIDATE', 4),
      node('candidate:2', 'CANDIDATE', 4),
    ],
    edges: [
      edge('dataset:1', 'version:1'),
      edge('version:1', 'run:1'),
      edge('run:1', 'candidate:1'),
      edge('run:1', 'candidate:2'),
    ],
    columns: 7,
    rows: 2,
  }
}

describe('buildDerivationTrace', () => {
  it('walks upstream dependencies using only the edges that exist', () => {
    const trace = buildDerivationTrace(graph(), 'candidate:1')
    expect(trace).not.toBeNull()
    expect(trace?.node.kind).toBe('CANDIDATE')
    expect(trace?.upstream.map((row) => row.id)).toEqual(['run:1', 'version:1', 'dataset:1'])
    expect(trace?.downstream).toEqual([])
  })

  it('walks downstream derivations from a branching run', () => {
    const trace = buildDerivationTrace(graph(), 'run:1')
    expect(trace?.upstream.map((row) => row.id)).toEqual(['version:1', 'dataset:1'])
    expect(trace?.downstream.map((row) => row.id)).toEqual(['candidate:1', 'candidate:2'])
  })

  it('returns null for a node the graph does not contain', () => {
    expect(buildDerivationTrace(graph(), 'candidate:missing')).toBeNull()
  })

  it('reports no upstream when the node has no incoming edges', () => {
    const trace = buildDerivationTrace(graph(), 'dataset:1')
    expect(trace?.upstream).toEqual([])
    expect(trace?.downstream).toHaveLength(4)
  })
})

describe('summarizeDerivationKinds', () => {
  it('counts only the kinds that actually appear', () => {
    expect(summarizeDerivationKinds(graph())).toEqual([
      { kind: 'DATASET', count: 1 },
      { kind: 'VERSION', count: 1 },
      { kind: 'RUN', count: 1 },
      { kind: 'CANDIDATE', count: 2 },
    ])
  })
})

describe('findBranchSources', () => {
  it('lists only nodes that split into more than one edge', () => {
    expect(findBranchSources(graph())).toEqual(['run:1'])
  })

  it('returns nothing when every node has at most one outgoing edge', () => {
    const linear: FlowGraph = {
      nodes: [node('a', 'DATASET', 0), node('b', 'VERSION', 1)],
      edges: [edge('a', 'b')],
      columns: 7,
      rows: 1,
    }
    expect(findBranchSources(linear)).toEqual([])
  })
})
