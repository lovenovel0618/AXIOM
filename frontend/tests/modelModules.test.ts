import { describe, expect, it } from 'vitest'
import type { BudgetUsage, Run, RunType } from '../src/api/runs'
import type {
  EvaluationPolicy,
  ObservationSplit,
  Research,
  ResearchPage,
  ResearchVersion,
  ResearchVersionPage,
  ResearchVersionStatus,
  RunPage,
  SemanticProfile,
} from '../src/api/research'
import {
  MODEL_UNKNOWN,
  RECENT_RUNS_READ,
  averageDisclosed,
  buildCapabilityRows,
  buildModelLoads,
  buildStorageRows,
  buildTaskClasses,
  filterModelLoads,
  filterStorageRows,
  loadModelCenter,
  maxDisclosed,
  resourceFrom,
  sumDisclosed,
  summarizeCapability,
  summarizeModelResources,
  summarizeStorage,
  summarizeTaskClasses,
  type ModelCenter,
  type ModelDeps,
} from '../src/lib/modelCenter'

const SHA_A = 'a'.repeat(64)
const DATASET_VERSION_ID = '11111111-1111-1111-1111-111111111111'
const RESEARCH_ID = '22222222-2222-2222-2222-222222222222'
const RESEARCH_ID_B = '33333333-3333-3333-3333-333333333333'
const VERSION_ID = '44444444-4444-4444-4444-444444444444'
const VERSION_ID_B = '55555555-5555-5555-5555-555555555555'
const RUN_ID = '66666666-6666-6666-6666-666666666666'

const SEMANTIC_PROFILE: SemanticProfile = {
  inputs: [],
  target: {
    name: 'y',
    unit: [0, 1],
    source_column: 'y',
    conversion: { source_unit: 'm', scale: '1', offset: '0' },
  },
  units_confirmed: true,
  time_ordered: false,
  measurement_resolution: null,
  resolution_reason: '',
  group_column: null,
}

const EVALUATION_POLICY: EvaluationPolicy = {
  policy_version: '2.0',
  metric_version: '2.0',
  error_model: 'EXACT',
  absolute_error_bound: null,
  comparison_method: 'IID_PAIRED_BOOTSTRAP',
  bootstrap_replicates: 1000,
  bootstrap_seed: 7,
  block_method: null,
  block_length: null,
  practical_scale_override: null,
  practical_margin_ratio: '0.05',
  baseline: 'ZERO',
  practical_scale_reason: null,
}

const OBSERVATION_SPLIT: ObservationSplit = {
  kind: 'IID_ROWS',
  dataset_version_id: DATASET_VERSION_ID,
  fit: [0, 1],
  development: [2],
  final_test: [3],
  gap_rows: 0,
  lookback_rows: 0,
  horizon_rows: 0,
  seed: 1,
  time_column: null,
  group_column: null,
  group_assignment_digest: null,
  splitter_version: '1.0',
  policy_version: '1.0',
  sealed_final_test: true,
  id: 'split-1',
  row_ids_hash: SHA_A,
  sealed_test_id: null,
}

function research(overrides: Partial<Research> = {}): Research {
  return {
    kind: 'Research',
    id: RESEARCH_ID,
    tenant_id: '77777777-7777-7777-7777-777777777777',
    schema_version: '2.0',
    created_at: '2026-10-20T00:00:00Z',
    name: 'sin 週期研究',
    owner_id: '88888888-8888-8888-8888-888888888888',
    ...overrides,
  }
}

