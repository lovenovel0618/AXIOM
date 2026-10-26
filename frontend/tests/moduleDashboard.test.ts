import { describe, expect, it } from 'vitest'
import type { CandidatePage } from '../src/api/candidates'
import type { Dataset, DatasetPage, DatasetVersion, VersionPage } from '../src/api/datasets'
import type { Research, ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../src/api/research'
import type { Run } from '../src/api/runs'
import { loadModuleDashboard, type ModuleDashboardDeps } from '../src/lib/moduleDashboard'

function research(id: string, name: string, createdAt: string): Research {
  return {
    kind: 'Research',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: createdAt,
    name,
    owner_id: 'owner-1',
  }
}

function researchVersion(id: string, researchId: string, status: ResearchVersion['status'], createdAt: string): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: createdAt,
    research_id: researchId,
    dataset_version_id: 'dataset-version-1',
    semantic_profile: {
      inputs: [],
      target: {
        name: 'y',
        unit: [],
        source_column: 'y',
        conversion: { source_unit: '1', scale: '1', offset: '0' },
      },
      units_confirmed: true,
      time_ordered: false,
      measurement_resolution: null,
      resolution_reason: 'ok',
      group_column: null,
    },
    budget: {
      cpu_seconds: 1,
      gpu_seconds: 0,
      wall_seconds: 1,
      tokens: 0,
      candidate_limit: 10,
      memory_bytes: 2147483648,
    },
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

function run(id: string, type: Run['type'], status: Run['status'], versionId: string, createdAt: string): Run {
  return {
    kind: 'Run',
    id,
    type,
    status,
    revision: 1,
    created_at: createdAt,
    dataset_id: null,
    research_version_id: versionId,
    current_event_cursor: `RUN:${id}:0`,
  }
}

function dataset(id: string, name: string, createdAt: string): Dataset {
  return {
    kind: 'Dataset',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: createdAt,
    name,
    owner_id: 'owner-1',
  }
}

function datasetVersion(
  id: string,
  datasetId: string,
  status: DatasetVersion['status'],
  createdAt: string,
  previewId: string | null,
): DatasetVersion {
  return {
    kind: 'DatasetVersion',
    id,
    dataset_id: datasetId,
    created_at: createdAt,
    format: 'CSV',
    row_count: 128,
    sha256: 'c'.repeat(64),
    status,
    artifact_id: 'artifact-1',
    structure_preview_artifact_id: previewId,
  }
}

function deps(overrides: Partial<ModuleDashboardDeps> = {}): ModuleDashboardDeps {
  const researchRows = [research('research-1', 'sin-wave', '2026-10-26T01:00:00Z')]
  const versionRows = [researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')]
  const runRows = [run('run-1', 'SEARCH', 'RUNNING', 'version-1', '2026-10-26T03:00:00Z')]
  const datasetRows = [dataset('dataset-1', 'sin-dataset', '2026-10-25T01:00:00Z')]
  const datasetVersionRows = [datasetVersion('dataset-version-1', 'dataset-1', 'AVAILABLE', '2026-10-25T03:00:00Z', 'preview-1')]
  const candidateRows: CandidatePage = {
    items: [
      {
        kind: 'Candidate',
        id: 'candidate-1',
        tenant_id: 'tenant-1',
        schema_version: '2.0',
        created_at: '2026-10-26T04:00:00Z',
        search_run_id: 'run-1',
        equation_version_id: 'equation-1',
        source: 'POLYNOMIAL',
        development_rank: 1,
        validation_status: 'NOT_RUN',
        fit_run_ids: [],
        validation_run_ids: [],
      },
    ],
    next_cursor: null,
  }

  return {
    checkReadiness: async () => 'ready',
    listResearches: async (_limit) => ({ items: researchRows, next_cursor: null } satisfies ResearchPage),
    listResearchVersions: async (_researchId, _limit) => ({ items: versionRows, next_cursor: null } satisfies ResearchVersionPage),
    listResearchVersionRuns: async (_versionId, _limit) => ({ items: runRows, next_cursor: null } satisfies RunPage),
    listDatasets: async (_limit) => ({ items: datasetRows, next_cursor: null } satisfies DatasetPage),
    listVersions: async (_datasetId, _limit) => ({ items: datasetVersionRows, next_cursor: null } satisfies VersionPage),
    listRunCandidates: async (_runId, _limit) => candidateRows,
    ...overrides,
  }
}

describe('loadModuleDashboard', () => {
  it('builds overview metrics from real research and dataset signals', async () => {
    const dashboard = await loadModuleDashboard('overview', deps())

    expect(dashboard.metrics.map((row) => row.label)).toContain('可分析資料集')
    expect(dashboard.metrics.find((row) => row.label === '可分析資料集')?.value).toBe('1')
    expect(dashboard.lists[0]?.items[0]?.title).toBe('sin-wave')
    expect(dashboard.lists[1]?.items[0]?.badge).toContain('AVAILABLE')
  })

  it('builds discoveries from recent search runs and candidate pages', async () => {
    const frozenVersion = researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')
    frozenVersion.frozen_submission_ids = ['submission-1']
    frozenVersion.evidence_bundle_ids = ['bundle-1']

    const dashboard = await loadModuleDashboard(
      'discoveries',
      deps({
        listResearchVersions: async (_researchId, _limit) => ({
          items: [frozenVersion],
          next_cursor: null,
        }),
      }),
    )

    expect(dashboard.metrics.find((row) => row.label === '最近候選')?.value).toBe('1')
    expect(dashboard.metrics.find((row) => row.label === '已凍結版本')?.value).toBe('1')
    expect(dashboard.lists[1]?.items[0]?.title).toContain('候選 #1')
  })

  it('marks settings readiness as bad when health endpoint is unavailable', async () => {
    const dashboard = await loadModuleDashboard(
      'settings',
      deps({
        checkReadiness: async () => 'unavailable',
      }),
    )

    expect(dashboard.metrics[0]?.label).toBe('服務狀態')
    expect(dashboard.metrics[0]?.tone).toBe('bad')
    expect(dashboard.metrics[0]?.value).toBe('異常')
  })
})
