import { describe, expect, it } from 'vitest'
import type { Candidate, EquationVersion, FitRun } from '../src/api/candidates'
import type { ResearchVersion } from '../src/api/research'
import type { Run } from '../src/api/runs'
import type { RunEventEnvelope } from '../src/lib/events'
import type { QualityReport } from '../src/lib/evidence'
import type { ValidationRun } from '../src/lib/evaluation'
import type { FinalEvaluation } from '../src/lib/finalEvaluation'
import { buildFlow, FLOW_KIND_LABELS, type FlowGraph } from '../src/lib/flow'

const VERSION_ID = '22222222-2222-2222-2222-222222222222'
const DATASET_VERSION_ID = '33333333-3333-3333-3333-333333333333'
const SEARCH_RUN_ID = 'search-run'
const VALIDATION_ID = 'validation-run'
const SUBMISSION_ID = '77777777-7777-7777-7777-777777777777'

function version(overrides: Partial<ResearchVersion> = {}): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id: VERSION_ID,
    tenant_id: '55555555-5555-5555-5555-555555555555',
    schema_version: '2.0',
    created_at: '2026-10-21T00:00:00Z',
    research_id: '11111111-1111-1111-1111-111111111111',
    dataset_version_id: DATASET_VERSION_ID,
    semantic_profile: {
      inputs: [
        { name: 'x', unit: [], source_column: 'x_col', conversion: { source_unit: '1', scale: '1', offset: '0' } },
      ],
      target: { name: 'y', unit: [], source_column: 'y_col', conversion: { source_unit: '1', scale: '1', offset: '0' } },
      units_confirmed: true,
      time_ordered: false,
      measurement_resolution: null,
      resolution_reason: '欄位以 0.001 為最小刻度。',
      group_column: null,
    },
    budget: { cpu_seconds: 60, gpu_seconds: 0, wall_seconds: 120, tokens: 0, candidate_limit: 0, memory_bytes: 2147483648 },
    purpose: 'DESCRIPTION',
    status: 'READY',
    revision: 3,
    observation_split: {
      kind: 'EXPLICIT',
      dataset_version_id: DATASET_VERSION_ID,
      fit: [0, 1],
      development: [2],
      final_test: [3],
      gap_rows: 0,
      lookback_rows: 0,
      horizon_rows: 0,
      seed: 0,
      time_column: null,
      group_column: null,
      group_assignment_digest: null,
      splitter_version: 'axiom-ui-sequential-v1',
      policy_version: '2.0',
      sealed_final_test: true,
      id: 'split-1',
      row_ids_hash: 'a'.repeat(64),
      sealed_test_id: null,
    },
    current_event_cursor: 'RESEARCH:22222222-2222-2222-2222-222222222222:0',
    frozen_submission_ids: [],
    evidence_bundle_ids: [],
    quality_report_id: null,
    refit_policy_artifact_id: null,
    domain: [],
    evaluation_policy: {
      policy_version: '1.0',
      metric_version: '2.0',
      error_model: 'UNSPECIFIED',
      absolute_error_bound: null,
      comparison_method: 'NONE',
      bootstrap_replicates: 2000,
      bootstrap_seed: 0,
      block_method: null,
      block_length: null,
      practical_scale_override: null,
      practical_margin_ratio: '0.01',
      baseline: 'FIT_MEAN',
      practical_scale_reason: null,
    },
    evaluation_policy_hash: 'b'.repeat(64),
    research_budget_usage: {
      cpu_seconds: 12,
      gpu_seconds: 0,
      tokens: 0,
      peak_memory_bytes: 1024,
      elapsed_wall_seconds: 30,
      candidates_generated: 3,
      candidates_accepted: 1,
    },
    structure_assessment_artifact_id: null,
    ...overrides,
  }
}

function run(overrides: Partial<Run> & Pick<Run, 'id' | 'type' | 'status'>): Run {
  return {
    kind: 'Run',
    revision: 1,
    created_at: '2026-10-21T00:00:00Z',
    dataset_id: null,
    research_version_id: VERSION_ID,
    current_event_cursor: `RUN:${overrides.id}:0`,
    ...overrides,
  }
}