function researchVersion(overrides: Partial<ResearchVersion> = {}): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id: VERSION_ID,
    tenant_id: '77777777-7777-7777-7777-777777777777',
    schema_version: '2.0',
    created_at: '2026-10-26T00:00:00Z',
    research_id: RESEARCH_ID,
    dataset_version_id: DATASET_VERSION_ID,
    semantic_profile: SEMANTIC_PROFILE,
    budget: { cpu_seconds: 60, gpu_seconds: 10, wall_seconds: 600, tokens: 1000, candidate_limit: 50, memory_bytes: 1048576 },
    purpose: 'DESCRIPTION',
    status: 'READY',
    revision: 1,
    observation_split: OBSERVATION_SPLIT,
    current_event_cursor: '0',
    frozen_submission_ids: [],
    evidence_bundle_ids: [],
    quality_report_id: null,
    refit_policy_artifact_id: null,
    domain: [],
    evaluation_policy: EVALUATION_POLICY,
    evaluation_policy_hash: SHA_A,
    research_budget_usage: usage({ tokens: 300, cpu_seconds: 20, gpu_seconds: 4, elapsed_wall_seconds: 42, peak_memory_bytes: 2048 }),
    structure_assessment_artifact_id: null,
    ...overrides,
  }
}

function usage(overrides: Partial<BudgetUsage> = {}): BudgetUsage {
  return {
    cpu_seconds: 0,
    gpu_seconds: 0,
    tokens: 0,
    peak_memory_bytes: 0,
    elapsed_wall_seconds: 0,
    candidates_generated: 0,
    candidates_accepted: 0,
    ...overrides,
  }
}

function run(overrides: Partial<Run> = {}): Run {
  return {
    kind: 'Run',
    id: RUN_ID,
    type: 'SEARCH',
    status: 'SUCCEEDED',
    revision: 1,
    created_at: '2026-10-26T01:00:00Z',
    dataset_id: null,
    research_version_id: VERSION_ID,
    current_event_cursor: '0',
    ...overrides,
  }
}

function center(overrides: Partial<ModelCenter> = {}): ModelCenter {
  return {
    researches: [research()],
    versions: [researchVersion()],
    runs: [{ run: run({ budget_usage: usage({ tokens: 120, cpu_seconds: 8, gpu_seconds: 2, elapsed_wall_seconds: 30, peak_memory_bytes: 4096 }) }), research: research(), version: researchVersion() }],
    scope: { researchesRead: 1, versionsRead: 1, runsRead: 1, truncated: false },
    ...overrides,
  }
}

function deps(overrides: Partial<ModelDeps> = {}): ModelDeps {
  return {
    listResearches: () => Promise.resolve({ items: [research()], next_cursor: null } satisfies ResearchPage),
    listResearchVersions: () => Promise.resolve({ items: [researchVersion()], next_cursor: null } satisfies ResearchVersionPage),
    listResearchVersionRuns: () => Promise.resolve({ items: [run()], next_cursor: null } satisfies RunPage),
    ...overrides,
  }
}

