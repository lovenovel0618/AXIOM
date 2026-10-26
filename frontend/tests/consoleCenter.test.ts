import { describe, expect, it } from 'vitest'
import type {
  Dataset,
  DatasetPage,
  DatasetRunPage,
  DatasetVersion,
  RunRecord,
  VersionPage,
} from '../src/api/datasets'
import type { Research, ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../src/api/research'
import type { BudgetUsage, Run } from '../src/api/runs'
import type { HealthStatus } from '../src/health'
import {
  activeRunCount,
  activeVersionCount,
  buildActivityAnalysis,
  buildActivityTimeline,
  buildConsoleSnapshot,
  buildPendingQueue,
  buildResourceSummary,
  latestDatasetVersionOf,
  UNKNOWN,
  type ConsoleDeps,
} from '../src/lib/consoleCenter'

const ZERO_USAGE: BudgetUsage = {
  cpu_seconds: 0,
  gpu_seconds: 0,
  tokens: 0,
  peak_memory_bytes: 0,
  elapsed_wall_seconds: 0,
  candidates_generated: 0,
  candidates_accepted: 0,
}

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

function researchVersion(
  id: string,
  researchId: string,
  status: ResearchVersion['status'],
  createdAt: string,
  usage: Partial<BudgetUsage> = {},
): ResearchVersion {
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
      cpu_seconds: 600,
      gpu_seconds: 0,
      wall_seconds: 300,
      tokens: 2000,
      candidate_limit: 40,
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
    research_budget_usage: { ...ZERO_USAGE, ...usage },
    structure_assessment_artifact_id: null,
  }
}

interface RunOptions {
  researchVersionId?: string | null
  datasetId?: string | null
  stopReason?: Run['stop_reason']
  outcomeStatus?: Run['outcome_status']
  budgetUsage?: BudgetUsage
}

function run(
  id: string,
  type: Run['type'],
  status: Run['status'],
  createdAt: string,
  options: RunOptions = {},
): Run {
  return {
    kind: 'Run',
    id,
    type,
    status,
    revision: 1,
    created_at: createdAt,
    dataset_id: options.datasetId ?? null,
    research_version_id: options.researchVersionId ?? null,
    current_event_cursor: `RUN:${id}:0`,
    stop_reason: options.stopReason ?? null,
    outcome_status: options.outcomeStatus ?? null,
    ...(options.budgetUsage === undefined ? {} : { budget_usage: options.budgetUsage }),
  }
}

function runRecord(id: string, type: string, status: string, datasetId: string, createdAt: string): RunRecord {
  return { kind: 'Run', id, type, status, dataset_id: datasetId, created_at: createdAt }
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
): DatasetVersion {
  return {
    kind: 'DatasetVersion',
    id,
    dataset_id: datasetId,
    created_at: createdAt,
    format: 'CSV',
    row_count: 5000,
    sha256: 'c'.repeat(64),
    status,
    artifact_id: 'artifact-1',
    structure_preview_artifact_id: null,
  }
}

interface DepsOptions {
  readiness?: HealthStatus
  readinessFails?: boolean
  researches?: Research[]
  researchVersions?: ResearchVersion[]
  researchRuns?: Run[]
  researchVersionsFails?: boolean
  researchRunsFail?: boolean
  datasets?: Dataset[]
  datasetVersions?: DatasetVersion[]
  datasetRuns?: RunRecord[]
  datasetsFails?: boolean
}

function deps(options: DepsOptions = {}): ConsoleDeps {
  const researchRows = options.researches ?? [research('research-1', 'sin-wave', '2026-10-26T01:00:00Z')]
  const versionRows = options.researchVersions ?? []
  const runRows = options.researchRuns ?? []
  const datasetRows = options.datasets ?? []
  const datasetVersionRows = options.datasetVersions ?? []
  const datasetRunRows = options.datasetRuns ?? []

  return {
    checkReadiness: () =>
      options.readinessFails === true
        ? Promise.reject(new Error('down'))
        : Promise.resolve(options.readiness ?? 'ready'),
    listResearches: () => Promise.resolve({ items: researchRows, next_cursor: null } satisfies ResearchPage),
    listResearchVersions: (researchId) => {
      if (options.researchVersionsFails === true) return Promise.reject(new Error('boom'))
      return Promise.resolve({
        items: versionRows.filter((version) => version.research_id === researchId),
        next_cursor: null,
      } satisfies ResearchVersionPage)
    },
    listResearchVersionRuns: (versionId) => {
      if (options.researchRunsFail === true) return Promise.reject(new Error('boom'))
      return Promise.resolve({
        items: runRows.filter((entry) => entry.research_version_id === versionId),
        next_cursor: null,
      } satisfies RunPage)
    },
    listDatasets: () => {
      if (options.datasetsFails === true) return Promise.reject(new Error('boom'))
      return Promise.resolve({ items: datasetRows, next_cursor: null } satisfies DatasetPage)
    },
    listVersions: (datasetId) =>
      Promise.resolve({
        items: datasetVersionRows.filter((version) => version.dataset_id === datasetId),
        next_cursor: null,
      } satisfies VersionPage),
    listDatasetRuns: (datasetId) =>
      Promise.resolve({
        items: datasetRunRows.filter((entry) => entry.dataset_id === datasetId),
        next_cursor: null,
      } satisfies DatasetRunPage),
  }
}

