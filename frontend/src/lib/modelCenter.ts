/**
 * 模型模組（SSOT 32–35：Ollama 模型管理／模型路由／模型能力評估／Token 與儲存）共用推導層。
 *
 * 後端沒有模型 registry、路由策略、基準測試或儲存配額端點，因此這一層只從既有契約實體
 * （研究、研究版本、任務，以及任務與版本的預算用量）推導；模型名稱、上下文長度、模型版本、
 * 路由策略、基準分數、事件保存與壓縮留存等未揭露欄位一律標示「未取得」，不以 0 或推測值代替。
 */
import type { BudgetUsage, Run, RunStatus, RunType } from '../api/runs'
import type {
  Research,
  ResearchPage,
  ResearchVersion,
  ResearchVersionPage,
  ResearchVersionStatus,
  RunPage,
} from '../api/research'

/** 後端未回報的欄位一律顯示這個字串，不以 0 或推測值代替。 */
export const MODEL_UNKNOWN = '未取得'

/** 讀取範圍；後端沒有全域端點，所有統計都只涵蓋實際讀到的頁面。 */
export const RESEARCHES_READ = 12
export const VERSIONS_PER_RESEARCH = 5
export const RECENT_VERSIONS_READ = 12
export const RUNS_PER_VERSION = 8
export const RECENT_RUNS_READ = 16

/** 模型任務類別：由任務型別對照；後端未宣告模型與路由策略。 */
export const TASK_CLASS_LABELS: Record<RunType, string> = {
  INGEST: '資料匯入',
  PROFILE: '資料剖析',
  SEARCH: '公式搜尋',
  FIT: '參數擬合',
  VALIDATE: '驗證評估',
}

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  QUEUED: '排隊中',
  RUNNING: '執行中',
  CANCEL_REQUESTED: '取消中',
  SUCCEEDED: '已完成',
  FAILED: '失敗',
  CANCELLED: '已取消',
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

export interface ModelRunEntry {
  run: Run
  research: Research | null
  version: ResearchVersion | null
}

export interface ModelScope {
  researchesRead: number
  versionsRead: number
  runsRead: number
  truncated: boolean
}

export interface ModelCenter {
  researches: Research[]
  versions: ResearchVersion[]
  runs: ModelRunEntry[]
  scope: ModelScope
}

export interface ModelDeps {
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
}

function desc(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? 1 : -1
}

function takeRecent<T extends { created_at: string }>(rows: T[], limit: number): T[] {
  return [...rows].sort((left, right) => desc(left.created_at, right.created_at)).slice(0, limit)
}

async function safe<T>(task: Promise<T>, fallback: T): Promise<T> {
  try {
    return await task
  } catch {
    return fallback
  }
}

/** 只加總已揭露值；全部未揭露時回 null，由畫面顯示「未取得」而不是 0。 */
export function sumDisclosed(values: (number | null)[]): number | null {
  const disclosed = values.filter((value): value is number => value !== null)
  if (disclosed.length === 0) return null
  return disclosed.reduce((total, value) => total + value, 0)
}

/** 只平均已揭露值；沒有可平均的值時回 null。 */
export function averageDisclosed(values: (number | null)[]): number | null {
  const total = sumDisclosed(values)
  if (total === null) return null
  const count = values.filter((value) => value !== null).length
  return total / count
}

/** 只取已揭露值的最大者；沒有可比較的值時回 null。 */
export function maxDisclosed(values: (number | null)[]): number | null {
  const disclosed = values.filter((value): value is number => value !== null)
  if (disclosed.length === 0) return null
  return disclosed.reduce((best, value) => (value > best ? value : best), disclosed[0] ?? 0)
}

