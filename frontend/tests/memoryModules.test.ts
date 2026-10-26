import { describe, expect, it } from 'vitest'
import type { Research, ResearchVersion } from '../src/api/research'
import type { Run } from '../src/api/runs'
import type { ValidationRun } from '../src/lib/evaluation'
import type { FinalEvaluation } from '../src/lib/finalEvaluation'
import {
  MEMORY_UNKNOWN,
  buildEvolutionGraph,
  buildEvolutionTimeline,
  buildExperienceTimeline,
  buildFailureRows,
  buildKnowledgeRows,
  buildRecoveryRows,
  loadMemoryCenter,
  runVerdict,
  summarizeEvolution,
  summarizeExperience,
  summarizeFailures,
  summarizeKnowledgeRows,
  type MemoryCenter,
  type MemoryDeps,
} from '../src/lib/memoryCenter'

const RESEARCH_ID = 'research-1'
const VERSION_ID = 'version-1'
const SUBMISSION_ID = '11111111-1111-1111-1111-111111111111'
const VALIDATION_FALSIFIED = '22222222-2222-2222-2222-222222222222'
const VALIDATION_SUPPORTED = '33333333-3333-3333-3333-333333333333'

const research: Research = {
  kind: 'Research',
  id: RESEARCH_ID,
  tenant_id: 'tenant-1',
  schema_version: '2.0',
  created_at: '2026-10-26T00:00:00Z',
  name: 'sin 週期研究',
  owner_id: 'owner-1',
}

function version(): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id: VERSION_ID,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T01:00:00Z',
    research_id: RESEARCH_ID,
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
    revision: 3,
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
    frozen_submission_ids: [SUBMISSION_ID],
    evidence_bundle_ids: ['bundle-1', 'bundle-2'],
    quality_report_id: 'artifact-quality',
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

function run(id: string, patch: Partial<Run> & Pick<Run, 'type' | 'status'>): Run {
  return {
    kind: 'Run',
    id,
    revision: 1,
    created_at: '2026-10-26T02:00:00Z',
    dataset_id: null,
    research_version_id: VERSION_ID,
    current_event_cursor: `RUN:${id}:0`,
    ...patch,
  }
}

const searchRun = run('run-search', { type: 'SEARCH', status: 'SUCCEEDED', outcome_status: 'SUPPORTED', created_at: '2026-10-26T05:00:00Z' })
const failedRun = run('run-fit', { type: 'FIT', status: 'FAILED', stop_reason: 'NUMERICAL_FAILURE', phase: 'FITTING', created_at: '2026-10-26T04:00:00Z' })
const cancelledRun = run('run-profile', { type: 'PROFILE', status: 'CANCELLED', stop_reason: 'USER_CANCELLED', created_at: '2026-10-26T03:00:00Z' })

function validation(id: string, patch: Partial<ValidationRun>): ValidationRun {
  return {
    id,
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
    validCount: 9,
    failedCount: 1,
    sha256: 'c'.repeat(64),
    createdAt: '2026-10-26T03:30:00Z',
    ...patch,
  }
}

const falsified = validation(VALIDATION_FALSIFIED, {
  outcome: 'FALSIFIED',
  splitRole: 'FIT',
  failedCount: 3,
  metricReasons: { mae: 'NO_EVALUABLE_ROWS' },
})
const supported = validation(VALIDATION_SUPPORTED, { outcome: 'SUPPORTED' })

const finalEvaluation: FinalEvaluation = {
  submissionId: SUBMISSION_ID,
  metricVersion: '1',
  status: 'FAILED',
  slots: [
    { frozenCandidateId: '44444444-4444-4444-4444-444444444444', slotId: '55555555-5555-5555-5555-555555555555', runId: '66666666-6666-6666-6666-666666666666', validationRunId: VALIDATION_FALSIFIED, status: 'COMPLETED' },
    { frozenCandidateId: '77777777-7777-7777-7777-777777777777', slotId: '88888888-8888-8888-8888-888888888888', runId: '99999999-9999-9999-9999-999999999999', validationRunId: VALIDATION_SUPPORTED, status: 'COMPLETED' },
  ],
  exposure: { budget: 4, reserved: 2, consumed: 2, retired: 0 },
}

