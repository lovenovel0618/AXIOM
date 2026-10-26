import { describe, expect, it } from 'vitest'
import type {
  EvaluationPolicy,
  ObservationSplit,
  Research,
  ResearchPage,
  ResearchVersion,
  ResearchVersionPage,
} from '../src/api/research'
import {
  RECENT_VERSIONS_READ,
  RESEARCHES_READ,
  SETTINGS_UNKNOWN,
  buildSecurityRows,
  buildStrategyRows,
  filterSecurityRows,
  filterStrategyRows,
  loadSettingsCenter,
  summarizeSecurity,
  summarizeStrategy,
  type SettingsDeps,
} from '../src/lib/settingsCenter'

const SHA_A = 'a'.repeat(64)
const SHA_B = 'b'.repeat(64)
const DATASET_VERSION_ID = '11111111-1111-1111-1111-111111111111'
const RESEARCH_ID = '22222222-2222-2222-2222-222222222222'
const RESEARCH_ID_B = '33333333-3333-3333-3333-333333333333'
const VERSION_ID = '44444444-4444-4444-4444-444444444444'
const VERSION_ID_B = '55555555-5555-5555-5555-555555555555'

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
    domain: [
      { name: 'x', lower: { numerator: '0', denominator: '1' }, upper: { numerator: '1', denominator: '1' }, lower_closed: true, upper_closed: true },
      { name: 'y', lower: { numerator: '-1', denominator: '1' }, upper: { numerator: '1', denominator: '1' }, lower_closed: true, upper_closed: true },
    ],
    evaluation_policy: EVALUATION_POLICY,
    evaluation_policy_hash: SHA_A,
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
    ...overrides,
  }
}

function deps(overrides: Partial<SettingsDeps> = {}): SettingsDeps {
  return {
    checkReadiness: () => Promise.resolve('ready'),
    listResearches: () => Promise.resolve({ items: [research()], next_cursor: null } satisfies ResearchPage),
    listResearchVersions: () =>
      Promise.resolve({ items: [researchVersion()], next_cursor: null } satisfies ResearchVersionPage),
    ...overrides,
  }
}

describe('loadSettingsCenter', () => {
  it('讀取就緒狀態、研究與版本，並由已讀取實體推導租戶識別', async () => {
    const loaded = await loadSettingsCenter(deps())
    expect(loaded.readiness).toBe('ready')
    expect(loaded.researches).toHaveLength(1)
    expect(loaded.versions).toHaveLength(1)
    expect(loaded.tenantIds).toEqual(['77777777-7777-7777-7777-777777777777'])
    expect(loaded.scope).toEqual({ researchesRead: 1, versionsRead: 1, truncated: false })
  })

  it('就緒檢查失敗時標示不可用，不拋出例外', async () => {
    const loaded = await loadSettingsCenter(deps({ checkReadiness: () => Promise.reject(new Error('down')) }))
    expect(loaded.readiness).toBe('unavailable')
  })

  it('研究或版本分頁仍有下一頁時標示截斷', async () => {
    const loaded = await loadSettingsCenter(
      deps({ listResearches: () => Promise.resolve({ items: [research()], next_cursor: 'next' } satisfies ResearchPage) }),
    )
    expect(loaded.scope.truncated).toBe(true)
  })

  it('單一研究版本讀取失敗不影響其他已揭露內容', async () => {
    const loaded = await loadSettingsCenter(
      deps({
        listResearches: () =>
          Promise.resolve({
            items: [research(), research({ id: RESEARCH_ID_B, name: '第二研究' })],
            next_cursor: null,
          } satisfies ResearchPage),
        listResearchVersions: (researchId) =>
          researchId === RESEARCH_ID_B
            ? Promise.reject(new Error('boom'))
            : Promise.resolve({
                items: [researchVersion()],
                next_cursor: null,
              } satisfies ResearchVersionPage),
      }),
    )
    expect(loaded.versions).toHaveLength(1)
    expect(loaded.versions[0]?.id).toBe(VERSION_ID)
  })

  it('讀不到研究清單時以空集合回應，租戶識別為空', async () => {
    const loaded = await loadSettingsCenter(deps({ listResearches: () => Promise.reject(new Error('offline')) }))
    expect(loaded.researches).toEqual([])
    expect(loaded.versions).toEqual([])
    expect(loaded.tenantIds).toEqual([])
  })
})