export async function loadModelCenter(deps: ModelDeps): Promise<ModelCenter> {
  const researchPage = await safe(deps.listResearches(RESEARCHES_READ), {
    items: [],
    next_cursor: null,
  } satisfies ResearchPage)
  const researches = researchPage.items

  const versionEntries = await Promise.all(
    researches.map(async (research) =>
      [
        research.id,
        (
          await safe(deps.listResearchVersions(research.id, VERSIONS_PER_RESEARCH), {
            items: [],
            next_cursor: null,
          } satisfies ResearchVersionPage)
        ).items,
      ] as const,
    ),
  )
  const recentVersions = takeRecent(
    versionEntries.flatMap(([, items]) => items),
    RECENT_VERSIONS_READ,
  )

  const runPages = await Promise.all(
    recentVersions.map(async (version) =>
      (
        await safe(deps.listResearchVersionRuns(version.id, RUNS_PER_VERSION), {
          items: [],
          next_cursor: null,
        } satisfies RunPage)
      ).items,
    ),
  )

  const runs: ModelRunEntry[] = []
  for (const run of takeRecent(runPages.flat(), RECENT_RUNS_READ)) {
    const version = recentVersions.find((row) => row.id === run.research_version_id) ?? null
    runs.push({
      run,
      version,
      research: version === null ? null : researches.find((row) => row.id === version.research_id) ?? null,
    })
  }
  runs.sort((left, right) => desc(left.run.created_at, right.run.created_at))

  const truncated =
    researchPage.next_cursor !== null ||
    versionEntries.some(([, items]) => items.length >= VERSIONS_PER_RESEARCH) ||
    runPages.some((items) => items.length >= RUNS_PER_VERSION)

  return {
    researches,
    versions: recentVersions,
    runs,
    scope: {
      researchesRead: researches.length,
      versionsRead: recentVersions.length,
      runsRead: runs.length,
      truncated,
    },
  }
}

// ---------------------------------------------------------------------------
// Ollama 模型管理（SSOT 32）：模型載入、上下文、版本與資源
// ---------------------------------------------------------------------------

/** 後端唯一揭露的資源面：任務與版本的預算用量。未揭露時各欄為 null。 */
export interface ModelResourceUsage {
  cpuSeconds: number | null
  gpuSeconds: number | null
  tokens: number | null
  peakMemoryBytes: number | null
  elapsedWallSeconds: number | null
  candidatesGenerated: number | null
  candidatesAccepted: number | null
}

const EMPTY_RESOURCE: ModelResourceUsage = {
  cpuSeconds: null,
  gpuSeconds: null,
  tokens: null,
  peakMemoryBytes: null,
  elapsedWallSeconds: null,
  candidatesGenerated: null,
  candidatesAccepted: null,
}

/** 任務的預算用量是選填欄位；缺席代表後端未揭露，不落回 0。 */
export function resourceFrom(usage: BudgetUsage | undefined | null): ModelResourceUsage {
  if (usage === undefined || usage === null) return { ...EMPTY_RESOURCE }
  return {
    cpuSeconds: usage.cpu_seconds,
    gpuSeconds: usage.gpu_seconds,
    tokens: usage.tokens,
    peakMemoryBytes: usage.peak_memory_bytes,
    elapsedWallSeconds: usage.elapsed_wall_seconds,
    candidatesGenerated: usage.candidates_generated,
    candidatesAccepted: usage.candidates_accepted,
  }
}

export interface ModelLoadRow {
  runId: string
  taskClass: RunType
  taskLabel: string
  researchId: string | null
  researchName: string
  versionId: string | null
  status: RunStatus
  /** 後端未揭露模型身分、上下文長度與模型版本。 */
  modelName: string
  contextWindow: string
  modelVersion: string
  resource: ModelResourceUsage
  createdAt: string
}

/** 模型載入對象只由已讀取的任務推導；模型名稱與上下文長度後端未揭露，一律「未取得」。 */
export function buildModelLoads(center: ModelCenter): ModelLoadRow[] {
  return center.runs.map((entry) => ({
    runId: entry.run.id,
    taskClass: entry.run.type,
    taskLabel: TASK_CLASS_LABELS[entry.run.type],
    researchId: entry.research?.id ?? null,
    researchName: entry.research?.name ?? '未命名研究',
    versionId: entry.version?.id ?? null,
    status: entry.run.status,
    modelName: MODEL_UNKNOWN,
    contextWindow: MODEL_UNKNOWN,
    modelVersion: MODEL_UNKNOWN,
    resource: resourceFrom(entry.run.budget_usage),
    createdAt: entry.run.created_at,
  }))
}

export interface ModelResourceSummary {
  cpuSeconds: number | null
  gpuSeconds: number | null
  tokens: number | null
  peakMemoryBytes: number | null
  elapsedWallSeconds: number | null
  /** 有揭露資源用量的任務數；未揭露的任務不計入任何加總。 */
  disclosed: number
  total: number
}