describe('loadModelCenter', () => {
  it('把任務關聯回研究版本與研究', async () => {
    const loaded = await loadModelCenter(deps())
    expect(loaded.researches).toHaveLength(1)
    expect(loaded.versions).toHaveLength(1)
    expect(loaded.runs).toHaveLength(1)
    expect(loaded.runs[0]?.run.id).toBe(RUN_ID)
    expect(loaded.runs[0]?.version?.id).toBe(VERSION_ID)
    expect(loaded.runs[0]?.research?.id).toBe(RESEARCH_ID)
    expect(loaded.scope).toEqual({ researchesRead: 1, versionsRead: 1, runsRead: 1, truncated: false })
  })

  it('研究或版本分頁仍有下一頁時標示截斷', async () => {
    const loaded = await loadModelCenter(
      deps({
        listResearches: () => Promise.resolve({ items: [research()], next_cursor: 'next' } satisfies ResearchPage),
      }),
    )
    expect(loaded.scope.truncated).toBe(true)
  })

  it('單一版本的任務讀取失敗不影響其他已揭露內容', async () => {
    const loaded = await loadModelCenter(
      deps({
        listResearches: () =>
          Promise.resolve({
            items: [research(), research({ id: RESEARCH_ID_B, name: '第二研究' })],
            next_cursor: null,
          } satisfies ResearchPage),
        listResearchVersions: (researchId) =>
          Promise.resolve({
            items:
              researchId === RESEARCH_ID
                ? [researchVersion()]
                : [researchVersion({ id: VERSION_ID_B, research_id: RESEARCH_ID_B })],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        listResearchVersionRuns: (versionId) =>
          versionId === VERSION_ID_B
            ? Promise.reject(new Error('boom'))
            : Promise.resolve({ items: [run()], next_cursor: null } satisfies RunPage),
      }),
    )
    expect(loaded.versions).toHaveLength(2)
    expect(loaded.runs).toHaveLength(1)
    expect(loaded.runs[0]?.run.research_version_id).toBe(VERSION_ID)
  })

  it('讀不到研究清單時以空集合回應，不拋出例外', async () => {
    const loaded = await loadModelCenter(
      deps({ listResearches: () => Promise.reject(new Error('offline')) }),
    )
    expect(loaded.researches).toEqual([])
    expect(loaded.versions).toEqual([])
    expect(loaded.runs).toEqual([])
  })
})

describe('資源用量推導', () => {
  it('任務未揭露預算用量時各欄為 null，不以 0 代替', () => {
    expect(resourceFrom(undefined)).toEqual({
      cpuSeconds: null,
      gpuSeconds: null,
      tokens: null,
      peakMemoryBytes: null,
      elapsedWallSeconds: null,
      candidatesGenerated: null,
      candidatesAccepted: null,
    })
  })

  it('只加總已揭露值；全部未揭露時回 null', () => {
    expect(sumDisclosed([null, null])).toBeNull()
    expect(sumDisclosed([1, null, 2])).toBe(3)
    expect(sumDisclosed([])).toBeNull()
  })

  it('平均與最大值只取已揭露值', () => {
    expect(averageDisclosed([10, null, 20])).toBe(15)
    expect(averageDisclosed([null])).toBeNull()
    expect(maxDisclosed([3, null, 9, 5])).toBe(9)
    expect(maxDisclosed([null])).toBeNull()
  })

  it('載入列的模型身分一律未取得，資源取自任務預算用量', () => {
    const rows = buildModelLoads(
      center({
        runs: [
          { run: run({ budget_usage: usage({ tokens: 55, elapsed_wall_seconds: 12 }) }), research: research(), version: researchVersion() },
          { run: run({ id: 'run-2', research_version_id: null }), research: null, version: null },
        ],
      }),
    )
    expect(rows[0]?.modelName).toBe(MODEL_UNKNOWN)
    expect(rows[0]?.contextWindow).toBe(MODEL_UNKNOWN)
    expect(rows[0]?.modelVersion).toBe(MODEL_UNKNOWN)
    expect(rows[0]?.resource.tokens).toBe(55)
    expect(rows[1]?.resource.tokens).toBeNull()
    expect(rows[1]?.researchId).toBeNull()
  })

  it('關鍵字篩選比對研究名稱、任務 ID 與任務類別', () => {
    const rows = buildModelLoads(center())
    expect(filterModelLoads(rows, 'sin')).toHaveLength(1)
    expect(filterModelLoads(rows, RUN_ID)).toHaveLength(1)
    expect(filterModelLoads(rows, '公式搜尋')).toHaveLength(1)
    expect(filterModelLoads(rows, '沒有這個')).toHaveLength(0)
    expect(filterModelLoads(rows, '  ')).toHaveLength(1)
  })

  it('資源摘要只涵蓋已揭露任務，完全未揭露時 Token 為 null', () => {
    const disclosed = summarizeModelResources(buildModelLoads(center()))
    expect(disclosed.tokens).toBe(120)
    expect(disclosed.gpuSeconds).toBe(2)
    expect(disclosed.peakMemoryBytes).toBe(4096)
    expect(disclosed.disclosed).toBe(1)
    expect(disclosed.total).toBe(1)

    const hidden = summarizeModelResources(
      buildModelLoads(center({ runs: [{ run: run(), research: null, version: null }] })),
    )
    expect(hidden.tokens).toBeNull()
    expect(hidden.cpuSeconds).toBeNull()
    expect(hidden.peakMemoryBytes).toBeNull()
    expect(hidden.disclosed).toBe(0)
    expect(hidden.total).toBe(1)
  })
})

describe('模型路由（任務分類）', () => {
  it('只列有任務的類別並維持固定順序', () => {
    const rows = buildTaskClasses(
      center({
        runs: [
          { run: run({ type: 'SEARCH' }), research: research(), version: researchVersion() },
          { run: run({ id: 'run-2', type: 'PROFILE' }), research: research(), version: researchVersion() },
          { run: run({ id: 'run-3', type: 'SEARCH', status: 'FAILED' }), research: research(), version: researchVersion() },
        ],
      }),
    )
    expect(rows.map((row) => row.taskClass)).toEqual<RunType[]>(['PROFILE', 'SEARCH'])
    const search = rows[1]
    expect(search?.runCount).toBe(2)
    expect(search?.failedCount).toBe(1)
    expect(search?.activeCount).toBe(0)
    expect(search?.candidateModels).toBe(MODEL_UNKNOWN)
    expect(search?.routingStrategy).toBe(MODEL_UNKNOWN)
  })

  it('沒有任務時不補造任何任務類別', () => {
    expect(buildTaskClasses(center({ runs: [] }))).toEqual([])
    expect(summarizeTaskClasses([])).toEqual({ classes: 0, runs: 0, active: 0, failed: 0 })
  })

  it('類別摘要加總任務、進行中與失敗數', () => {
    const rows = buildTaskClasses(
      center({
        runs: [
          { run: run({ type: 'SEARCH', status: 'RUNNING' }), research: research(), version: researchVersion() },
          { run: run({ id: 'run-2', type: 'VALIDATE', status: 'FAILED' }), research: research(), version: researchVersion() },
        ],
      }),
    )
    expect(summarizeTaskClasses(rows)).toEqual({ classes: 2, runs: 2, active: 1, failed: 1 })
  })
})

describe('模型能力評估（延遲與成本）', () => {
  it('基準分數一律未取得，延遲與成本由已揭露用量推導', () => {
    const rows = buildCapabilityRows(
      center({
        runs: [
          { run: run({ id: 'r1', type: 'SEARCH', budget_usage: usage({ tokens: 100, elapsed_wall_seconds: 10 }) }), research: research(), version: researchVersion() },
          { run: run({ id: 'r2', type: 'SEARCH', budget_usage: usage({ tokens: 200, elapsed_wall_seconds: 30 }) }), research: research(), version: researchVersion() },
          { run: run({ id: 'r3', type: 'SEARCH', status: 'FAILED' }), research: research(), version: researchVersion() },
        ],
      }),
    )
    const search = rows.find((row) => row.taskClass === 'SEARCH')
    expect(search?.benchmarkScore).toBe(MODEL_UNKNOWN)
    expect(search?.candidateModel).toBe(MODEL_UNKNOWN)
    expect(search?.sampleCount).toBe(3)
    expect(search?.successCount).toBe(2)
    expect(search?.averageWallSeconds).toBe(20)
    expect(search?.maxWallSeconds).toBe(30)
    expect(search?.tokens).toBe(300)
  })

  it('沒有已揭露延遲時平均值與最大值回 null，摘要 Token 亦為 null', () => {
    const rows = buildCapabilityRows(center({ runs: [{ run: run(), research: research(), version: researchVersion() }] }))
    const search = rows[0]
    expect(search?.averageWallSeconds).toBeNull()
    expect(search?.maxWallSeconds).toBeNull()
    const summary = summarizeCapability(rows)
    expect(summary.samples).toBe(1)
    expect(summary.tokens).toBeNull()
    expect(summary.wallSeconds).toBeNull()
  })
})

describe('Token 與儲存', () => {
  it('版本上限與累計用量取自版本預算欄位，未揭露欄位一律未取得', () => {
    const rows = buildStorageRows(center())
    const row = rows[0]
    expect(row?.tokenLimit).toBe(1000)
    expect(row?.usedTokens).toBe(300)
    expect(row?.usedCpuSeconds).toBe(20)
    expect(row?.usedGpuSeconds).toBe(4)
    expect(row?.overTokenLimit).toBe(false)
    expect(row?.eventRetention).toBe(MODEL_UNKNOWN)
    expect(row?.compression).toBe(MODEL_UNKNOWN)
    expect(row?.storageQuota).toBe(MODEL_UNKNOWN)
    expect(row?.researchName).toBe('sin 週期研究')
  })

  it('累計用量超過宣告上限時標示超額', () => {
    const rows = buildStorageRows(
      center({
        versions: [researchVersion({ research_budget_usage: usage({ tokens: 1200 }) })],
      }),
    )
    expect(rows[0]?.overTokenLimit).toBe(true)
    expect(summarizeStorage(rows).overTokenLimit).toBe(1)
  })

  it('版本無法對應研究時名稱退回未命名研究，不捏造名稱', () => {
    const rows = buildStorageRows(
      center({ researches: [], versions: [researchVersion({ research_id: RESEARCH_ID_B })] }),
    )
    expect(rows[0]?.researchName).toBe('未命名研究')
    expect(rows[0]?.researchId).toBe(RESEARCH_ID_B)
  })

  it('儲存摘要加總上限與用量並取尖峰記憶體最大值', () => {
    const rows = buildStorageRows(
      center({
        versions: [
          researchVersion({ research_budget_usage: usage({ tokens: 300, cpu_seconds: 20, gpu_seconds: 4, peak_memory_bytes: 2048 }) }),
          researchVersion({
            id: VERSION_ID_B,
            research_budget_usage: usage({ tokens: 100, cpu_seconds: 5, gpu_seconds: 1, peak_memory_bytes: 8192 }),
          }),
        ],
      }),
    )
    const summary = summarizeStorage(rows)
    expect(summary.versions).toBe(2)
    expect(summary.tokenLimit).toBe(2000)
    expect(summary.usedTokens).toBe(400)
    expect(summary.usedCpuSeconds).toBe(25)
    expect(summary.usedGpuSeconds).toBe(5)
    expect(summary.peakMemoryBytes).toBe(8192)
    expect(summary.overTokenLimit).toBe(0)
  })

  it('版本關鍵字篩選比對研究名稱與版本識別碼', () => {
    const rows = buildStorageRows(center())
    expect(filterStorageRows(rows, 'sin')).toHaveLength(1)
    expect(filterStorageRows(rows, VERSION_ID)).toHaveLength(1)
    expect(filterStorageRows(rows, '其他')).toHaveLength(0)
    expect(filterStorageRows(rows, '')).toHaveLength(1)
  })
})

describe('狀態標籤與讀取範圍常數', () => {
  it('讀取上限固定，供畫面標示統計範圍', () => {
    expect(RECENT_RUNS_READ).toBe(16)
    expect(MODEL_UNKNOWN).toBe('未取得')
  })

  it('版本狀態標籤涵蓋所有後端狀態值', () => {
    const statuses: ResearchVersionStatus[] = ['DRAFT', 'VALIDATING', 'READY', 'QUEUED', 'RUNNING', 'FAILED', 'CANCELLED']
    const rows = buildStorageRows(
      center({ versions: statuses.map((status) => researchVersion({ id: `v-${status}`, status })) }),
    )
    expect(rows).toHaveLength(statuses.length)
  })
})
