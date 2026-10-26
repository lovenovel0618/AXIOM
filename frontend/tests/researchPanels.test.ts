import { describe, expect, it } from 'vitest'
import type {
  EvaluationPolicy,
  ObservationSplit,
  Research,
  ResearchPage,
  ResearchVersion,
  ResearchVersionPage,
  RunPage,
} from '../src/api/research'
import type { Run } from '../src/api/runs'
import type { FinalEvaluation } from '../src/lib/finalEvaluation'
import {
  EVALUATIONS_READ,
  RESEARCH_UNKNOWN,
  RESEARCHES_READ,
  RUNS_PER_VERSION,
  VERSIONS_PER_RESEARCH,
  buildResearchGraph,
  buildResearchProfile,
  buildResearchTimeline,
  filterResearchTimeline,
  loadResearchPanel,
  summarizeResearchGraph,
  summarizeResearchProfile,
  summarizeResearchTimeline,
  type ResearchPanelDeps,
} from '../src/lib/researchPanels'

const SHA_A = 'a'.repeat(64)
const TENANT_ID = '77777777-7777-7777-7777-777777777777'
const OWNER_ID = '88888888-8888-8888-8888-888888888888'
const DATASET_VERSION_ID = '11111111-1111-1111-1111-111111111111'
const RESEARCH_ID = '22222222-2222-2222-2222-222222222222'
const RESEARCH_ID_B = '33333333-3333-3333-3333-333333333333'
const VERSION_A = '44444444-4444-4444-4444-444444444444'
const VERSION_B = '55555555-5555-5555-5555-555555555555'
const SUBMISSION_A = '66666666-6666-6666-6666-666666666666'
const SUBMISSION_B = '77777777-7777-7777-7777-777777777778'

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
  sealed_final_test: false,
  id: 'split-1',
  row_ids_hash: SHA_A,
  sealed_test_id: null,
}

function research(overrides: Partial<Research> = {}): Research {
  return {
    kind: 'Research',
    id: RESEARCH_ID,
    tenant_id: TENANT_ID,
    schema_version: '2.0',
    created_at: '2026-10-20T00:00:00Z',
    name: 'sin 週期研究',
    owner_id: OWNER_ID,
    ...overrides,
  }
}

function version(overrides: Partial<ResearchVersion> = {}): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id: VERSION_A,
    tenant_id: TENANT_ID,
    schema_version: '2.0',
    created_at: '2026-10-26T00:00:00Z',
    research_id: RESEARCH_ID,
    dataset_version_id: DATASET_VERSION_ID,
    semantic_profile: {
      inputs: [
        { name: 'x', unit: [1], source_column: 'x', conversion: { source_unit: 's', scale: '1', offset: '0' } },
      ],
      target: { name: 'y', unit: [1], source_column: 'y', conversion: { source_unit: 'm', scale: '1', offset: '0' } },
      units_confirmed: true,
      time_ordered: true,
      measurement_resolution: '0.001',
      resolution_reason: '依欄位小數位數推定',
      group_column: null,
    },
    budget: { cpu_seconds: 60, gpu_seconds: 10, wall_seconds: 600, tokens: 1000, candidate_limit: 50, memory_bytes: 1048576 },
    purpose: 'DESCRIPTION',
    status: 'READY',
    revision: 3,
    observation_split: OBSERVATION_SPLIT,
    current_event_cursor: '12',
    frozen_submission_ids: [],
    evidence_bundle_ids: [],
    quality_report_id: null,
    refit_policy_artifact_id: null,
    domain: [
      { name: 'x', lower: { numerator: '0', denominator: '1' }, upper: { numerator: '1', denominator: '1' }, lower_closed: true, upper_closed: true },
    ],
    evaluation_policy: EVALUATION_POLICY,
    evaluation_policy_hash: SHA_A,
    research_budget_usage: {
      cpu_seconds: 12,
      gpu_seconds: 3,
      tokens: 100,
      peak_memory_bytes: 0,
      elapsed_wall_seconds: 0,
      candidates_generated: 5,
      candidates_accepted: 2,
    },
    structure_assessment_artifact_id: null,
    ...overrides,
  }
}

