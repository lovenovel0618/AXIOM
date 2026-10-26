/**
 * 設定模組（SSOT 39–40：系統與安全設定／研究策略設定）共用推導層。
 *
 * 後端沒有角色權限、金鑰、稽核留存或治理政策端點，因此安全設定頁只呈現確實可讀的
 * 服務就緒、租戶識別、工作階段機制與讀取範圍，其餘一律標示「未取得」；研究策略設定
 * 頁則只投影研究版本已固定的評估政策、切分宣告、預算與研究域，策略名稱與治理規則
 * 後端未揭露，一律「未取得」。
 */
import type { HealthStatus } from '../health'
import type {
  Baseline,
  ComparisonMethod,
  ErrorModel,
  Research,
  ResearchPage,
  ResearchPurpose,
  ResearchVersion,
  ResearchVersionPage,
  ResearchVersionStatus,
  SplitKind,
} from '../api/research'

/** 後端未回報的欄位一律顯示這個字串，不以 0 或推測值代替。 */
export const SETTINGS_UNKNOWN = '未取得'

export const PURPOSE_LABELS: Record<ResearchPurpose, string> = {
  DESCRIPTION: '描述',
  PREDICTION: '預測',
  MECHANISM: '機制',
}

export const VERSION_STATUS_LABELS: Record<ResearchVersionStatus, string> = {
  DRAFT: '草稿',
  VALIDATING: '驗證中',
  READY: '就緒',
  QUEUED: '排隊中',
  RUNNING: '執行中',
  FAILED: '失敗',
  CANCELLED: '已取消',
}

export const SPLIT_KIND_LABELS: Record<SplitKind, string> = {
  IID_ROWS: '獨立同分布列',
  GROUPED_ROWS: '分組列',
  TIME_ORDERED: '時間序',
  EXPLICIT: '明確列舉',
}

export const ERROR_MODEL_LABELS: Record<ErrorModel, string> = {
  EXACT: '精確',
  ABSOLUTE_BOUND: '絕對界限',
  UNSPECIFIED: '未指定',
}

export const COMPARISON_METHOD_LABELS: Record<ComparisonMethod, string> = {
  IID_PAIRED_BOOTSTRAP: '同分布配對重抽樣',
  BLOCK_BOOTSTRAP: '區塊重抽樣',
  NONE: '無',
}

export const BASELINE_LABELS: Record<Baseline, string> = {
  ZERO: '零',
  FIT_MEAN: '擬合均值',
}

/** 讀取範圍；後端沒有全域端點，所有統計都只涵蓋實際讀到的頁面。 */
export const RESEARCHES_READ = 12
export const VERSIONS_PER_RESEARCH = 5
export const RECENT_VERSIONS_READ = 12

export interface SettingsScope {
  researchesRead: number
  versionsRead: number
  truncated: boolean
}

export interface SettingsCenter {
  readiness: HealthStatus
  researches: Research[]
  versions: ResearchVersion[]
  /** 由已讀取實體推導的租戶識別；後端沒有租戶設定端點。 */
  tenantIds: string[]
  scope: SettingsScope
}

export interface SettingsDeps {
  checkReadiness: () => Promise<HealthStatus>
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
}

async function safe<T>(task: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await task()
  } catch {
    return fallback
  }
}

function desc(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? 1 : -1
}

