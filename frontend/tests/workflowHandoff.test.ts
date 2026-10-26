import { describe, expect, it } from 'vitest'
import type { Candidate } from '../src/api/candidates'
import type { DiscoverySearchRun } from '../src/lib/discoveries'
import type { VerificationSubmissionRow } from '../src/lib/verificationCenter'
import { buildDiscoveriesHandoffSummary, buildVerificationHandoffSummary, groupVerificationRowsByVersion } from '../src/lib/workflowHandoff'

function candidate(id: string, rank: number | null, status: Candidate['validation_status']): Candidate {
  return {
    kind: 'Candidate',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: '2026-10-26T00:00:00Z',
    search_run_id: 'run-1',
    equation_version_id: `equation-${id}`,
    source: 'POLYNOMIAL',
    development_rank: rank,
    validation_status: status,
    fit_run_ids: [],
    validation_run_ids: [],
  }
}

function searchRun(): DiscoverySearchRun {
  return {
    run: {
      kind: 'Run',
      id: 'run-1',
      type: 'SEARCH',
      status: 'RUNNING',
      revision: 1,
      created_at: '2026-10-26T00:00:00Z',
      dataset_id: null,
      research_version_id: 'version-1',
      current_event_cursor: 'RUN:run-1:0',
    },
    research: {
      kind: 'Research',
      id: 'research-1',
      tenant_id: 'tenant-1',
      schema_version: '2.0',
      created_at: '2026-10-26T00:00:00Z',
      name: 'sin',
      owner_id: 'owner-1',
    },
    version: {
      kind: 'ResearchVersion',
      id: 'version-1',
      tenant_id: 'tenant-1',
      schema_version: '2.0',
      created_at: '2026-10-26T00:00:00Z',
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
      budget: { cpu_seconds: 1, gpu_seconds: 0, wall_seconds: 1, tokens: 0, candidate_limit: 4, memory_bytes: 2147483648 },
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
        sealed_test_id: null,
      },
      current_event_cursor: 'RESEARCH:1:0',
      frozen_submission_ids: [],
      evidence_bundle_ids: [],
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
    },
    candidates: [
      candidate('candidate-1', 1, 'NOT_RUN'),
      candidate('candidate-2', 2, 'PENDING'),
      candidate('candidate-3', 3, 'FINISHED'),
      candidate('candidate-4', 4, 'INVALID'),
      candidate('candidate-5', 5, 'NOT_RUN'),
    ],
  }
}

function submissionRow(versionId: string, submissionId: string, evaluated: boolean): VerificationSubmissionRow {
  return {
    research: {
      kind: 'Research',
      id: `research-${versionId}`,
      tenant_id: 'tenant-1',
      schema_version: '2.0',
      created_at: '2026-10-26T00:00:00Z',
      name: `research-${versionId}`,
      owner_id: 'owner-1',
    },
    version: {
      kind: 'ResearchVersion',
      id: versionId,
      tenant_id: 'tenant-1',
      schema_version: '2.0',
      created_at: '2026-10-26T00:00:00Z',
      research_id: `research-${versionId}`,
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
      budget: { cpu_seconds: 1, gpu_seconds: 0, wall_seconds: 1, tokens: 0, candidate_limit: 4, memory_bytes: 2147483648 },
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
      frozen_submission_ids: [submissionId],
      evidence_bundle_ids: [],
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
    },
    submissionId,
    finalEvaluation: evaluated
      ? {
          submissionId,
          metricVersion: '1',
          status: 'EVALUATED',
          slots: [],
          exposure: { budget: 4, reserved: 0, consumed: 1, retired: 0 },
        }
      : null,
    validations: [],
  }
}

describe('workflowHandoff', () => {
  it('builds discovery handoff summary from selected run and pins', () => {
    const summary = buildDiscoveriesHandoffSummary(searchRun(), ['candidate-2', 'missing', 'candidate-3'])
    expect(summary?.totalCandidates).toBe(5)
    expect(summary?.pinnedIds).toEqual(['candidate-2', 'candidate-3'])
    expect(summary?.suggestedPinnedIds).toEqual(['candidate-1', 'candidate-2', 'candidate-3', 'candidate-4'])
    expect(summary?.focusIds).toEqual(['candidate-2', 'candidate-3'])
    expect(summary?.statusCounts.FINISHED).toBe(1)
    expect(summary?.availableSlots).toBe(2)
  })

  it('falls back to all candidates when nothing is pinned', () => {
    const summary = buildDiscoveriesHandoffSummary(searchRun(), [])
    expect(summary?.focusIds).toEqual(['candidate-1', 'candidate-2', 'candidate-3', 'candidate-4', 'candidate-5'])
  })

  it('groups verification submissions by research version', () => {
    const groups = groupVerificationRowsByVersion(
      [
        submissionRow('version-1', 'submission-1', true),
        submissionRow('version-1', 'submission-2', false),
        submissionRow('version-2', 'submission-3', true),
      ],
      'submission-2',
    )
    expect(groups).toHaveLength(2)
    expect(groups[0]?.versionId).toBe('version-1')
    expect(groups[0]?.submissionIds).toEqual(['submission-1', 'submission-2'])
    expect(groups[0]?.selectedSubmissionId).toBe('submission-2')
  })

  it('builds verification handoff summary with visible and hidden counts', () => {
    const summary = buildVerificationHandoffSummary(
      [
        submissionRow('version-1', 'submission-1', true),
        submissionRow('version-1', 'submission-2', false),
        submissionRow('version-2', 'submission-3', true),
      ],
      ['submission-2', 'submission-3'],
      'submission-3',
    )
    expect(summary.visibleSubmissions).toBe(2)
    expect(summary.hiddenSubmissions).toBe(1)
    expect(summary.selectedSubmissionId).toBe('submission-3')
    expect(summary.groups.map((group) => group.versionId)).toEqual(['version-1', 'version-2'])
  })
})