describe('buildConsoleSnapshot', () => {
  it('未取得的研究或資料集一律以空集合代替，不讓單一失敗中斷整頁', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({ readinessFails: true, researchVersionsFails: true, datasetsFails: true }),
    )

    expect(snapshot.readiness).toBe('unavailable')
    expect(snapshot.researches).toHaveLength(1)
    expect(snapshot.researchVersions).toEqual([])
    expect(snapshot.researchRuns).toEqual([])
    expect(snapshot.datasets).toEqual([])
    expect(snapshot.datasetRuns).toEqual([])
  })

  it('資料集匯入任務沒有預算欄位，投影一律留 null 而不是補 0', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        datasets: [dataset('dataset-1', 'sin-dataset', '2026-10-25T01:00:00Z')],
        datasetRuns: [
          runRecord('run-ingest', 'INGEST', 'FAILED', 'dataset-1', '2026-10-25T02:00:00Z'),
        ],
      }),
    )

    expect(snapshot.datasetRuns).toHaveLength(1)
    expect(snapshot.datasetRuns[0]?.budgetUsage).toBeNull()
    expect(snapshot.datasetRuns[0]?.stopReason).toBeNull()
    expect(snapshot.datasetRuns[0]?.researchId).toBeNull()
  })
})

describe('活動推導', () => {
  it('時間軸與分析只統計實際讀到的任務', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researchVersions: [researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')],
        researchRuns: [
          run('run-search', 'SEARCH', 'RUNNING', '2026-10-26T03:00:00Z', { researchVersionId: 'version-1' }),
          run('run-profile', 'PROFILE', 'SUCCEEDED', '2026-10-26T02:30:00Z', { researchVersionId: 'version-1' }),
        ],
      }),
    )

    const timeline = buildActivityTimeline(snapshot, 20)
    expect(timeline.map((entry) => entry.badge)).toEqual(['run-search', 'run-profile'])
    expect(timeline[0]?.detail).toContain('研究版本 version-1')

    const analysis = buildActivityAnalysis(snapshot)
    expect(analysis.total).toBe(2)
    expect(analysis.active).toBe(1)
    expect(analysis.byType.map((bucket) => bucket.key)).toEqual(['PROFILE', 'SEARCH'])
    expect(analysis.byStatus.find((bucket) => bucket.key === 'RUNNING')?.count).toBe(1)
    expect(activeRunCount(snapshot)).toBe(1)
    expect(activeVersionCount(snapshot)).toBe(1)
  })
})

describe('buildPendingQueue', () => {
  it('失敗任務以高優先列出並附上後端提供的停止理由', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researchVersions: [researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')],
        researchRuns: [
          run('run-1', 'SEARCH', 'FAILED', '2026-10-26T03:00:00Z', {
            researchVersionId: 'version-1',
            stopReason: 'NUMERICAL_FAILURE',
          }),
          run('run-2', 'SEARCH', 'SUCCEEDED', '2026-10-26T03:10:00Z', { researchVersionId: 'version-1' }),
        ],
      }),
    )

    const queue = buildPendingQueue(snapshot)
    const failed = queue.find((item) => item.id === 'run-1:failed')
    expect(failed?.priority).toBe('高')
    expect(failed?.reason).toContain('數值失敗')
    expect(failed?.to).toEqual({ name: 'run', params: { id: 'run-1' } })
    expect(queue.some((item) => item.id === 'run-2:failed')).toBe(false)
  })

  it('後端未揭露 stop_reason 時回報未取得，不自行推測原因', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researchVersions: [researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')],
        researchRuns: [
          run('run-1', 'SEARCH', 'FAILED', '2026-10-26T03:00:00Z', { researchVersionId: 'version-1' }),
          run('run-2', 'SEARCH', 'SUCCEEDED', '2026-10-26T03:10:00Z', { researchVersionId: 'version-1' }),
        ],
      }),
    )

    const failed = buildPendingQueue(snapshot).find((item) => item.id === 'run-1:failed')
    expect(failed?.reason).toContain(UNKNOWN)
  })

  it('歧義與拒答的結果不被當成成功，列入中優先待決策', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researchVersions: [researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')],
        researchRuns: [
          run('run-1', 'SEARCH', 'SUCCEEDED', '2026-10-26T03:00:00Z', {
            researchVersionId: 'version-1',
            outcomeStatus: 'INSUFFICIENT_EVIDENCE',
          }),
          run('run-2', 'SEARCH', 'SUCCEEDED', '2026-10-26T03:10:00Z', { researchVersionId: 'version-1' }),
        ],
      }),
    )

    const item = buildPendingQueue(snapshot).find((entry) => entry.id === 'run-1:outcome')
    expect(item?.priority).toBe('中')
    expect(item?.title).toContain('證據不足')
  })

  it('資料集尚無版本或最新版本不可用時列入待辦', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researches: [],
        datasets: [
          dataset('dataset-empty', 'empty', '2026-10-25T01:00:00Z'),
          dataset('dataset-1', 'sin-dataset', '2026-10-25T01:00:00Z'),
        ],
        datasetVersions: [datasetVersion('dataset-version-1', 'dataset-1', 'UNAVAILABLE', '2026-10-25T03:00:00Z')],
      }),
    )

    const queue = buildPendingQueue(snapshot)
    expect(queue.find((item) => item.id === 'dataset-empty:noversion')?.priority).toBe('低')
    expect(queue.find((item) => item.id === 'dataset-1:unavailable')?.priority).toBe('中')
  })

  it('排序為高、中、低且維持同優先級內的原始順序', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researchVersions: [researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')],
        researchRuns: [
          run('run-1', 'SEARCH', 'FAILED', '2026-10-26T03:00:00Z', {
            researchVersionId: 'version-1',
            stopReason: 'BUDGET_EXHAUSTED',
          }),
        ],
        datasets: [dataset('dataset-empty', 'empty', '2026-10-25T01:00:00Z')],
      }),
    )

    const priorities = buildPendingQueue(snapshot).map((item) => item.priority)
    expect(priorities).toEqual(['高', '中', '低'])
  })
})