function run(overrides: Partial<Run> = {}): Run {
  return {
    kind: 'Run',
    id: '99999999-9999-9999-9999-999999999999',
    type: 'SEARCH',
    status: 'SUCCEEDED',
    revision: 1,
    created_at: '2026-10-26T01:00:00Z',
    dataset_id: null,
    research_version_id: VERSION_A,
    current_event_cursor: '42',
    ...overrides,
  }
}

function evaluation(overrides: Partial<FinalEvaluation> = {}): FinalEvaluation {
  return {
    submissionId: SUBMISSION_A,
    metricVersion: '2.0',
    status: 'EVALUATED',
    slots: [],
    exposure: { budget: 10, reserved: 0, consumed: 1, retired: 0 },
    ...overrides,
  }
}

function deps(overrides: Partial<ResearchPanelDeps> = {}): ResearchPanelDeps {
  return {
    listResearches: () => Promise.resolve({ items: [research()], next_cursor: null } satisfies ResearchPage),
    listResearchVersions: () =>
      Promise.resolve({ items: [version()], next_cursor: null } satisfies ResearchVersionPage),
    listResearchVersionRuns: () =>
      Promise.resolve({ items: [run()], next_cursor: null } satisfies RunPage),
    getFinalEvaluation: () => Promise.resolve(null),
    ...overrides,
  }
}

describe('loadResearchPanel', () => {
  it('讀取研究、版本、任務與凍結提交的最終評估，並記錄讀取範圍', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [
              version({ id: VERSION_B, created_at: '2026-10-25T00:00:00Z' }),
              version({ id: VERSION_A, created_at: '2026-10-26T00:00:00Z', frozen_submission_ids: [SUBMISSION_A] }),
            ],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        getFinalEvaluation: () => Promise.resolve(evaluation()),
      }),
      RESEARCH_ID,
    )

    expect(panel.research?.id).toBe(RESEARCH_ID)
    // 版本以建立時間反序，最新在前。
    expect(panel.versions.map((item) => item.id)).toEqual([VERSION_A, VERSION_B])
    expect(panel.runs).toHaveLength(2)
    expect(panel.samples).toHaveLength(1)
    expect(panel.samples[0]?.submissionId).toBe(SUBMISSION_A)
    expect(panel.samples[0]?.evaluation?.status).toBe('EVALUATED')
    expect(panel.scope).toEqual({
      researchesRead: 1,
      versionsRead: 2,
      runsRead: 2,
      samplesRead: 1,
      truncated: false,
    })
  })

  it('任一分頁仍有下一頁時標示截斷', async () => {
    const panel = await loadResearchPanel(
      deps({ listResearchVersionRuns: () => Promise.resolve({ items: [run()], next_cursor: 'next' } satisfies RunPage) }),
      RESEARCH_ID,
    )
    expect(panel.scope.truncated).toBe(true)
  })

  it('研究不在已讀取頁面時其餘一律回空集合', async () => {
    const panel = await loadResearchPanel(deps(), RESEARCH_ID_B)
    expect(panel.research).toBeNull()
    expect(panel.versions).toEqual([])
    expect(panel.runs).toEqual([])
    expect(panel.samples).toEqual([])
    expect(panel.scope.versionsRead).toBe(0)
  })

  it('研究清單讀取失敗時回空集合而非拋出例外', async () => {
    const panel = await loadResearchPanel(deps({ listResearches: () => Promise.reject(new Error('offline')) }), RESEARCH_ID)
    expect(panel.research).toBeNull()
    expect(panel.versions).toEqual([])
  })

  it('單一版本的任務讀取失敗不影響其他已揭露內容', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [version({ id: VERSION_A }), version({ id: VERSION_B })],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        listResearchVersionRuns: (versionId) =>
          versionId === VERSION_B
            ? Promise.reject(new Error('boom'))
            : Promise.resolve({ items: [run()], next_cursor: null } satisfies RunPage),
      }),
      RESEARCH_ID,
    )
    expect(panel.runs).toHaveLength(1)
    expect(panel.runs[0]?.version.id).toBe(VERSION_A)
  })

  it('最終評估讀取失敗時樣本仍保留，但評估為未取得', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [version({ frozen_submission_ids: [SUBMISSION_A] })],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        getFinalEvaluation: () => Promise.reject(new Error('boom')),
      }),
      RESEARCH_ID,
    )
    expect(panel.samples).toHaveLength(1)
    expect(panel.samples[0]?.evaluation).toBeNull()
  })

  it('凍結提交超過讀取上限時停止讀取並標示截斷', async () => {
    const many = Array.from({ length: EVALUATIONS_READ + 3 }, (_, index) => `sub-${String(index)}`)
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({ items: [version({ frozen_submission_ids: many })], next_cursor: null } satisfies ResearchVersionPage),
      }),
      RESEARCH_ID,
    )
    expect(panel.samples).toHaveLength(EVALUATIONS_READ)
    expect(panel.scope.truncated).toBe(true)
  })

  it('讀取上限為固定常數', () => {
    expect(RESEARCHES_READ).toBe(12)
    expect(VERSIONS_PER_RESEARCH).toBe(8)
    expect(RUNS_PER_VERSION).toBe(12)
    expect(EVALUATIONS_READ).toBe(16)
  })
})