/** 資源加總只涵蓋已揭露值；完全未揭露的面向回 null，由畫面顯示「未取得」。 */
export function summarizeModelResources(rows: ModelLoadRow[]): ModelResourceSummary {
  return {
    cpuSeconds: sumDisclosed(rows.map((row) => row.resource.cpuSeconds)),
    gpuSeconds: sumDisclosed(rows.map((row) => row.resource.gpuSeconds)),
    tokens: sumDisclosed(rows.map((row) => row.resource.tokens)),
    peakMemoryBytes: maxDisclosed(rows.map((row) => row.resource.peakMemoryBytes)),
    elapsedWallSeconds: sumDisclosed(rows.map((row) => row.resource.elapsedWallSeconds)),
    disclosed: rows.filter((row) => row.resource.tokens !== null || row.resource.elapsedWallSeconds !== null).length,
    total: rows.length,
  }
}

export function filterModelLoads(rows: ModelLoadRow[], keyword: string): ModelLoadRow[] {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return rows
  return rows.filter(
    (row) =>
      row.researchName.toLowerCase().includes(needle) ||
      row.runId.toLowerCase().includes(needle) ||
      row.taskLabel.toLowerCase().includes(needle),
  )
}

// ---------------------------------------------------------------------------
// 模型路由（SSOT 33）：任務分類、候選模型與路由策略
// ---------------------------------------------------------------------------

export interface TaskClassRow {
  taskClass: RunType
  label: string
  runCount: number
  activeCount: number
  failedCount: number
  /** 後端未揭露候選模型。 */
  candidateModels: string
  /** 後端未揭露路由策略。 */
  routingStrategy: string
  tokens: number | null
  elapsedWallSeconds: number | null
}

/** 任務分類只列實際讀到任務的類別；未讀到的類別不補造，候選模型與路由策略一律「未取得」。 */
export function buildTaskClasses(center: ModelCenter): TaskClassRow[] {
  const order: RunType[] = ['INGEST', 'PROFILE', 'SEARCH', 'FIT', 'VALIDATE']
  const rows: TaskClassRow[] = []
  for (const taskClass of order) {
    const entries = center.runs.filter((entry) => entry.run.type === taskClass)
    if (entries.length === 0) continue
    const resources = entries.map((entry) => resourceFrom(entry.run.budget_usage))
    rows.push({
      taskClass,
      label: TASK_CLASS_LABELS[taskClass],
      runCount: entries.length,
      activeCount: entries.filter((entry) => entry.run.status === 'RUNNING' || entry.run.status === 'QUEUED').length,
      failedCount: entries.filter((entry) => entry.run.status === 'FAILED').length,
      candidateModels: MODEL_UNKNOWN,
      routingStrategy: MODEL_UNKNOWN,
      tokens: sumDisclosed(resources.map((resource) => resource.tokens)),
      elapsedWallSeconds: sumDisclosed(resources.map((resource) => resource.elapsedWallSeconds)),
    })
  }
  return rows
}

export function summarizeTaskClasses(rows: TaskClassRow[]): {
  classes: number
  runs: number
  active: number
  failed: number
} {
  return {
    classes: rows.length,
    runs: rows.reduce((total, row) => total + row.runCount, 0),
    active: rows.reduce((total, row) => total + row.activeCount, 0),
    failed: rows.reduce((total, row) => total + row.failedCount, 0),
  }
}

// ---------------------------------------------------------------------------
// 模型能力評估（SSOT 34）：數學任務基準、延遲與成本
// ---------------------------------------------------------------------------

export interface CapabilityRow {
  taskClass: RunType
  label: string
  /** 後端未提供基準分數。 */
  benchmarkScore: string
  sampleCount: number
  successCount: number
  /** 延遲與成本由已揭露的預算用量推導；無資料時為 null。 */
  averageWallSeconds: number | null
  maxWallSeconds: number | null
  tokens: number | null
  /** 後端未揭露候選模型。 */
  candidateModel: string
}