describe('buildResourceSummary', () => {
  it('即時硬體使用率固定回報未取得，不以推測填補', async () => {
    const snapshot = await buildConsoleSnapshot(deps())
    const summary = buildResourceSummary(snapshot)

    expect(summary.instantaneous.map((cell) => cell.value)).toEqual([UNKNOWN, UNKNOWN, UNKNOWN])
    expect(summary.note).toContain('沒有即時')
  })

  it('沒有任務揭露用量時總和為 null 而非 0', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researchVersions: [researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z')],
        researchRuns: [
          run('run-1', 'SEARCH', 'RUNNING', '2026-10-26T03:00:00Z', { researchVersionId: 'version-1' }),
        ],
      }),
    )
    const summary = buildResourceSummary(snapshot)

    expect(summary.rows).toEqual([])
    expect(summary.totals.disclosing).toBe(0)
    expect(summary.totals.cpuSeconds).toBeNull()
    expect(summary.totals.tokens).toBeNull()
    expect(summary.totals.peakMemoryBytes).toBeNull()
  })

  it('只加總已揭露的用量，並帶出研究版本預算帳本', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researchVersions: [
          researchVersion('version-1', 'research-1', 'READY', '2026-10-26T02:00:00Z', {
            cpu_seconds: 120,
            tokens: 900,
            elapsed_wall_seconds: 60,
            peak_memory_bytes: 1024,
            candidates_generated: 12,
            candidates_accepted: 3,
          }),
        ],
        researchRuns: [
          run('run-1', 'SEARCH', 'SUCCEEDED', '2026-10-26T03:00:00Z', {
            researchVersionId: 'version-1',
            budgetUsage: { ...ZERO_USAGE, cpu_seconds: 10, tokens: 100, elapsed_wall_seconds: 5, peak_memory_bytes: 512 },
          }),
        ],
      }),
    )
    const summary = buildResourceSummary(snapshot)

    expect(summary.rows).toHaveLength(1)
    expect(summary.totals.cpuSeconds).toBe(10)
    expect(summary.totals.tokens).toBe(100)
    expect(summary.totals.peakMemoryBytes).toBe(512)
    expect(summary.totals.runs).toBe(1)

    const budget = summary.budgets[0]
    expect(budget?.cpuUsed).toBe(120)
    expect(budget?.cpuLimit).toBe(600)
    expect(budget?.wallUsed).toBe(60)
    expect(budget?.tokensLimit).toBe(2000)
    expect(budget?.candidatesUsed).toBe(12)
    expect(budget?.candidatesLimit).toBe(40)
  })
})

describe('latestDatasetVersionOf', () => {
  it('以 created_at 反序決定最新版本', async () => {
    const snapshot = await buildConsoleSnapshot(
      deps({
        researches: [],
        datasets: [dataset('dataset-1', 'sin-dataset', '2026-10-25T01:00:00Z')],
        datasetVersions: [
          datasetVersion('dataset-version-old', 'dataset-1', 'AVAILABLE', '2026-10-25T02:00:00Z'),
          datasetVersion('dataset-version-new', 'dataset-1', 'UNAVAILABLE', '2026-10-25T04:00:00Z'),
        ],
      }),
    )

    expect(latestDatasetVersionOf(snapshot, 'dataset-1')?.id).toBe('dataset-version-new')
    expect(latestDatasetVersionOf(snapshot, 'dataset-unknown')).toBeNull()
  })
})