describe('研究詳情（SCREEN 08）', () => {
  it('目標取自最新版本的語意概況，未揭露欄位標示未取得', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [
              version({ id: VERSION_B, created_at: '2026-10-25T00:00:00Z' }),
              version({ id: VERSION_A, created_at: '2026-10-26T00:00:00Z' }),
            ],
            next_cursor: null,
          } satisfies ResearchVersionPage),
      }),
      RESEARCH_ID,
    )
    const profile = buildResearchProfile(panel)
    expect(profile.researchId).toBe(RESEARCH_ID)
    expect(profile.researchName).toBe('sin 週期研究')
    expect(profile.goals.map((goal) => goal.label)).toEqual([
      '研究目的',
      '資料集版本',
      '目標量',
      '輸入量',
      '單位確認',
      '時間序列',
      '量測解析度',
      '分組欄位',
    ])
    expect(profile.goals[4]?.value).toBe('已確認')
    expect(profile.goals[6]?.value).toBe('0.001')
    expect(profile.goals[7]?.value).toBe(RESEARCH_UNKNOWN)
  })

  it('沒有版本時每一個目標都以未取得呈現', async () => {
    const panel = await loadResearchPanel(
      deps({ listResearchVersions: () => Promise.resolve({ items: [], next_cursor: null } satisfies ResearchVersionPage) }),
      RESEARCH_ID,
    )
    const profile = buildResearchProfile(panel)
    expect(profile.goals.every((goal) => goal.value === RESEARCH_UNKNOWN)).toBe(true)
    expect(profile.snapshots).toEqual([])
    expect(profile.outcomes.declaredSubmissions).toBe(0)
  })

  it('快照投影預算、用量、封存設定與證據，成果統計以宣告與已評估計數', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [
              version({
                frozen_submission_ids: [SUBMISSION_A, SUBMISSION_B],
                evidence_bundle_ids: ['bundle-1'],
                quality_report_id: 'quality-1',
                observation_split: { ...OBSERVATION_SPLIT, sealed_final_test: true },
              }),
            ],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        getFinalEvaluation: (submissionId) =>
          submissionId === SUBMISSION_A
            ? Promise.resolve(evaluation({ status: 'EVALUATED' }))
            : Promise.resolve(evaluation({ status: 'FAILED' })),
      }),
      RESEARCH_ID,
    )
    const profile = buildResearchProfile(panel)
    const snapshot = profile.snapshots[0]
    expect(snapshot?.budgetTokens).toBe(1000)
    expect(snapshot?.usedCpuSeconds).toBe(12)
    expect(snapshot?.candidatesGenerated).toBe(5)
    expect(snapshot?.sealedFinalTest).toBe(true)
    expect(snapshot?.domainCount).toBe(1)
    expect(snapshot?.qualityReportId).toBe('quality-1')
    expect(snapshot?.evidenceBundleCount).toBe(1)

    expect(profile.outcomes).toMatchObject({
      declaredSubmissions: 2,
      evaluatedSubmissions: 1,
      failedSubmissions: 1,
      unknownSubmissions: 0,
      sealedTestCount: 1,
      qualityReportCount: 1,
      evidenceBundleCount: 1,
      candidatesGenerated: 5,
      candidatesAccepted: 2,
    })
    expect(summarizeResearchProfile(profile)).toEqual({
      versions: 1,
      ready: 1,
      declaredSubmissions: 2,
      evaluatedSubmissions: 1,
    })
  })

  it('讀不到的最終評估計入未取得而非 0', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [version({ frozen_submission_ids: [SUBMISSION_A, SUBMISSION_B] })],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        getFinalEvaluation: () => Promise.resolve(null),
      }),
      RESEARCH_ID,
    )
    const outcomes = buildResearchProfile(panel).outcomes
    expect(outcomes.declaredSubmissions).toBe(2)
    expect(outcomes.evaluatedSubmissions).toBe(0)
    expect(outcomes.failedSubmissions).toBe(0)
    expect(outcomes.unknownSubmissions).toBe(2)
  })
})