/** 基準分數需後端基準端點，一律「未取得」；延遲與成本只由已揭露用量推導。 */
export function buildCapabilityRows(center: ModelCenter): CapabilityRow[] {
  return buildTaskClasses(center).map((row) => {
    const entries = center.runs.filter((entry) => entry.run.type === row.taskClass)
    const resources = entries.map((entry) => resourceFrom(entry.run.budget_usage))
    return {
      taskClass: row.taskClass,
      label: row.label,
      benchmarkScore: MODEL_UNKNOWN,
      sampleCount: entries.length,
      successCount: entries.filter((entry) => entry.run.status === 'SUCCEEDED').length,
      averageWallSeconds: averageDisclosed(resources.map((resource) => resource.elapsedWallSeconds)),
      maxWallSeconds: maxDisclosed(resources.map((resource) => resource.elapsedWallSeconds)),
      tokens: sumDisclosed(resources.map((resource) => resource.tokens)),
      candidateModel: MODEL_UNKNOWN,
    }
  })
}

export function summarizeCapability(rows: CapabilityRow[]): {
  classes: number
  samples: number
  successes: number
  tokens: number | null
  wallSeconds: number | null
} {
  return {
    classes: rows.length,
    samples: rows.reduce((total, row) => total + row.sampleCount, 0),
    successes: rows.reduce((total, row) => total + row.successCount, 0),
    tokens: sumDisclosed(rows.map((row) => row.tokens)),
    wallSeconds: sumDisclosed(rows.map((row) => row.averageWallSeconds)),
  }
}

// ---------------------------------------------------------------------------
// Token 與儲存（SSOT 35）：事件保存、壓縮、留存及成本
// ---------------------------------------------------------------------------

export interface StorageRow {
  versionId: string
  researchId: string | null
  researchName: string
  versionStatus: ResearchVersionStatus
  /** 版本宣告的預算上限與累計用量，皆為後端已揭露欄位。 */
  tokenLimit: number
  usedTokens: number
  usedCpuSeconds: number
  usedGpuSeconds: number
  usedWallSeconds: number
  peakMemoryBytes: number
  candidatesGenerated: number
  candidatesAccepted: number
  overTokenLimit: boolean
  /** 後端未揭露事件保存、壓縮與留存政策。 */
  eventRetention: string
  compression: string
  storageQuota: string
  createdAt: string
}

/** Token 與成本只由版本宣告的預算上限與累計用量推導；留存、壓縮與儲存配額後端未揭露。 */
export function buildStorageRows(center: ModelCenter): StorageRow[] {
  return center.versions.map((version) => {
    const usage = version.research_budget_usage
    return {
      versionId: version.id,
      researchId: version.research_id,
      researchName: center.researches.find((row) => row.id === version.research_id)?.name ?? '未命名研究',
      versionStatus: version.status,
      tokenLimit: version.budget.tokens,
      usedTokens: usage.tokens,
      usedCpuSeconds: usage.cpu_seconds,
      usedGpuSeconds: usage.gpu_seconds,
      usedWallSeconds: usage.elapsed_wall_seconds,
      peakMemoryBytes: usage.peak_memory_bytes,
      candidatesGenerated: usage.candidates_generated,
      candidatesAccepted: usage.candidates_accepted,
      overTokenLimit: usage.tokens > version.budget.tokens,
      eventRetention: MODEL_UNKNOWN,
      compression: MODEL_UNKNOWN,
      storageQuota: MODEL_UNKNOWN,
      createdAt: version.created_at,
    }
  })
}

export function summarizeStorage(rows: StorageRow[]): {
  versions: number
  tokenLimit: number
  usedTokens: number
  usedCpuSeconds: number
  usedGpuSeconds: number
  peakMemoryBytes: number | null
  overTokenLimit: number
} {
  return {
    versions: rows.length,
    tokenLimit: rows.reduce((total, row) => total + row.tokenLimit, 0),
    usedTokens: rows.reduce((total, row) => total + row.usedTokens, 0),
    usedCpuSeconds: rows.reduce((total, row) => total + row.usedCpuSeconds, 0),
    usedGpuSeconds: rows.reduce((total, row) => total + row.usedGpuSeconds, 0),
    peakMemoryBytes: maxDisclosed(rows.map((row) => row.peakMemoryBytes)),
    overTokenLimit: rows.filter((row) => row.overTokenLimit).length,
  }
}

export function filterStorageRows(rows: StorageRow[], keyword: string): StorageRow[] {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return rows
  return rows.filter(
    (row) =>
      row.researchName.toLowerCase().includes(needle) || row.versionId.toLowerCase().includes(needle),
  )
}
