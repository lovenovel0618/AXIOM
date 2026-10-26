import { describe, expect, it } from 'vitest'
import type { FlowGraph, FlowNode } from '../src/lib/flow'
import { filterFlowGraph, highlightFlowNodes, matchesFlowNode } from '../src/lib/researchFlowFilters'

function node(id: string, overrides: Partial<FlowNode> = {}): FlowNode {
  return {
    id,
    kind: 'RUN',
    column: 2,
    row: 0,
    title: 'SEARCH',
    subtitle: 'running search',
    badge: 'RUNNING',
    tone: 'RUNNING',
    records: [],
    artifacts: [],
    events: [],
    runId: 'run-1',
    ...overrides,
  }
}

function graph(): FlowGraph {
  return {
    nodes: [
      node('dataset:1', { kind: 'DATASET', column: 0, row: 0, title: 'dataset', subtitle: 'source', badge: 'READY', tone: 'OK', runId: null }),
      node('run:1', { kind: 'RUN', column: 2, row: 0 }),
      node('candidate:1', {
        kind: 'CANDIDATE',
        column: 4,
        row: 0,
        title: 'candidate a',
        subtitle: 'poly',
        badge: 'READY',
        tone: 'OK',
        runId: null,
        records: [{ label: '候選識別碼', value: 'cand-1' }],
      }),
      node('candidate:2', {
        kind: 'CANDIDATE',
        column: 4,
        row: 1,
        title: 'candidate b',
        subtitle: 'failed',
        badge: 'FAILED',
        tone: 'FAILED',
        runId: null,
      }),
    ],
    edges: [
      { from: 'dataset:1', to: 'run:1', branch: false },
      { from: 'run:1', to: 'candidate:1', branch: true },
      { from: 'run:1', to: 'candidate:2', branch: true },
    ],
    columns: 5,
    rows: 2,
  }
}

describe('researchFlowFilters', () => {
  it('matches nodes by kind, tone, and free text', () => {
    expect(matchesFlowNode(node('candidate:1', { kind: 'CANDIDATE', tone: 'OK', title: 'Polynomial' }), {
      kind: 'CANDIDATE',
      tone: 'OK',
      query: 'poly',
    })).toBe(true)
    expect(matchesFlowNode(node('run:1'), { kind: 'CANDIDATE', tone: 'ALL', query: '' })).toBe(false)
  })

  it('filters the graph and reflows rows within each column', () => {
    const filtered = filterFlowGraph(graph(), { kind: 'CANDIDATE', tone: 'ALL', query: '' })
    expect(filtered.nodes.map((row) => row.id)).toEqual(['candidate:1', 'candidate:2'])
    expect(filtered.nodes.map((row) => row.row)).toEqual([0, 1])
    expect(filtered.edges).toHaveLength(0)
  })

  it('highlights the selected node and its neighbors', () => {
    expect([...highlightFlowNodes(graph(), 'run:1')].sort()).toEqual(['candidate:1', 'candidate:2', 'dataset:1', 'run:1'])
    expect([...highlightFlowNodes(graph(), null)]).toEqual([])
  })
})