const deps: MemoryDeps = {
  listResearches: async () => ({ items: [research], next_cursor: null }),
  listResearchVersions: async () => ({ items: [version()], next_cursor: null }),
  listResearchVersionRuns: async () => ({ items: [searchRun, failedRun, cancelledRun], next_cursor: null }),
  getFinalEvaluation: async (submissionId) => (submissionId === SUBMISSION_ID ? finalEvaluation : null),
  getValidationRun: async (validationId) => {
    if (validationId === VALIDATION_FALSIFIED) return falsified
    if (validationId === VALIDATION_SUPPORTED) return supported
    return null
  },
  getEvidenceBundle: async (bundleId) => ({
    kind: 'EvidenceBundle',
    id: bundleId,
    research_version_id: VERSION_ID,
    status: bundleId === 'bundle-2' ? 'QUARANTINED' : 'ACTIVE',
    revision: 1,
    validation_ids: [VALIDATION_FALSIFIED],
    proof_artifact_ids: ['artifact-proof-1'],
  }),
  getQualityReport: async () => ({
    kind: 'QualityReport',
    quality: 'BLOCKED',
    readiness: 'BLOCKED',
    blocking_code: 'SEALED_TEST_NOT_REGISTERED',
    remaining: ['SEALED_TEST_NOT_REGISTERED'],
  }),
}

async function center(): Promise<MemoryCenter> {
  return await loadMemoryCenter(deps)
}

describe('記憶中心載入', () => {
  it('aggregates researches, versions, runs and submission snapshots', async () => {
    const built = await center()

    expect(built.researches.map((row) => row.id)).toEqual([RESEARCH_ID])
    expect(built.versions.map((row) => row.id)).toEqual([VERSION_ID])
    expect(built.runs.map((entry) => entry.run.id)).toEqual(['run-search', 'run-fit', 'run-profile'])
    expect(built.submissionRows).toHaveLength(1)
    expect(built.submissionRows[0]?.validations.map((row) => row.id)).toEqual([VALIDATION_FALSIFIED, VALIDATION_SUPPORTED])
    expect(built.scope).toEqual({ researchesRead: 1, versionsRead: 1, runsRead: 3, truncated: false })
  })

  it('marks evidence items unreadable when nothing can be parsed', async () => {
    const built = await loadMemoryCenter({
      ...deps,
      getEvidenceBundle: async () => ({}),
      getQualityReport: async () => ({}),
    })

    expect(built.evidenceItems[0]?.bundles).toEqual([])
    expect(built.evidenceItems[0]?.qualityReport).toBeNull()
    expect(built.evidenceItems[0]?.unreadable).toBe(true)
  })
})

describe('知識庫推導（SCREEN 27）', () => {
  it('counts verified conclusions from supported validations only', async () => {
    const rows = buildKnowledgeRows(await center())

    expect(rows).toHaveLength(1)
    expect(rows[0]?.verifiedConclusions).toBe(1)
    expect(rows[0]?.outcomes).toEqual({ SUPPORTED: 1, AMBIGUOUS: 0, INSUFFICIENT_EVIDENCE: 0, FALSIFIED: 1 })
    expect(rows[0]?.bundleStatus).toBe('ACTIVE')
    expect(rows[0]?.retrievalTags).toBe(MEMORY_UNKNOWN)
  })

  it('summarizes evidence-backed, quarantined and blocked versions', async () => {
    const rows = buildKnowledgeRows(await center())

    // 版本同時有 ACTIVE 與 QUARANTINED 證據包時，有效狀態視為 ACTIVE，不列為已隔離。
    expect(summarizeKnowledgeRows(rows)).toEqual({ conclusions: 1, evidenceBacked: 1, quarantined: 0, blockedQuality: 1 })
  })

  it('counts a version as quarantined only when every bundle is quarantined', async () => {
    const built = await loadMemoryCenter({
      ...deps,
      getEvidenceBundle: async (bundleId) => ({
        kind: 'EvidenceBundle',
        id: bundleId,
        research_version_id: VERSION_ID,
        status: 'QUARANTINED',
        revision: 1,
        validation_ids: [VALIDATION_FALSIFIED],
        proof_artifact_ids: [],
      }),
    })
    const rows = buildKnowledgeRows(built)

    expect(rows[0]?.bundleStatus).toBe('QUARANTINED')
    expect(summarizeKnowledgeRows(rows).quarantined).toBe(1)
  })

  it('returns an empty list when no version carries evidence', async () => {
    const built = await center()
    built.evidenceItems = []

    expect(buildKnowledgeRows(built)).toEqual([])
  })
})