export async function loadSettingsCenter(deps: SettingsDeps): Promise<SettingsCenter> {
  let truncated = false
  const readiness = await safe(() => deps.checkReadiness(), 'unavailable' satisfies HealthStatus)
  const researchPage = await safe(
    () => deps.listResearches(RESEARCHES_READ),
    { items: [], next_cursor: null } satisfies ResearchPage,
  )
  if (researchPage.next_cursor !== null) truncated = true

  const versionGroups = await Promise.all(
    researchPage.items.map(async (research) => {
      const page = await safe(
        () => deps.listResearchVersions(research.id, VERSIONS_PER_RESEARCH),
        { items: [], next_cursor: null } satisfies ResearchVersionPage,
      )
      if (page.next_cursor !== null) truncated = true
      return page.items
    }),
  )

  const allVersions = versionGroups.flat().sort((a, b) => desc(a.created_at, b.created_at))
  if (allVersions.length > RECENT_VERSIONS_READ) truncated = true
  const versions = allVersions.slice(0, RECENT_VERSIONS_READ)

  const tenantIds = [
    ...new Set([...researchPage.items.map((research) => research.tenant_id), ...versions.map((version) => version.tenant_id)]),
  ].sort()

  return {
    readiness,
    researches: researchPage.items,
    versions,
    tenantIds,
    scope: {
      researchesRead: researchPage.items.length,
      versionsRead: versions.length,
      truncated,
    },
  }
}

/** SCREEN 39｜系統與安全設定：每列都必須指出可追溯來源，沒有來源就是「未取得」。 */
export interface SecurityRow {
  key: string
  label: string
  value: string
  source: string
  tone: 'good' | 'warn' | 'bad' | 'neutral'
}

export function buildSecurityRows(center: SettingsCenter): SecurityRow[] {
  const rows: SecurityRow[] = [
    {
      key: 'readiness',
      label: '服務就緒狀態',
      value: center.readiness === 'ready' ? '已就緒' : '異常',
      source: 'GET /health/ready/',
      tone: center.readiness === 'ready' ? 'good' : 'bad',
    },
    {
      key: 'session',
      label: '工作階段機制',
      value: '同源 Session Cookie 與 CSRF 雙提交',
      source: 'POST /auth/login、POST /auth/logout',
      tone: 'neutral',
    },
    {
      key: 'tenants',
      label: '已讀取租戶識別',
      value: center.tenantIds.length === 0 ? SETTINGS_UNKNOWN : center.tenantIds.join('、'),
      source: 'GET /api/v2/researches、GET /api/v2/researches/{id}/versions',
      tone: center.tenantIds.length === 0 ? 'warn' : 'neutral',
    },
    {
      key: 'scope',
      label: '授權讀取範圍',
      value: `研究 ${String(center.scope.researchesRead)} 筆／版本 ${String(center.scope.versionsRead)} 筆${center.scope.truncated ? '（後端仍有未讀取頁面）' : ''}`,
      source: '本頁實際讀取的頁面',
      tone: center.scope.truncated ? 'warn' : 'neutral',
    },
    {
      key: 'roles',
      label: '角色與權限矩陣',
      value: SETTINGS_UNKNOWN,
      source: '後端沒有角色或權限端點',
      tone: 'neutral',
    },
    {
      key: 'keys',
      label: '存取金鑰與 Token 效期',
      value: SETTINGS_UNKNOWN,
      source: '後端沒有金鑰或 Token 管理端點',
      tone: 'neutral',
    },
    {
      key: 'mfa',
      label: '多因素驗證',
      value: SETTINGS_UNKNOWN,
      source: '後端沒有多因素驗證端點',
      tone: 'neutral',
    },
    {
      key: 'password',
      label: '密碼與帳號政策',
      value: SETTINGS_UNKNOWN,
      source: '後端沒有帳號政策端點',
      tone: 'neutral',
    },
    {
      key: 'audit',
      label: '稽核日誌與留存',
      value: SETTINGS_UNKNOWN,
      source: '後端沒有稽核或留存端點',
      tone: 'neutral',
    },
    {
      key: 'encryption',
      label: '資料加密與隔離政策',
      value: SETTINGS_UNKNOWN,
      source: '後端沒有加密政策端點',
      tone: 'neutral',
    },
  ]
  return rows
}

export interface SecuritySummary {
  total: number
  disclosed: number
  unknown: number
}