describe('系統與安全設定（SCREEN 39）', () => {
  it('固定 10 列，僅服務就緒、工作階段、租戶與讀取範圍可讀', async () => {
    const center = await loadSettingsCenter(deps())
    const rows = buildSecurityRows(center)
    expect(rows).toHaveLength(10)
    expect(rows.map((row) => row.key)).toEqual([
      'readiness',
      'session',
      'tenants',
      'scope',
      'roles',
      'keys',
      'mfa',
      'password',
      'audit',
      'encryption',
    ])
    const readiness = rows[0]
    expect(readiness?.value).toBe('已就緒')
    expect(readiness?.tone).toBe('good')
    expect(rows.filter((row) => row.value === SETTINGS_UNKNOWN)).toHaveLength(6)
    expect(summarizeSecurity(rows)).toEqual({ total: 10, disclosed: 4, unknown: 6 })
  })

  it('服務異常時就緒列標示異常', async () => {
    const center = await loadSettingsCenter(deps({ checkReadiness: () => Promise.resolve('unavailable') }))
    const readiness = buildSecurityRows(center)[0]
    expect(readiness?.value).toBe('異常')
    expect(readiness?.tone).toBe('bad')
  })

  it('沒有租戶識別時該列標示未取得', async () => {
    const center = await loadSettingsCenter(deps({ listResearches: () => Promise.reject(new Error('offline')) }))
    const tenants = buildSecurityRows(center).find((row) => row.key === 'tenants')
    expect(tenants?.value).toBe(SETTINGS_UNKNOWN)
    expect(tenants?.tone).toBe('warn')
  })

  it('關鍵字篩選比對設定名稱、值與來源', async () => {
    const rows = buildSecurityRows(await loadSettingsCenter(deps()))
    expect(filterSecurityRows(rows, '金鑰')).toHaveLength(1)
    expect(filterSecurityRows(rows, 'health')).toHaveLength(1)
    expect(filterSecurityRows(rows, '沒有這個')).toHaveLength(0)
    expect(filterSecurityRows(rows, '  ')).toHaveLength(10)
  })
})

describe('研究策略設定（SCREEN 40）', () => {
  it('投影版本已固定的評估政策、切分、預算與研究域', async () => {
    const rows = buildStrategyRows(await loadSettingsCenter(deps()))
    const row = rows[0]
    expect(row?.versionId).toBe(VERSION_ID)
    expect(row?.researchName).toBe('sin 週期研究')
    expect(row?.purposeLabel).toBe('描述')
    expect(row?.policyVersion).toBe('2.0')
    expect(row?.policyHash).toBe(SHA_A)
    expect(row?.metricVersion).toBe('2.0')
    expect(row?.errorModelLabel).toBe('精確')
    expect(row?.comparisonMethodLabel).toBe('同分布配對重抽樣')
    expect(row?.baselineLabel).toBe('零')
    expect(row?.bootstrapReplicates).toBe(1000)
    expect(row?.bootstrapSeed).toBe(7)
    expect(row?.practicalMarginRatio).toBe('0.05')
    expect(row?.splitKindLabel).toBe('獨立同分布列')
    expect(row?.fitRows).toBe(2)
    expect(row?.developmentRows).toBe(1)
    expect(row?.finalTestRows).toBe(1)
    expect(row?.sealedFinalTest).toBe(true)
    expect(row?.budgetCpuSeconds).toBe(60)
    expect(row?.budgetGpuSeconds).toBe(10)
    expect(row?.budgetTokens).toBe(1000)
    expect(row?.domainCount).toBe(2)
  })

  it('策略名稱與治理規則一律未取得', async () => {
    const rows = buildStrategyRows(await loadSettingsCenter(deps()))
    expect(rows[0]?.strategyName).toBe(SETTINGS_UNKNOWN)
    expect(rows[0]?.governanceRules).toBe(SETTINGS_UNKNOWN)
  })

  it('版本無法對應研究時名稱退回未取得', async () => {
    const rows = buildStrategyRows(
      await loadSettingsCenter(
        deps({
          listResearchVersions: () =>
            Promise.resolve({
              items: [researchVersion({ research_id: RESEARCH_ID_B })],
              next_cursor: null,
            } satisfies ResearchVersionPage),
        }),
      ),
    )
    expect(rows[0]?.researchName).toBe(SETTINGS_UNKNOWN)
  })

  it('摘要加總版本、已就緒、封存與研究域端點', async () => {
    const center = await loadSettingsCenter(
      deps({
        listResearchVersions: () =>
          Promise.resolve({
            items: [
              researchVersion(),
              researchVersion({
                id: VERSION_ID_B,
                research_id: RESEARCH_ID_B,
                status: 'DRAFT',
                evaluation_policy_hash: SHA_B,
                observation_split: { ...OBSERVATION_SPLIT, sealed_final_test: false },
                domain: [],
              }),
            ],
            next_cursor: null,
          } satisfies ResearchVersionPage),
      }),
    )
    expect(summarizeStrategy(buildStrategyRows(center))).toEqual({
      versions: 2,
      ready: 1,
      sealed: 1,
      domainIntervals: 2,
    })
  })

  it('關鍵字篩選比對研究名稱、版本 ID、政策版本與指紋', async () => {
    const rows = buildStrategyRows(await loadSettingsCenter(deps()))
    expect(filterStrategyRows(rows, 'sin')).toHaveLength(1)
    expect(filterStrategyRows(rows, VERSION_ID)).toHaveLength(1)
    expect(filterStrategyRows(rows, '2.0')).toHaveLength(1)
    expect(filterStrategyRows(rows, SHA_A)).toHaveLength(1)
    expect(filterStrategyRows(rows, '沒有這個')).toHaveLength(0)
  })
})

describe('讀取範圍常數', () => {
  it('讀取上限固定，供畫面標示統計範圍', () => {
    expect(RESEARCHES_READ).toBe(12)
    expect(RECENT_VERSIONS_READ).toBe(12)
    expect(SETTINGS_UNKNOWN).toBe('未取得')
  })
})
