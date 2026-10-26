import { describe, expect, it } from 'vitest'
import type { Artifact } from '../src/api/artifacts'
import type { Candidate, EquationVersion, FitRun } from '../src/api/candidates'
import type { Research, ResearchVersion } from '../src/api/research'
import type { Run } from '../src/api/runs'
import type { ValidationRun } from '../src/lib/evaluation'
import type { DiscoverySearchRun } from '../src/lib/discoveries'
import { buildEvidenceGraph, findEvidenceTrace } from '../src/lib/verificationGraph'
import { buildCounterexampleRows, summarizeFalsify } from '../src/lib/verificationFalsify'
import { buildProofRows, describeProofLevels, summarizeProof } from '../src/lib/verificationProof'
import { buildInverseDerivation, emptyInverseDerivation } from '../src/lib/verificationInverse'
import type { VerificationCenter } from '../src/lib/verificationCenter'

const research: Research = {
  kind: 'Research',
  id: 'research-1',
  tenant_id: 'tenant-1',
  schema_version: '2.0',
  created_at: '2026-10-26T00:00:00Z',
  name: 'sin',
  owner_id: 'owner-1',
}

function version(): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id: 'version-1',
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T01:00:00Z',
    research_id: 'research-1',
    dataset_version_id: 'dataset-version-1',
    semantic_profile: {
      inputs: [],
      target: { name: 'y', unit: [], source_column: 'y', conversion: { source_unit: '1', scale: '1', offset: '0' } },
      units_confirmed: true,
      time_ordered: false,
      measurement_resolution: null,
      resolution_reason: 'ok',
      group_column: null,
    },
    budget: { cpu_seconds: 1, gpu_seconds: 0, wall_seconds: 1, tokens: 0, candidate_limit: 1, memory_bytes: 2147483648 },
    purpose: 'DESCRIPTION',
    status: 'READY',
    revision: 1,
    observation_split: {
      id: 'split-1',
      kind: 'EXPLICIT',
      dataset_version_id: 'dataset-version-1',
      fit: [1],
      development: [2],
      final_test: [3],
      gap_rows: 0,
      lookback_rows: 0,
      horizon_rows: 0,
      seed: 0,
      time_column: null,
      group_column: null,
      group_assignment_digest: null,
      splitter_version: '1',
      policy_version: '1',
      sealed_final_test: true,
      row_ids_hash: 'a'.repeat(64),
      sealed_test_id: 'sealed-1',
    },
    current_event_cursor: 'RESEARCH:1:0',
    frozen_submission_ids: ['submission-1'],
    evidence_bundle_ids: ['bundle-1', 'bundle-2'],
    quality_report_id: null,
    refit_policy_artifact_id: null,
    domain: [],
    evaluation_policy: {
      policy_version: '1',
      metric_version: '1',
      error_model: 'UNSPECIFIED',
      absolute_error_bound: null,
      comparison_method: 'NONE',
      bootstrap_replicates: 100,
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

const artifact: Artifact = {
  kind: 'Artifact',
  id: 'artifact-1',
  tenant_id: 'tenant-1',
  created_at: '2026-10-26T04:00:00Z',
  artifact_uri: 's3://axiom/artifact-1',
  sha256: 'd'.repeat(64),
  status: 'AVAILABLE',
  owner_id: 'owner-1',
  size_bytes: 1024,
  media_type: 'application/json',
  access_class: 'PROJECT',
}

function validation(overrides: Partial<ValidationRun> & Pick<ValidationRun, 'id'>): ValidationRun {
  return {
    outcome: 'SUPPORTED',
    metricVersion: '1',
    splitRole: 'FINAL_TEST',
    empiricalLevel: 'E2',
    proofLevel: 'P0',
    mae: 0.1,
    rmse: 0.2,
    metricReasons: {},
    validCoverage: 1,
    selectedCount: 10,
    validCount: 10,
    failedCount: 0,
    sha256: 'c'.repeat(64),
    createdAt: '2026-10-26T03:00:00Z',
    ...overrides,
  }
}

const falsified = validation({ id: 'validation-1', outcome: 'FALSIFIED', splitRole: 'FIT', failedCount: 3, empiricalLevel: 'E1' })
const supported = validation({ id: 'validation-2', outcome: 'SUPPORTED', splitRole: 'FINAL_TEST', proofLevel: 'P1' })

function center(): VerificationCenter {
  const v = version()
  return {
    metrics: [],
    runs: [],
    evidenceRows: [{ research, version: v }],
    submissionRows: [
      {
        research,
        version: v,
        submissionId: 'submission-1',
        finalEvaluation: null,
        validations: [falsified, supported],
      },
    ],
    evidenceItems: [
      {
        research,
        version: v,
        bundles: [
          { id: 'bundle-1', researchVersionId: v.id, status: 'ACTIVE', revision: 1, validationIds: ['validation-1'], proofArtifactIds: ['artifact-1'] },
          {
            id: 'bundle-2',
            researchVersionId: v.id,
            status: 'ACTIVE',
            revision: 1,
            validationIds: ['validation-1', 'validation-2'],
            proofArtifactIds: ['artifact-1'],
          },
        ],
        qualityReport: null,
        unreadable: false,
      },
    ],
    proofArtifacts: { 'artifact-1': artifact },
  }
}

describe('反例搜尋推導', () => {
  it('only lists validations with failure evidence', () => {
    const rows = buildCounterexampleRows(center())

    expect(rows.map((row) => row.validationId)).toEqual(['validation-1'])
    expect(rows[0]?.researchId).toBe('research-1')
    expect(rows[0]?.reasons.some((reason) => reason.includes('3 列'))).toBe(true)
  })

  it('summarizes falsified and failed counts', () => {
    const summary = summarizeFalsify(buildCounterexampleRows(center()))

    expect(summary).toEqual({ falsified: 1, failed: 1, insufficient: 0, total: 1 })
  })

  it('returns an empty list when nothing is falsified', () => {
    const bare = center()
    bare.submissionRows[0]!.validations = [supported]

    expect(buildCounterexampleRows(bare)).toHaveLength(0)
  })
})

describe('形式化證明推導', () => {
  it('lists proof artifacts from evidence bundles', () => {
    const rows = buildProofRows(center())

    expect(rows).toHaveLength(2)
    expect(rows[0]?.artifactId).toBe('artifact-1')
    expect(describeProofLevels(rows[0]?.proofLevels ?? [])).toBe('P0、P1')
  })

  it('summarizes availability and unreadable artifacts', () => {
    expect(summarizeProof(buildProofRows(center()))).toEqual({ total: 2, available: 2, quarantined: 0, unreadable: 0 })

    const bare = center()
    bare.proofArtifacts = {}
    expect(summarizeProof(buildProofRows(bare)).unreadable).toBe(2)
  })

  it('returns an empty list when no bundle references artifacts', () => {
    const bare = center()
    bare.evidenceItems[0]!.bundles = []

    expect(buildProofRows(bare)).toHaveLength(0)
    expect(summarizeProof([])).toEqual({ total: 0, available: 0, quarantined: 0, unreadable: 0 })
  })
})

describe('證據關聯圖推導', () => {
  it('builds nodes and edges from actual references', () => {
    const graph = buildEvidenceGraph(center())

    expect(graph.independence.bundles).toBe(2)
    expect(graph.independence.independent).toBe(false)
    expect(graph.shared.map((item) => item.id).sort()).toEqual(['proof_artifact:artifact-1', 'validation:validation-1'])
    expect(graph.edges.some((edge) => edge.from === 'research:research-1' && edge.to === 'version:version-1')).toBe(true)
  })

  it('traces upstream and downstream for a node', () => {
    const graph = buildEvidenceGraph(center())
    const trace = findEvidenceTrace(graph, 'bundle:bundle-1')

    expect(trace).not.toBeNull()
    expect(trace?.upstream.map((node) => node.id)).toContain('version:version-1')
    expect(trace?.downstream.map((node) => node.id)).toContain('validation:validation-1')
  })

  it('returns null for an unknown node instead of guessing', () => {
    expect(findEvidenceTrace(buildEvidenceGraph(center()), 'validation:missing')).toBeNull()
  })

  it('never reports independence with a single bundle', () => {
    const bare = center()
    bare.evidenceItems[0]!.bundles = [bare.evidenceItems[0]!.bundles[0]!]
    const graph = buildEvidenceGraph(bare)

    expect(graph.independence.bundles).toBe(1)
    expect(graph.independence.independent).toBe(false)
  })
})

function equation(): EquationVersion {
  return {
    kind: 'EquationVersion',
    id: 'eq-1',
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T02:00:00Z',
    dsl: {
      dsl_version: '1',
      variables: [{ name: 'x', unit: [] }],
      parameters: [{ name: 'a', unit: [], lower: '0', upper: '10' }],
      domain: [],
      root: { op: 'param', name: 'a' },
    },
    identity_hash: 'e'.repeat(64),
  }
}

function fit(id: string, value: string): FitRun {
  return {
    kind: 'FitRun',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T02:00:00Z',
    run_id: 'run-1',
    equation_version_id: 'eq-1',
    dataset_version_id: 'dataset-version-1',
    parameters: { a: value },
    optimizer: 'lm',
    observation_split_id: 'split-1',
    split_role: 'FIT',
    precision_bits: 64,
    fit_row_ids: [1],
    fit_rows_hash: 'f'.repeat(64),
    representation_artifact_id: 'artifact-1',
  }
}

function searchEntry(): DiscoverySearchRun {
  const run: Run = {
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
  const candidate: Candidate = {
    kind: 'Candidate',
    id: 'candidate-1',
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T02:00:00Z',
    search_run_id: 'run-1',
    equation_version_id: 'eq-1',
    source: 'search',
    development_rank: 1,
    validation_status: 'FINISHED',
    fit_run_ids: ['fit-1', 'fit-2'],
    validation_run_ids: [],
  }
  return { run, research, version: version(), candidates: [candidate] }
}

describe('逆向推導推導', () => {
  it('flags parameters with differing fitted values as multi-valued', () => {
    const derivation = buildInverseDerivation(searchEntry(), { 'eq-1': equation() }, { 'fit-1': fit('fit-1', '1.0'), 'fit-2': fit('fit-2', '2.0') })

    expect(derivation.solutions).toHaveLength(1)
    expect(derivation.solutions[0]?.multiValuedParameters).toEqual(['a'])
    expect(derivation.solutions[0]?.parameters[0]?.distinct).toBe(2)
  })

  it('reports no multi-valued parameters when fits agree', () => {
    const derivation = buildInverseDerivation(searchEntry(), { 'eq-1': equation() }, { 'fit-1': fit('fit-1', '1.0'), 'fit-2': fit('fit-2', '1.0') })

    expect(derivation.solutions[0]?.multiValuedParameters).toEqual([])
  })

  it('keeps formula unknown when the equation is missing', () => {
    const derivation = buildInverseDerivation(searchEntry(), {}, {})

    expect(derivation.solutions[0]?.formula).toBeNull()
    expect(derivation.solutions[0]?.parameters).toEqual([])
  })

  it('returns an empty derivation without a selected run', () => {
    const derivation = emptyInverseDerivation(null)

    expect(derivation.runId).toBe('')
    expect(derivation.solutions).toEqual([])
  })
})
