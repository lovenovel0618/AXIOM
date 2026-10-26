import { describe, expect, it } from 'vitest'
import type { BudgetUsage, Run } from '../src/api/runs'
import type {
  EvaluationPolicy,
  ObservationSplit,
  Research,
  ResearchPage,
  ResearchVersion,
  ResearchVersionPage,
  RunPage,
} from '../src/api/research'
import type { FinalEvaluation } from '../src/lib/finalEvaluation'
import {
  RECENT_RUNS_READ,
  RECENT_VERSIONS_READ,
  RESEARCHES_READ,
  TRAINING_UNKNOWN,
  buildFinetuneRows,
  buildReleaseRows,
  buildTrainingDatasets,
  filterFinetuneRows,
  filterReleaseRows,
  filterTrainingDatasets,
  loadTrainingCenter,
  summarizeFinetune,
  summarizeReleases,
  summarizeTrainingDatasets,
  type TrainingCenter,
  type TrainingDeps,
} from '../src/lib/trainingCenter'

const SHA_A = 'a'.repeat(64)
const SHA_B = 'b'.repeat(64)
const DATASET_VERSION_ID = '11111111-1111-1111-1111-111111111111'
const RESEARCH_ID = '22222222-2222-2222-2222-222222222222'
const RESEARCH_ID_B = '33333333-3333-3333-3333-333333333333'
const VERSION_ID = '44444444-4444-4444-4444-444444444444'
const VERSION_ID_B = '55555555-5555-5555-5555-555555555555'
const RUN_ID = '66666666-6666-6666-6666-666666666666'
const SUBMISSION_ID = '99999999-9999-9999-9999-999999999999'

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
    semantic_profile: {
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
    },
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
    research_budget_usage: usage(),
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

function evaluation(overrides: Partial<FinalEvaluation> = {}): FinalEvaluation {
  return {
    submissionId: SUBMISSION_ID,
    metricVersion: '2.0',
    status: 'EVALUATED',
    slots: [],
    exposure: { budget: 8, reserved: 1, consumed: 1, retired: 0 },
    ...overrides,
  }
}

function center(overrides: Partial<TrainingCenter> = {}): TrainingCenter {
  return {
    researches: [research()],
    versions: [researchVersion()],
    runs: [{ run: run(), research: research(), version: researchVersion() }],
    samples: [],
    scope: { researchesRead: 1, versionsRead: 1, runsRead: 1, samplesRead: 0, truncated: false },
    ...overrides,
  }
}

function deps(overrides: Partial<TrainingDeps> = {}): TrainingDeps {
  return {
    listResearches: () => Promise.resolve({ items: [research()], next_cursor: null } satisfies ResearchPage),
    listResearchVersions: () => Promise.resolve({ items: [researchVersion()], next_cursor: null } satisfies ResearchVersionPage),
    listResearchVersionRuns: () => Promise.resolve({ items: [run()], next_cursor: null } satisfies RunPage),
    getFinalEvaluation: () => Promise.resolve(evaluation()),
    ...overrides,
  }
}

describe('loadTrainingCenter', () => {
  it('把任務與樣本關聯回研究版本與研究，並回報讀取範圍', async () => {
    const loaded = await loadTrainingCenter(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [researchVersion({ frozen_submission_ids: [SUBMISSION_ID] })],
            next_cursor: null,
          } satisfies ResearchVersionPage),
      }),
    )
    expect(loaded.researches).toHaveLength(1)
    expect(loaded.versions).toHaveLength(1)
    expect(loaded.runs).toHaveLength(1)
    expect(loaded.runs[0]?.research?.id).toBe(RESEARCH_ID)
    expect(loaded.runs[0]?.version?.id).toBe(VERSION_ID)
    expect(loaded.samples).toHaveLength(1)
    expect(loaded.samples[0]?.submissionId).toBe(SUBMISSION_ID)
    expect(loaded.samples[0]?.evaluation?.status).toBe('EVALUATED')
    expect(loaded.scope).toEqual({ researchesRead: 1, versionsRead: 1, runsRead: 1, samplesRead: 1, truncated: false })
  })

  it('研究或版本分頁仍有下一頁時標示截斷', async () => {
    const loaded = await loadTrainingCenter(
      deps({
        listResearches: () => Promise.resolve({ items: [research()], next_cursor: 'next' } satisfies ResearchPage),
      }),
    )
    expect(loaded.scope.truncated).toBe(true)
  })

  it('單一版本讀取失敗不影響其他已揭露內容', async () => {
    const loaded = await loadTrainingCenter(
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
    expect(loaded.runs[0]?.run.id).toBe(RUN_ID)
  })

  it('讀不到最終評估時樣本仍保留且標示未取得', async () => {
    const loaded = await loadTrainingCenter(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [researchVersion({ frozen_submission_ids: [SUBMISSION_ID] })],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        getFinalEvaluation: () => Promise.reject(new Error('offline')),
      }),
    )
    expect(loaded.samples).toHaveLength(1)
    expect(loaded.samples[0]?.evaluation).toBeNull()
  })

  it('讀不到研究清單時以空集合回應，不拋出例外', async () => {
    const loaded = await loadTrainingCenter(deps({ listResearches: () => Promise.reject(new Error('offline')) }))
    expect(loaded.researches).toEqual([])
    expect(loaded.versions).toEqual([])
    expect(loaded.runs).toEqual([])
    expect(loaded.samples).toEqual([])
  })
})