function candidate(overrides: Partial<Candidate> & Pick<Candidate, 'id'>): Candidate {
  return {
    kind: 'Candidate',
    tenant_id: '55555555-5555-5555-5555-555555555555',
    schema_version: '2.0',
    created_at: '2026-10-21T00:00:00Z',
    search_run_id: SEARCH_RUN_ID,
    equation_version_id: 'equation-1',
    source: 'POLYNOMIAL',
    development_rank: 1,
    validation_status: 'NOT_RUN',
    fit_run_ids: [],
    validation_run_ids: [],
    ...overrides,
  }
}

function validation(): ValidationRun {
  return {
    id: VALIDATION_ID,
    outcome: 'SUPPORTED',
    metricVersion: '2.0',
    splitRole: 'FINAL_TEST',
    empiricalLevel: 'E2',
    proofLevel: 'P0',
    mae: 0.5,
    rmse: 0.7,
    metricReasons: {},
    validCoverage: 1,
    selectedCount: 1,
    validCount: 1,
    failedCount: 0,
    sha256: 'c'.repeat(64),
    createdAt: '2026-10-21T00:00:00Z',
  }
}

function submission(): FinalEvaluation {
  return {
    submissionId: SUBMISSION_ID,
    metricVersion: '2.0',
    status: 'EVALUATED',
    slots: [
      {
        frozenCandidateId: '99999999-9999-9999-9999-999999999999',
        slotId: '88888888-8888-8888-8888-888888888888',
        runId: '44444444-4444-4444-4444-444444444444',
        validationRunId: VALIDATION_ID,
        status: 'COMPLETED',
      },
    ],
    exposure: { budget: 4, reserved: 0, consumed: 1, retired: 0 },
  }
}

function nodeById(graph: FlowGraph, id: string): FlowGraph['nodes'][number] | undefined {
  return graph.nodes.find((node) => node.id === id)
}

function recordValue(graph: FlowGraph, nodeId: string, label: string): string | undefined {
  return nodeById(graph, nodeId)?.records.find((record) => record.label === label)?.value
}

