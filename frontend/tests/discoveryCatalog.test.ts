import { describe, expect, it } from 'vitest'
import type { Candidate, EquationVersion } from '../src/api/candidates'
import type { Research, ResearchVersion } from '../src/api/research'
import type { Run } from '../src/api/runs'
import {
  buildComparisonContextRows,
  buildDiscoveryCatalogCsv,
  buildDiscoveryCatalogRows,
  buildFairComparisonRows,
  DISCOVERY_UNKNOWN,
  filterDiscoveryCatalogRows,
  sortDiscoveryCatalogRows,
  summarizeDiscoveryStatus,
  type DiscoveriesCenter,
  type DiscoveryCatalogRow,
  type DiscoverySearchRun,
} from '../src/lib/discoveries'

const DATASET_VERSION_ID = '44444444-4444-4444-4444-444444444444'

function equation(id: string, root: EquationVersion['dsl']['root'], variables = 1, parameters = 1): EquationVersion {
  return {
    kind: 'EquationVersion',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T03:00:00Z',
    dsl: {
      dsl_version: '1',
      variables: Array.from({ length: variables }, (_, index) => ({ name: `x${String(index)}`, unit: [] })),
      parameters: Array.from({ length: parameters }, (_, index) => ({
        name: `c${String(index)}`,
        unit: [],
        lower: '-1',
        upper: '1',
      })),
      domain: [
        { name: 'x0', lower: { numerator: '0', denominator: '1' }, upper: { numerator: '1', denominator: '1' }, lower_closed: true, upper_closed: true },
      ],
      root,
    },
    identity_hash: 'a'.repeat(64),
  }
}

function candidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    kind: 'Candidate',
    id: 'candidate-1',
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T03:00:00Z',
    search_run_id: 'run-1',
    equation_version_id: 'equation-1',
    source: 'POLYNOMIAL',
    development_rank: 1,
    validation_status: 'NOT_RUN',
    fit_run_ids: ['fit-1'],
    validation_run_ids: [],
    ...overrides,
  }
}

function run(): Run {
  return {
    kind: 'Run',
    id: 'run-1',
    type: 'SEARCH',
    status: 'SUCCEEDED',
    revision: 1,
    created_at: '2026-10-26T02:00:00Z',
    dataset_id: null,
    research_version_id: 'version-1',
    current_event_cursor: 'RUN:run-1:0',
  }
}

function research(): Research {
  return {
    kind: 'Research',
    id: 'research-1',
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T00:00:00Z',
    name: 'sin 週期研究',
    owner_id: 'owner-1',
  }
}

function version(): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id: 'version-1',
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T01:00:00Z',
    research_id: 'research-1',
    dataset_version_id: DATASET_VERSION_ID,
    semantic_profile: {
      inputs: [],
      target: { name: 'y', unit: [], source_column: 'y', conversion: { source_unit: '1', scale: '1', offset: '0' } },
      units_confirmed: true,
      time_ordered: false,
      measurement_resolution: null,
      resolution_reason: 'ok',
      group_column: null,
    },
    budget: { cpu_seconds: 1, gpu_seconds: 0, wall_seconds: 1, tokens: 0, candidate_limit: 1, memory_bytes: 1 },
    purpose: 'DESCRIPTION',
    status: 'READY',
    revision: 1,
    observation_split: {
      id: 'split-1',
      kind: 'EXPLICIT',
      dataset_version_id: DATASET_VERSION_ID,
      fit: [1, 2],
      development: [3],
      final_test: [4, 5],
      gap_rows: 0,
      lookback_rows: 0,
      horizon_rows: 0,
      seed: 0,
      time_column: null,
      group_column: null,
      group_assignment_digest: null,
      splitter_version: 'axiom-ui-sequential-v1',
      policy_version: '1',
      sealed_final_test: true,
      row_ids_hash: 'a'.repeat(64),
      sealed_test_id: null,
    },
    current_event_cursor: 'RESEARCH:1:0',
    frozen_submission_ids: [],
    evidence_bundle_ids: [],
    quality_report_id: null,
    refit_policy_artifact_id: null,
    domain: [],
    evaluation_policy: {
      policy_version: '2.0',
      metric_version: '2.0',
      error_model: 'ABSOLUTE_BOUND',
      absolute_error_bound: '0.01',
      comparison_method: 'IID_PAIRED_BOOTSTRAP',
      bootstrap_replicates: 2000,
      bootstrap_seed: 7,
      block_method: null,
      block_length: null,
      practical_scale_override: null,
      practical_margin_ratio: '0.01',
      baseline: 'FIT_MEAN',
      practical_scale_reason: null,
    },
    evaluation_policy_hash: 'b'.repeat(64),
    research_budget_usage: {
      cpu_seconds: 0,
      gpu_seconds: 0,
      tokens: 0,
      peak_memory_bytes: 0,
      elapsed_wall_seconds: 0,
      candidates_generated: 0,
      candidates_accepted: 0,
    },
    structure_assessment_artifact_id: null,
  }
}