describe('訓練資料集（SCREEN 36）', () => {
  it('只列宣告了凍結提交的版本，其餘不補造', () => {
    const rows = buildTrainingDatasets(
      center({
        versions: [
          researchVersion({ frozen_submission_ids: [SUBMISSION_ID] }),
          researchVersion({ id: VERSION_ID_B }),
        ],
      }),
    )
    expect(rows).toHaveLength(1)
    expect(rows[0]?.versionId).toBe(VERSION_ID)
    expect(rows[0]?.researchName).toBe('sin 週期研究')
    expect(rows[0]?.labelPolicyHash).toBe(SHA_A)
  })

  it('樣本狀態依最終評估計數，讀不到評估算未取得', () => {
    const version = researchVersion({ frozen_submission_ids: ['s1', 's2', 's3', 's4'] })
    const rows = buildTrainingDatasets(
      center({
        versions: [version],
        samples: [
          { version, research: research(), submissionId: 's1', evaluation: evaluation({ status: 'EVALUATED' }) },
          { version, research: research(), submissionId: 's2', evaluation: evaluation({ status: 'FAILED' }) },
          { version, research: research(), submissionId: 's3', evaluation: evaluation({ status: 'EVALUATING' }) },
          { version, research: research(), submissionId: 's4', evaluation: null },
        ],
      }),
    )
    expect(rows[0]?.samples).toEqual({ declared: 4, evaluated: 1, running: 1, failed: 1, unknown: 1 })
    expect(rows[0]?.metricVersion).toBe('2.0')
  })

  it('全部評估未取得時計量版本顯示未取得', () => {
    const version = researchVersion({ frozen_submission_ids: ['s1'] })
    const rows = buildTrainingDatasets(
      center({ versions: [version], samples: [{ version, research: research(), submissionId: 's1', evaluation: null }] }),
    )
    expect(rows[0]?.metricVersion).toBe(TRAINING_UNKNOWN)
  })

  it('摘要加總宣告、已評估與失敗樣本', () => {
    const version = researchVersion({ frozen_submission_ids: ['s1', 's2'] })
    const rows = buildTrainingDatasets(
      center({
        versions: [version],
        samples: [
          { version, research: research(), submissionId: 's1', evaluation: evaluation({ status: 'EVALUATED' }) },
          { version, research: research(), submissionId: 's2', evaluation: evaluation({ status: 'FAILED' }) },
        ],
      }),
    )
    expect(summarizeTrainingDatasets(rows)).toEqual({ datasets: 1, declared: 2, evaluated: 1, failed: 1 })
  })

  it('關鍵字篩選比對研究名稱、版本 ID 與研究目的', () => {
    const rows = buildTrainingDatasets(center({ versions: [researchVersion({ frozen_submission_ids: [SUBMISSION_ID] })] }))
    expect(filterTrainingDatasets(rows, 'sin')).toHaveLength(1)
    expect(filterTrainingDatasets(rows, VERSION_ID)).toHaveLength(1)
    expect(filterTrainingDatasets(rows, '描述')).toHaveLength(1)
    expect(filterTrainingDatasets(rows, '沒有這個')).toHaveLength(0)
    expect(filterTrainingDatasets(rows, '   ')).toHaveLength(1)
  })
})