export function summarizeSecurity(rows: SecurityRow[]): SecuritySummary {
  const unknown = rows.filter((row) => row.value === SETTINGS_UNKNOWN).length
  return { total: rows.length, disclosed: rows.length - unknown, unknown }
}

export function filterSecurityRows(rows: SecurityRow[], keyword: string): SecurityRow[] {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return rows
  return rows.filter((row) => `${row.label} ${row.value} ${row.source}`.toLowerCase().includes(needle))
}

/** SCREEN 40｜研究策略設定：只投影版本已固定的策略欄位。 */
export interface StrategyRow {
  versionId: string
  researchId: string
  researchName: string
  versionStatus: ResearchVersionStatus
  purposeLabel: string
  policyVersion: string
  policyHash: string
  metricVersion: string
  errorModelLabel: string
  comparisonMethodLabel: string
  baselineLabel: string
  bootstrapReplicates: number
  bootstrapSeed: number
  practicalMarginRatio: string
  splitKindLabel: string
  fitRows: number
  developmentRows: number
  finalTestRows: number
  sealedFinalTest: boolean
  budgetCpuSeconds: number
  budgetGpuSeconds: number
  budgetTokens: number
  domainCount: number
  /** 策略名稱、預設範本與治理規則後端未揭露。 */
  strategyName: string
  governanceRules: string
  createdAt: string
}

export function buildStrategyRows(center: SettingsCenter): StrategyRow[] {
  const researchById = new Map(center.researches.map((research) => [research.id, research]))
  const rows = center.versions.map((version) => {
    const split = version.observation_split
    const policy = version.evaluation_policy
    return {
      versionId: version.id,
      researchId: version.research_id,
      researchName: researchById.get(version.research_id)?.name ?? SETTINGS_UNKNOWN,
      versionStatus: version.status,
      purposeLabel: PURPOSE_LABELS[version.purpose],
      policyVersion: policy.policy_version,
      policyHash: version.evaluation_policy_hash,
      metricVersion: policy.metric_version,
      errorModelLabel: ERROR_MODEL_LABELS[policy.error_model],
      comparisonMethodLabel: COMPARISON_METHOD_LABELS[policy.comparison_method],
      baselineLabel: BASELINE_LABELS[policy.baseline],
      bootstrapReplicates: policy.bootstrap_replicates,
      bootstrapSeed: policy.bootstrap_seed,
      practicalMarginRatio: policy.practical_margin_ratio,
      splitKindLabel: SPLIT_KIND_LABELS[split.kind],
      fitRows: split.fit.length,
      developmentRows: split.development.length,
      finalTestRows: split.final_test.length,
      sealedFinalTest: split.sealed_final_test,
      budgetCpuSeconds: version.budget.cpu_seconds,
      budgetGpuSeconds: version.budget.gpu_seconds,
      budgetTokens: version.budget.tokens,
      domainCount: version.domain.length,
      strategyName: SETTINGS_UNKNOWN,
      governanceRules: SETTINGS_UNKNOWN,
      createdAt: version.created_at,
    } satisfies StrategyRow
  })
  return rows.sort((a, b) => desc(a.createdAt, b.createdAt))
}

export interface StrategySummary {
  versions: number
  ready: number
  sealed: number
  domainIntervals: number
}

export function summarizeStrategy(rows: StrategyRow[]): StrategySummary {
  const summary: StrategySummary = { versions: rows.length, ready: 0, sealed: 0, domainIntervals: 0 }
  for (const row of rows) {
    if (row.versionStatus === 'READY') summary.ready += 1
    if (row.sealedFinalTest) summary.sealed += 1
    summary.domainIntervals += row.domainCount
  }
  return summary
}

export function filterStrategyRows(rows: StrategyRow[], keyword: string): StrategyRow[] {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return rows
  return rows.filter((row) =>
    `${row.researchName} ${row.versionId} ${row.policyVersion} ${row.policyHash} ${row.splitKindLabel}`
      .toLowerCase()
      .includes(needle),
  )
}
