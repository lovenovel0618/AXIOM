import { describe, expect, it } from 'vitest'
import type { ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../src/api/research'
import type { Run } from '../src/api/runs'
import type { FinalEvaluation } from '../src/lib/finalEvaluation'
import type { ValidationRun } from '../src/lib/evaluation'
import { loadVerificationCenter } from '../src/lib/verificationCenter'

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
    evidence_bundle_ids: ['bundle-1'],
    quality_report_id: 'quality-1',
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

function run(status: Run['status'] = 'RUNNING'): Run {
  return {
    kind: 'Run',
    id: 'run-1',
    type: 'VALIDATE',
    status,
    revision: 1,
    created_at: '2026-10-26T02:00:00Z',
    dataset_id: null,
    research_version_id: 'version-1',
    current_event_cursor: 'RUN:run-1:0',
  }
}

const finalEvaluation: FinalEvaluation = {
  submissionId: 'submission-1',
  metricVersion: '1',
  status: 'EVALUATED',
  slots: [
    {
      frozenCandidateId: 'candidate-1',
      slotId: 'slot-1',
      runId: 'run-1',
      validationRunId: 'validation-1',
      status: 'COMPLETED',
    },
  ],
  exposure: {
    budget: 4,
    reserved: 0,
    consumed: 1,
    retired: 0,
  },
}

const validation: ValidationRun = {
  id: 'validation-1',
  outcome: 'SUPPORTED',
  metricVersion: '1',
  splitRole: 'FINAL_TEST',
  empiricalLevel: 'E2',
  proofLevel: 'P0',
  mae: 0.1,
  rmse: 0.2,
  metricReasons: {},
  validCoverage: 1,
  selectedCount: 1,
  validCount: 1,
  failedCount: 0,
  sha256: 'c'.repeat(64),
  createdAt: '2026-10-26T03:00:00Z',
}

describe('loadVerificationCenter', () => {
  it('builds evidence and submission rows from recent versions', async () => {
    const center = await loadVerificationCenter({
      listResearches: async () =>
        ({
          items: [{ kind: 'Research', id: 'research-1', tenant_id: 'tenant-1', schema_version: '2.0', created_at: '2026-10-26T00:00:00Z', name: 'sin', owner_id: 'owner-1' }],
          next_cursor: null,
        }) satisfies ResearchPage,
      listResearchVersions: async () => ({ items: [version()], next_cursor: null } satisfies ResearchVersionPage),
      listResearchVersionRuns: async () => ({ items: [run()], next_cursor: null } satisfies RunPage),
      getFinalEvaluation: async () => finalEvaluation,
      getValidationRun: async () => validation,
    })

    expect(center.metrics.find((row) => row.label === '已評估提交')?.value).toBe('1')
    expect(center.evidenceRows).toHaveLength(1)
    expect(center.submissionRows[0]?.validations[0]?.outcome).toBe('SUPPORTED')
  })
})