describe('微調任務（SCREEN 37）', () => {
  it('配額取自版本預算、用量取自任務，LoRA 身分一律未取得', () => {
    const rows = buildFinetuneRows(
      center({
        runs: [
          {
            run: run({ budget_usage: usage({ cpu_seconds: 12, gpu_seconds: 3, tokens: 200 }) }),
            research: research(),
            version: researchVersion(),
          },
        ],
      }),
    )
    const row = rows[0]
    expect(row?.taskLabel).toBe('公式搜尋')
    expect(row?.quotaCpuSeconds).toBe(60)
    expect(row?.quotaGpuSeconds).toBe(10)
    expect(row?.quotaTokens).toBe(1000)
    expect(row?.usedCpuSeconds).toBe(12)
    expect(row?.usedGpuSeconds).toBe(3)
    expect(row?.usedTokens).toBe(200)
    expect(row?.adapterTarget).toBe(TRAINING_UNKNOWN)
    expect(row?.baseModel).toBe(TRAINING_UNKNOWN)
    expect(row?.checkpoint).toBe(TRAINING_UNKNOWN)
  })

  it('沒有版本或預算用量時配額與用量為 null，不以 0 代替', () => {
    const rows = buildFinetuneRows(
      center({ runs: [{ run: run({ research_version_id: null }), research: null, version: null }] }),
    )
    const row = rows[0]
    expect(row?.quotaCpuSeconds).toBeNull()
    expect(row?.usedCpuSeconds).toBeNull()
    expect(row?.usedTokens).toBeNull()
    expect(row?.researchName).toBe(TRAINING_UNKNOWN)
    expect(row?.versionId).toBeNull()
  })

  it('摘要加總任務、進行中、失敗與配額；完全未揭露時配額為 null', () => {
    const rows = buildFinetuneRows(
      center({
        runs: [
          { run: run({ status: 'RUNNING' }), research: research(), version: researchVersion() },
          { run: run({ id: 'r2', status: 'FAILED' }), research: research(), version: researchVersion() },
          { run: run({ id: 'r3', status: 'SUCCEEDED' }), research: research(), version: researchVersion() },
        ],
      }),
    )
    expect(summarizeFinetune(rows)).toEqual({
      tasks: 3,
      active: 1,
      failed: 1,
      quotaCpuSeconds: 180,
      quotaGpuSeconds: 30,
    })

    const hidden = summarizeFinetune(
      buildFinetuneRows(center({ runs: [{ run: run(), research: null, version: null }] })),
    )
    expect(hidden.quotaCpuSeconds).toBeNull()
    expect(hidden.quotaGpuSeconds).toBeNull()
  })

  it('關鍵字篩選比對研究名稱、任務 ID 與任務類別', () => {
    const rows = buildFinetuneRows(center())
    expect(filterFinetuneRows(rows, 'sin')).toHaveLength(1)
    expect(filterFinetuneRows(rows, RUN_ID)).toHaveLength(1)
    expect(filterFinetuneRows(rows, '公式搜尋')).toHaveLength(1)
    expect(filterFinetuneRows(rows, '沒有這個')).toHaveLength(0)
  })
})

describe('模型版本發布（SCREEN 38）', () => {
  it('只列已宣告凍結提交或已就緒的版本，發布資訊一律未取得', () => {
    const rows = buildReleaseRows(
      center({
        versions: [
          researchVersion({ frozen_submission_ids: [SUBMISSION_ID] }),
          researchVersion({ id: VERSION_ID_B, status: 'DRAFT' }),
        ],
      }),
    )
    expect(rows).toHaveLength(1)
    expect(rows[0]?.versionId).toBe(VERSION_ID)
    expect(rows[0]?.declaredSubmissions).toBe(1)
    expect(rows[0]?.modelName).toBe(TRAINING_UNKNOWN)
    expect(rows[0]?.modelVersion).toBe(TRAINING_UNKNOWN)
    expect(rows[0]?.releaseChannel).toBe(TRAINING_UNKNOWN)
    expect(rows[0]?.releasedAt).toBe(TRAINING_UNKNOWN)
  })

  it('沒有宣告提交但狀態就緒的版本也算發布候選', () => {
    const rows = buildReleaseRows(center({ versions: [researchVersion({ status: 'READY' })] }))
    expect(rows).toHaveLength(1)
    expect(rows[0]?.declaredSubmissions).toBe(0)
  })

  it('已評估提交數只計入已讀取到的評估', () => {
    const version = researchVersion({ frozen_submission_ids: ['s1', 's2'] })
    const rows = buildReleaseRows(
      center({
        versions: [version],
        samples: [
          { version, research: research(), submissionId: 's1', evaluation: evaluation({ status: 'EVALUATED' }) },
          { version, research: research(), submissionId: 's2', evaluation: null },
        ],
      }),
    )
    expect(rows[0]?.declaredSubmissions).toBe(2)
    expect(rows[0]?.evaluatedSubmissions).toBe(1)
  })

  it('摘要加總候選、已就緒、凍結提交與已評估', () => {
    const version = researchVersion({ frozen_submission_ids: ['s1'] })
    const rows = buildReleaseRows(
      center({
        versions: [version, researchVersion({ id: VERSION_ID_B, status: 'READY', evaluation_policy_hash: SHA_B })],
        samples: [{ version, research: research(), submissionId: 's1', evaluation: evaluation({ status: 'EVALUATED' }) }],
      }),
    )
    expect(summarizeReleases(rows)).toEqual({ versions: 2, ready: 2, submissions: 1, evaluated: 1 })
  })

  it('關鍵字篩選比對研究名稱、版本 ID 與政策指紋', () => {
    const rows = buildReleaseRows(center({ versions: [researchVersion({ status: 'READY' })] }))
    expect(filterReleaseRows(rows, 'sin')).toHaveLength(1)
    expect(filterReleaseRows(rows, VERSION_ID)).toHaveLength(1)
    expect(filterReleaseRows(rows, SHA_A)).toHaveLength(1)
    expect(filterReleaseRows(rows, '沒有這個')).toHaveLength(0)
  })
})

describe('讀取範圍常數', () => {
  it('讀取上限固定，供畫面標示統計範圍', () => {
    expect(RESEARCHES_READ).toBe(12)
    expect(RECENT_VERSIONS_READ).toBe(12)
    expect(RECENT_RUNS_READ).toBe(16)
    expect(TRAINING_UNKNOWN).toBe('未取得')
  })
})