function searchRun(candidates: Candidate[]): DiscoverySearchRun {
  return { run: run(), research: research(), version: version(), candidates }
}

function center(searchRuns: DiscoverySearchRun[]): DiscoveriesCenter {
  return {
    metrics: [],
    searchRuns,
    recentVersions: [version()],
    scope: { researchesRead: 1, versionsRead: 1, versionIds: ['version-1'], searchRunsRead: searchRuns.length, candidatesRead: 0, truncated: false },
  }
}

describe('buildDiscoveryCatalogRows', () => {
  it('keeps formula fields unknown until the AST is loaded', () => {
    const rows = buildDiscoveryCatalogRows(center([searchRun([candidate()])]), {})
    expect(rows).toHaveLength(1)
    expect(rows[0]?.formula).toBeNull()
    expect(rows[0]?.complexity).toBeNull()
    expect(rows[0]?.researchName).toBe('sin 週期研究')
    expect(rows[0]?.versionId).toBe('version-1')
  })

  it('renders formula, complexity, arity and domain from the loaded AST', () => {
    const equations = {
      'equation-1': equation('equation-1', {
        op: 'add',
        args: [
          { op: 'var', name: 'x0' },
          { op: 'param', name: 'c0' },
        ],
      }),
    }
    const rows = buildDiscoveryCatalogRows(center([searchRun([candidate()])]), equations)
    expect(rows[0]?.formula).toBe('(x0 + c0)')
    expect(rows[0]?.complexity).toBe(3)
    expect(rows[0]?.variableCount).toBe(1)
    expect(rows[0]?.parameterCount).toBe(1)
    expect(rows[0]?.domain).toBe('x0 ∈ [0, 1]')
  })
})

describe('sortDiscoveryCatalogRows', () => {
  function row(overrides: Partial<DiscoveryCatalogRow>): DiscoveryCatalogRow {
    return {
      candidateId: 'candidate-x',
      equationVersionId: 'equation-x',
      source: 'POLYNOMIAL',
      developmentRank: 1,
      validationStatus: 'NOT_RUN',
      runId: 'run-1',
      researchId: 'research-1',
      researchName: '研究',
      versionId: 'version-1',
      createdAt: '2026-10-26T03:00:00Z',
      formula: null,
      complexity: null,
      variableCount: null,
      parameterCount: null,
      domain: null,
      fitRunCount: 0,
      validationRunCount: 0,
      ...overrides,
    }
  }

  it('pushes rows without a development rank to the end', () => {
    const rows = [row({ candidateId: 'a', developmentRank: null }), row({ candidateId: 'b', developmentRank: 2 })]
    expect(sortDiscoveryCatalogRows(rows, 'RANK_ASC').map((entry) => entry.candidateId)).toEqual(['b', 'a'])
    expect(sortDiscoveryCatalogRows(rows, 'RANK_DESC').map((entry) => entry.candidateId)).toEqual(['a', 'b'])
  })

  it('sorts by complexity and keeps unknown complexity last', () => {
    const rows = [
      row({ candidateId: 'a', complexity: 9 }),
      row({ candidateId: 'b', complexity: null }),
      row({ candidateId: 'c', complexity: 2 }),
    ]
    expect(sortDiscoveryCatalogRows(rows, 'COMPLEXITY_ASC').map((entry) => entry.candidateId)).toEqual(['c', 'a', 'b'])
    expect(sortDiscoveryCatalogRows(rows, 'COMPLEXITY_DESC').map((entry) => entry.candidateId)).toEqual(['a', 'c', 'b'])
  })

  it('sorts finished validation first when requested', () => {
    const rows = [
      row({ candidateId: 'a', validationStatus: 'NOT_RUN' }),
      row({ candidateId: 'b', validationStatus: 'FINISHED' }),
      row({ candidateId: 'c', validationStatus: 'INVALID' }),
    ]
    expect(sortDiscoveryCatalogRows(rows, 'STATUS').map((entry) => entry.candidateId)).toEqual(['b', 'a', 'c'])
  })
})