describe('研究分支圖（SCREEN 09）', () => {
  it('以研究 → 版本 → 任務建立節點與歸屬邊', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [
              version({ id: VERSION_A, created_at: '2026-10-26T00:00:00Z' }),
              version({ id: VERSION_B, created_at: '2026-10-25T00:00:00Z' }),
            ],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        listResearchVersionRuns: (versionId) =>
          Promise.resolve({
            items: [run({ id: `run-${versionId}` })],
            next_cursor: null,
          } satisfies RunPage),
      }),
      RESEARCH_ID,
    )
    const graph = buildResearchGraph(panel)
    const kinds = graph.nodes.map((node) => node.kind)
    expect(kinds.filter((kind) => kind === 'RESEARCH')).toHaveLength(1)
    expect(kinds.filter((kind) => kind === 'VERSION')).toHaveLength(2)
    expect(kinds.filter((kind) => kind === 'RUN')).toHaveLength(2)
    expect(graph.columns).toBe(3)
    // 研究 → 兩個版本各一條邊，且因版本數大於一標為分支。
    const rootEdges = graph.edges.filter((edge) => edge.from === `research:${RESEARCH_ID}`)
    expect(rootEdges).toHaveLength(2)
    expect(rootEdges.every((edge) => edge.branch)).toBe(true)
    expect(graph.nodes[0]?.badge).toBe('2 個版本')
  })

  it('同版本同型任務依建立時間標示重試序號', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersionRuns: () =>
          Promise.resolve({
            items: [
              run({ id: 'run-first', created_at: '2026-10-26T01:00:00Z' }),
              run({ id: 'run-second', created_at: '2026-10-26T02:00:00Z' }),
            ],
            next_cursor: null,
          } satisfies RunPage),
      }),
      RESEARCH_ID,
    )
    const graph = buildResearchGraph(panel)
    const first = graph.nodes.find((node) => node.id === 'run:run-first')
    const second = graph.nodes.find((node) => node.id === 'run:run-second')
    expect(first?.retryIndex).toBe(1)
    expect(second?.retryIndex).toBe(2)
    expect(summarizeResearchGraph(panel)).toMatchObject({
      versions: 1,
      runs: 2,
      branches: 1,
      retries: 1,
    })
  })

  it('不同型別任務不互相計為重試', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersionRuns: () =>
          Promise.resolve({
            items: [
              run({ id: 'run-search', type: 'SEARCH', created_at: '2026-10-26T01:00:00Z' }),
              run({ id: 'run-fit', type: 'FIT', created_at: '2026-10-26T02:00:00Z' }),
            ],
            next_cursor: null,
          } satisfies RunPage),
      }),
      RESEARCH_ID,
    )
    expect(summarizeResearchGraph(panel).retries).toBe(0)
  })

  it('找不到研究時根節點標示未取得且無版本邊', async () => {
    const panel = await loadResearchPanel(deps(), RESEARCH_ID_B)
    const graph = buildResearchGraph(panel)
    expect(graph.nodes).toHaveLength(1)
    expect(graph.nodes[0]?.badge).toBe('未取得')
    expect(graph.nodes[0]?.tone).toBe('NEUTRAL')
    expect(graph.edges).toEqual([])
  })

  it('失敗或取消的任務計入失敗統計', async () => {
    const panel = await loadResearchPanel(
      deps({
        listResearchVersionRuns: () =>
          Promise.resolve({
            items: [
              run({ id: 'run-ok', status: 'SUCCEEDED' }),
              run({ id: 'run-failed', status: 'FAILED', created_at: '2026-10-26T02:00:00Z' }),
              run({ id: 'run-cancelled', status: 'CANCELLED', created_at: '2026-10-26T03:00:00Z' }),
            ],
            next_cursor: null,
          } satisfies RunPage),
      }),
      RESEARCH_ID,
    )
    expect(summarizeResearchGraph(panel).failed).toBe(2)
  })
})