describe('研究經驗推導（SCREEN 28）', () => {
  it('maps run status to a verdict', () => {
    expect(runVerdict('SUCCEEDED')).toBe('SUCCESS')
    expect(runVerdict('FAILED')).toBe('FAILURE')
    expect(runVerdict('CANCELLED')).toBe('ABORTED')
    expect(runVerdict('RUNNING')).toBe('ACTIVE')
  })

  it('builds a timeline with conditions from the evaluation policy hash', async () => {
    const entries = buildExperienceTimeline(await center())

    expect(entries.map((entry) => entry.verdict)).toEqual(['SUCCESS', 'FAILURE', 'ABORTED'])
    expect(entries[0]?.condition).toBe('b'.repeat(64))
    expect(entries[0]?.lesson).toBe(MEMORY_UNKNOWN)
    expect(summarizeExperience(entries)).toEqual({ SUCCESS: 1, FAILURE: 1, ABORTED: 1, ACTIVE: 0 })
  })
})

describe('失敗案例推導（SCREEN 29）', () => {
  it('classifies every failure source without inventing repairs', async () => {
    const rows = buildFailureRows(await center())

    expect(new Set(rows.map((row) => row.category))).toEqual(
      new Set(['RUN_FAILED', 'SUBMISSION_FAILED', 'FALSIFIED', 'QUALITY_BLOCKED', 'EVIDENCE_QUARANTINED']),
    )
    expect(rows.every((row) => row.repair === MEMORY_UNKNOWN)).toBe(true)
    expect(summarizeFailures(rows)).toEqual({
      RUN_FAILED: 1,
      SUBMISSION_FAILED: 1,
      FALSIFIED: 1,
      QUALITY_BLOCKED: 1,
      EVIDENCE_QUARANTINED: 1,
    })
  })

  it('keeps the falsified reason when the backend hides the stop reason', async () => {
    const built = await center()
    built.runs = built.runs.map((entry) =>
      entry.run.id === 'run-fit' ? { ...entry, run: { ...entry.run, stop_reason: undefined } } : entry,
    )
    const rows = buildFailureRows(built).filter((row) => row.category === 'RUN_FAILED')

    expect(rows[0]?.reason).toBe('後端未揭露停止理由')
  })
})

describe('假設恢復推導（SCREEN 30）', () => {
  it('only lists versions that actually failed', async () => {
    const built = await center()
    const failures = buildFailureRows(built)
    const rows = buildRecoveryRows(built, failures)

    expect(rows).toHaveLength(1)
    expect(rows[0]?.versionId).toBe(VERSION_ID)
    expect(rows[0]?.blockers.sort()).toEqual(
      ['EVIDENCE_QUARANTINED', 'FALSIFIED', 'QUALITY_BLOCKED', 'RUN_FAILED', 'SUBMISSION_FAILED'].sort(),
    )
    expect(rows[0]?.searchRunCount).toBe(1)
    expect(rows[0]?.condition).toBe(MEMORY_UNKNOWN)
  })

  it('returns nothing when there is no failure to recover from', async () => {
    const built = await center()

    expect(buildRecoveryRows(built, [])).toEqual([])
  })
})

describe('知識演化推導（SCREEN 31）', () => {
  it('builds graph nodes and edges only from actual references', async () => {
    const built = await center()
    const graph = buildEvolutionGraph(built)
    const ids = graph.nodes.map((node) => node.id)

    expect(ids).toContain(`research:${RESEARCH_ID}`)
    expect(ids).toContain(`version:${VERSION_ID}`)
    expect(ids).toContain(`submission:${SUBMISSION_ID}`)
    expect(ids).toContain('bundle:bundle-2')
    expect(graph.edges.some((edge) => edge.from === `version:${VERSION_ID}` && edge.to === `submission:${SUBMISSION_ID}`)).toBe(true)
    expect(graph.edges.every((edge) => ids.includes(edge.from) && ids.includes(edge.to))).toBe(true)
  })

  it('summarizes revisions, quarantined evidence and withdrawn versions', async () => {
    const built = await center()

    expect(summarizeEvolution(built)).toEqual({ versions: 1, revisions: 3, quarantinedEvidence: 1, withdrawn: 0 })
  })

  it('keeps the evolution timeline aligned with version status labels', async () => {
    const entries = buildEvolutionTimeline(await center())

    expect(entries).toHaveLength(1)
    expect(entries[0]?.versionStatus).toBe('READY')
    expect(entries[0]?.evidenceStatus).toBe('ACTIVE')
    expect(entries[0]?.quality).toBe('BLOCKED')
    expect(entries[0]?.submissionStatus).toBe('失敗')
  })
})