describe('filterDiscoveryCatalogRows', () => {
  it('matches keyword against formula, source and research name', () => {
    const rows = buildDiscoveryCatalogRows(center([searchRun([candidate()])]), {
      'equation-1': equation('equation-1', { op: 'var', name: 'x0' }),
    })
    expect(filterDiscoveryCatalogRows(rows, 'sin 週期', 'ALL')).toHaveLength(1)
    expect(filterDiscoveryCatalogRows(rows, 'polynomial', 'ALL')).toHaveLength(1)
    expect(filterDiscoveryCatalogRows(rows, 'x0', 'ALL')).toHaveLength(1)
    expect(filterDiscoveryCatalogRows(rows, '找不到', 'ALL')).toHaveLength(0)
    expect(filterDiscoveryCatalogRows(rows, '', 'FINISHED')).toHaveLength(0)
  })
})

describe('summarizeDiscoveryStatus', () => {
  it('counts every validation status bucket', () => {
    const rows = buildDiscoveryCatalogRows(
      center([
        searchRun([
          candidate({ id: 'a', validation_status: 'FINISHED' }),
          candidate({ id: 'b', validation_status: 'PENDING' }),
          candidate({ id: 'c', validation_status: 'INVALID' }),
        ]),
      ]),
      {},
    )
    expect(summarizeDiscoveryStatus(rows)).toEqual({ NOT_RUN: 0, PENDING: 1, FINISHED: 1, INVALID: 1 })
  })
})

describe('buildDiscoveryCatalogCsv', () => {
  it('writes 未取得 for unloaded columns and quotes text cells', () => {
    const rows = buildDiscoveryCatalogRows(center([searchRun([candidate()])]), {})
    const csv = buildDiscoveryCatalogCsv(rows)
    const lines = csv.trimEnd().split('\r\n')
    expect(lines).toHaveLength(2)
    expect(lines[0]).toContain('candidate_id')
    expect(lines[1]).toContain(`,${DISCOVERY_UNKNOWN},`)
    expect(lines[1]).toContain('"candidate-1"')
  })
})

describe('buildComparisonContextRows', () => {
  it('returns nothing when the version is not loaded', () => {
    expect(buildComparisonContextRows(null)).toEqual([])
    expect(buildFairComparisonRows(null)).toEqual([])
  })

  it('reports the split that both candidates were compared on', () => {
    const rows = buildComparisonContextRows(version())
    const byLabel = new Map(rows.map((fact) => [fact.label, fact.value]))
    expect(byLabel.get('資料集版本')).toBe(DATASET_VERSION_ID)
    expect(byLabel.get('切分方式')).toBe('EXPLICIT')
    expect(byLabel.get('fit 列數')).toBe('2')
    expect(byLabel.get('development 列數')).toBe('1')
    expect(byLabel.get('final_test 列數')).toBe('2')
    expect(byLabel.get('封存 final_test')).toBe('已封存')
  })
})

describe('buildFairComparisonRows', () => {
  it('renders the evaluation policy without inventing defaults', () => {
    const rows = buildFairComparisonRows(version())
    const byLabel = new Map(rows.map((fact) => [fact.label, fact.value]))
    expect(byLabel.get('比較方法')).toBe('配對重抽樣（IID）（IID_PAIRED_BOOTSTRAP）')
    expect(byLabel.get('誤差模型')).toBe('絕對誤差界（ABSOLUTE_BOUND）')
    expect(byLabel.get('絕對誤差上界')).toBe('0.01')
    expect(byLabel.get('區塊長度')).toBe('未使用')
    expect(byLabel.get('實務尺度覆寫')).toBe(DISCOVERY_UNKNOWN)
    expect(byLabel.get('基準')).toBe('擬合平均基準（FIT_MEAN）')
  })
})