describe('研究任務紀錄（SCREEN 10）', () => {
  async function timelinePanel() {
    return loadResearchPanel(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [version({ id: VERSION_A, revision: 4, status: 'RUNNING' })],
            next_cursor: null,
          } satisfies ResearchVersionPage),
        listResearchVersionRuns: () =>
          Promise.resolve({
            items: [
              run({ id: 'run-earliest', created_at: '2026-10-26T01:00:00Z', status: 'SUCCEEDED' }),
              run({ id: 'run-later', created_at: '2026-10-26T02:00:00Z', status: 'FAILED' }),
              run({
                id: 'run-newest',
                created_at: '2026-10-26T03:00:00Z',
                status: 'RUNNING',
                type: 'FIT',
                phase: 'FITTING',
                budget_usage: {
                  cpu_seconds: 30,
                  gpu_seconds: 5,
                  tokens: 200,
                  peak_memory_bytes: 0,
                  elapsed_wall_seconds: 0,
                  candidates_generated: 1,
                  candidates_accepted: 1,
                },
              }),
            ],
            next_cursor: null,
          } satisfies RunPage),
      }),
      RESEARCH_ID,
    )
  }

  it('時間軸由新到舊，並帶出所屬版本、重試與事件游標', async () => {
    const entries = buildResearchTimeline(await timelinePanel())
    expect(entries.map((entry) => entry.runId)).toEqual(['run-newest', 'run-later', 'run-earliest'])
    const newest = entries[0]
    expect(newest?.typeLabel).toBe('參數擬合')
    expect(newest?.statusLabel).toBe('執行中')
    expect(newest?.terminal).toBe(false)
    expect(newest?.replayCursor).toBe('42')
    expect(newest?.cpuSeconds).toBe(30)
    // run-earliest 與 run-later 同型（SEARCH），第二筆即為重試。
    expect(entries[1]?.isRetry).toBe(true)
    expect(entries[2]?.isRetry).toBe(false)
    expect(newest?.versionLabel).toContain('控制版本 4')
  })

  it('未揭露欄位以未取得表示，未提供用量時三個用量皆為 null', async () => {
    const entries = buildResearchTimeline(await timelinePanel())
    const earliest = entries[2]
    expect(earliest?.phase).toBe(RESEARCH_UNKNOWN)
    expect(earliest?.stopReason).toBe(RESEARCH_UNKNOWN)
    expect(earliest?.outcomeStatus).toBe(RESEARCH_UNKNOWN)
    expect(earliest?.cpuSeconds).toBeNull()
    expect(earliest?.gpuSeconds).toBeNull()
    expect(earliest?.tokens).toBeNull()
  })

  it('摘要統計排隊、執行中、失敗、重試與已結束', async () => {
    const entries = buildResearchTimeline(await timelinePanel())
    expect(summarizeResearchTimeline(entries)).toEqual({
      entries: 3,
      queued: 0,
      running: 1,
      failed: 1,
      retried: 1,
      terminal: 2,
    })
  })

  it('關鍵字與狀態篩選', async () => {
    const entries = buildResearchTimeline(await timelinePanel())
    expect(filterResearchTimeline(entries, '')).toHaveLength(3)
    expect(filterResearchTimeline(entries, 'run-later')).toHaveLength(1)
    expect(filterResearchTimeline(entries, '', 'FAILED')).toHaveLength(1)
    expect(filterResearchTimeline(entries, '參數擬合')).toHaveLength(1)
    expect(filterResearchTimeline(entries, '沒有這個')).toHaveLength(0)
    expect(filterResearchTimeline(entries, '  ')).toHaveLength(3)
  })
})
