import { describe, expect, it } from 'vitest'
import type { CandidatePage, EquationVersion, FitRun } from '../src/api/candidates'
import type { ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../src/api/research'
import type { Run } from '../src/api/runs'
import { loadCandidateDetails, loadDiscoveriesCenter } from '../src/lib/discoveries'

function version(status: ResearchVersion['status'] = 'READY'): ResearchVersion {
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
    status,
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
  }
}

function run(): Run {
  return {
    kind: 'Run',
    id: 'run-1',
    type: 'SEARCH',
    status: 'RUNNING',
    revision: 1,
    created_at: '2026-10-26T02:00:00Z',
    dataset_id: null,
    research_version_id: 'version-1',
    current_event_cursor: 'RUN:run-1:0',
  }
}

const candidatePage: CandidatePage = {
  items: [
    {
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
    },
  ],
  next_cursor: null,
}

describe('loadDiscoveriesCenter', () => {
  it('builds recent search run summaries with candidate counts', async () => {
    const center = await loadDiscoveriesCenter({
      listResearches: async () =>
        ({
          items: [{ kind: 'Research', id: 'research-1', tenant_id: 'tenant-1', schema_version: '2.0', created_at: '2026-10-26T00:00:00Z', name: 'sin', owner_id: 'owner-1' }],
          next_cursor: null,
        }) satisfies ResearchPage,
      listResearchVersions: async () => ({ items: [version()], next_cursor: null } satisfies ResearchVersionPage),
      listResearchVersionRuns: async () => ({ items: [run()], next_cursor: null } satisfies RunPage),
      listRunCandidates: async () => candidatePage,
      getEquationVersion: async () => ({ kind: 'EquationVersion', id: 'equation-1', tenant_id: 'tenant-1', schema_version: '2.0', created_at: '2026-10-26T00:00:00Z', dsl: { dsl_version: '1', variables: [], parameters: [], domain: [], root: { op: 'const', value: { numerator: '1', denominator: '1' } } }, identity_hash: 'a'.repeat(64) } satisfies EquationVersion),
      getFitRun: async () => ({ kind: 'FitRun', id: 'fit-1', tenant_id: 'tenant-1', schema_version: '2.0', created_at: '2026-10-26T00:00:00Z', run_id: 'run-1', equation_version_id: 'equation-1', dataset_version_id: 'dataset-version-1', parameters: { c0: '1' }, optimizer: 'OPT', observation_split_id: 'split-1', split_role: 'FIT', precision_bits: 53, fit_row_ids: [1], fit_rows_hash: 'b'.repeat(64), representation_artifact_id: 'artifact-1' } satisfies FitRun),
    })

    expect(center.searchRuns).toHaveLength(1)
    expect(center.metrics.find((row) => row.label === '已載入候選')?.value).toBe('1')
    expect(center.searchRuns[0]?.candidates[0]?.id).toBe('candidate-1')
  })
})

describe('loadCandidateDetails', () => {
  it('loads only missing equations and fits', async () => {
    const details = await loadCandidateDetails(
      {
        listResearches: async () => ({ items: [], next_cursor: null }),
        listResearchVersions: async () => ({ items: [], next_cursor: null }),
        listResearchVersionRuns: async () => ({ items: [], next_cursor: null }),
        listRunCandidates: async () => ({ items: [], next_cursor: null }),
        getEquationVersion: async () => ({ kind: 'EquationVersion', id: 'equation-1', tenant_id: 'tenant-1', schema_version: '2.0', created_at: '2026-10-26T00:00:00Z', dsl: { dsl_version: '1', variables: [], parameters: [], domain: [], root: { op: 'const', value: { numerator: '1', denominator: '1' } } }, identity_hash: 'a'.repeat(64) }),
        getFitRun: async () => ({ kind: 'FitRun', id: 'fit-1', tenant_id: 'tenant-1', schema_version: '2.0', created_at: '2026-10-26T00:00:00Z', run_id: 'run-1', equation_version_id: 'equation-1', dataset_version_id: 'dataset-version-1', parameters: { c0: '1' }, optimizer: 'OPT', observation_split_id: 'split-1', split_role: 'FIT', precision_bits: 53, fit_row_ids: [1], fit_rows_hash: 'b'.repeat(64), representation_artifact_id: 'artifact-1' }),
      },
      candidatePage.items,
      { equations: {}, fits: {} },
    )

    expect(Object.keys(details.equations)).toEqual(['equation-1'])
    expect(Object.keys(details.fits)).toEqual(['fit-1'])
  })
})