describe('buildFlow', () => {
  it('always starts from the dataset version and ends at the研究版本 right after it', () => {
    const graph = buildFlow({ version: version(), runs: [], candidates: [] })
    const dataset = nodeById(graph, `dataset:${DATASET_VERSION_ID}`)
    const research = nodeById(graph, `version:${VERSION_ID}`)
    expect(dataset?.kind).toBe('DATASET')
    expect(dataset?.column).toBe(0)
    expect(research?.kind).toBe('VERSION')
    expect(research?.column).toBe(1)
    expect(graph.edges).toContainEqual({ from: `dataset:${DATASET_VERSION_ID}`, to: `version:${VERSION_ID}`, branch: false })
  })

  it('lays nodes into the fixed left-to-right columns per kind', () => {
    const graph = buildFlow({
      version: version({ quality_report_id: 'quality-1', frozen_submission_ids: [SUBMISSION_ID] }),
      runs: [run({ id: SEARCH_RUN_ID, type: 'SEARCH', status: 'SUCCEEDED' })],
      candidates: [candidate({ id: 'cand-1', validation_run_ids: [VALIDATION_ID] })],
      finalEvaluations: { [SUBMISSION_ID]: submission() },
      evaluations: { [VALIDATION_ID]: validation() },
    })
    for (const node of graph.nodes) {
      switch (node.kind) {
        case 'DATASET':
          expect(node.column).toBe(0)
          break
        case 'VERSION':
          expect(node.column).toBe(1)
          break
        case 'RUN':
          expect(node.column).toBe(2)
          break
        case 'EVIDENCE':
          expect(node.column).toBe(3)
          break
        case 'CANDIDATE':
          expect(node.column).toBe(4)
          break
        case 'SUBMISSION':
          expect(node.column).toBe(5)
          break
        case 'VALIDATION':
          expect(node.column).toBe(6)
          break
      }
    }
    expect(graph.columns).toBe(7)
  })

  it('marks every edge out of a SEARCH run as a branch when it produces several candidates', () => {
    const graph = buildFlow({
      version: version(),
      runs: [run({ id: SEARCH_RUN_ID, type: 'SEARCH', status: 'SUCCEEDED' })],
      candidates: [
        candidate({ id: 'cand-b', development_rank: 1 }),
        candidate({ id: 'cand-c', development_rank: 2 }),
        candidate({ id: 'cand-d', development_rank: 3 }),
      ],
    })
    const branches = graph.edges.filter((edge) => edge.from === `run:${SEARCH_RUN_ID}`)
    expect(branches).toHaveLength(3)
    expect(branches.every((edge) => edge.branch)).toBe(true)
    // 版本只有這條任務邊，因此不算分支。
    const versionEdges = graph.edges.filter((edge) => edge.from === `version:${VERSION_ID}`)
    expect(versionEdges).toHaveLength(1)
    expect(versionEdges[0]?.branch).toBe(false)
  })

  it('omits the品質與封存 node when no evidence references exist', () => {
    const graph = buildFlow({ version: version(), runs: [], candidates: [] })
    expect(graph.nodes.some((node) => node.kind === 'EVIDENCE')).toBe(false)
  })

  it('adds the品質與封存 node when a sealed test is registered', () => {
    const graph = buildFlow({
      version: version({
        observation_split: { ...version().observation_split, sealed_test_id: 'sealed-1' },
      }),
      runs: [],
      candidates: [],
      quality: {
        quality: 'BLOCKED',
        readiness: 'BLOCKED',
        blockingCode: 'SEALED_TEST_NOT_REGISTERED',
        remaining: ['SEALED_TEST_NOT_REGISTERED'],
        precisionBits: null,
        fitSummary: null,
      } satisfies QualityReport,
    })
    const evidence = graph.nodes.find((node) => node.kind === 'EVIDENCE')
    expect(evidence).toBeDefined()
    expect(evidence?.column).toBe(3)
    expect(evidence?.badge).toBe('BLOCKED')
    expect(evidence?.tone).toBe('FAILED')
  })

  it('keeps nodes for未取得的結果 but never invents values', () => {
    const graph = buildFlow({
      version: version({ frozen_submission_ids: [SUBMISSION_ID] }),
      runs: [],
      candidates: [candidate({ id: 'cand-1', validation_run_ids: [VALIDATION_ID] })],
    })
    const validationNode = nodeById(graph, `validation:${VALIDATION_ID}`)
    expect(validationNode).toBeDefined()
    expect(validationNode?.tone).toBe('NEUTRAL')
    expect(recordValue(graph, `validation:${VALIDATION_ID}`, '內容')).toBe(
      '未取得或格式不符契約，不顯示推測內容',
    )
    expect(recordValue(graph, `submission:${SUBMISSION_ID}`, '狀態')).toBe(
      '未取得或格式不符，不顯示推測內容',
    )
  })

  it('always reports final_test as not yet evaluated, even before any validation exists', () => {
    const graph = buildFlow({
      version: version(),
      runs: [],
      candidates: [candidate({ id: 'cand-1' })],
    })
    expect(recordValue(graph, 'candidate:cand-1', 'final_test')).toBe('尚未評估（凍結前不揭露）')
  })

  it('wires candidate to its validation result and submission slots to theirs', () => {
    const graph = buildFlow({
      version: version({ frozen_submission_ids: [SUBMISSION_ID] }),
      runs: [run({ id: SEARCH_RUN_ID, type: 'SEARCH', status: 'SUCCEEDED' })],
      candidates: [candidate({ id: 'cand-1', validation_run_ids: [VALIDATION_ID] })],
      finalEvaluations: { [SUBMISSION_ID]: submission() },
      evaluations: { [VALIDATION_ID]: validation() },
    })
    expect(graph.edges).toContainEqual({ from: 'candidate:cand-1', to: `validation:${VALIDATION_ID}`, branch: false })
    expect(graph.edges).toContainEqual({
      from: `submission:${SUBMISSION_ID}`,
      to: `validation:${VALIDATION_ID}`,
      branch: false,
    })
    expect(recordValue(graph, `validation:${VALIDATION_ID}`, '結果判定')).toBe('支持（SUPPORTED）')
  })

  it('attaches run-scoped events to their run and research-scoped events to the version', () => {
    const event = (id: string, runId: string | null): RunEventEnvelope => ({
      event_id: id,
      event_type: 'RunStateChanged',
      sequence: 1,
      occurred_at: '2026-10-21T00:00:00Z',
      run_id: runId,
      stream_scope: runId === null ? 'RESEARCH' : 'RUN',
      payload: {},
    })
    const graph = buildFlow({
      version: version(),
      runs: [run({ id: SEARCH_RUN_ID, type: 'SEARCH', status: 'RUNNING' })],
      candidates: [],
      events: [event('e-run', SEARCH_RUN_ID), event('e-research', null)],
    })
    expect(nodeById(graph, `run:${SEARCH_RUN_ID}`)?.events.map((entry) => entry.event_id)).toEqual(['e-run'])
    expect(nodeById(graph, `version:${VERSION_ID}`)?.events.map((entry) => entry.event_id)).toEqual(['e-research'])
  })

  it('exposes順序穩定的任務節點並保留契約 ID', () => {
    const graph = buildFlow({
      version: version(),
      runs: [
        run({ id: 'run-late', type: 'PROFILE', status: 'SUCCEEDED', created_at: '2026-10-21T02:00:00Z' }),
        run({ id: 'run-early', type: 'SEARCH', status: 'SUCCEEDED', created_at: '2026-10-21T01:00:00Z' }),
      ],
      candidates: [],
    })
    const runIds = graph.nodes.filter((node) => node.kind === 'RUN').map((node) => node.id)
    expect(runIds).toEqual(['run:run-early', 'run:run-late'])
  })

  it('labels every kind for the legend', () => {
    expect(FLOW_KIND_LABELS.DATASET).toBe('資料集版本')
    expect(FLOW_KIND_LABELS.CANDIDATE).toBe('候選假設')
    expect(Object.keys(FLOW_KIND_LABELS)).toHaveLength(7)
  })

  it('uses equation and fit data when provided, without inventing a fit when missing', () => {
    const equation: EquationVersion = {
      kind: 'EquationVersion',
      id: 'equation-1',
      tenant_id: '55555555-5555-5555-5555-555555555555',
      schema_version: '2.0',
      created_at: '2026-10-21T00:00:00Z',
      dsl: {
        dsl_version: '1.0',
        variables: [{ name: 'x', unit: [] }],
        parameters: [{ name: 'a', unit: [], lower: '0', upper: '1' }],
        domain: [],
        root: { op: 'var', name: 'x' },
      },
      identity_hash: 'd'.repeat(64),
    }
    const fit: FitRun = {
      kind: 'FitRun',
      id: 'fit-1',
      tenant_id: '55555555-5555-5555-5555-555555555555',
      schema_version: '2.0',
      created_at: '2026-10-21T00:00:00Z',
      run_id: SEARCH_RUN_ID,
      equation_version_id: 'equation-1',
      dataset_version_id: DATASET_VERSION_ID,
      parameters: { a: '0.5' },
      optimizer: 'LBFGS',
      observation_split_id: 'split-1',
      split_role: 'FIT',
      precision_bits: 53,
      fit_row_ids: [0, 1],
      fit_rows_hash: 'e'.repeat(64),
      representation_artifact_id: 'artifact-1',
    }
    const graph = buildFlow({
      version: version(),
      runs: [],
      candidates: [candidate({ id: 'cand-1', fit_run_ids: ['fit-1'] })],
      equations: { 'equation-1': equation },
      fits: { 'fit-1': fit },
    })
    expect(recordValue(graph, 'candidate:cand-1', '公式身分雜湊')).toBe('d'.repeat(64))
    expect(recordValue(graph, 'candidate:cand-1', '參數')).toBe('a = 0.5')
    expect(recordValue(graph, 'candidate:cand-1', '擬合列數')).toBe('2')
  })
})
