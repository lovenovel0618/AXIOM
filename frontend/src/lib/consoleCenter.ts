/**
 * 總覽控制台的共用推導：活動中心、待處理事件與資源監控只使用後端已揭露欄位。
 *
 * 後端沒有全域任務端點，因此快照由「研究 → 版本 → 任務」與「資料集 → 版本／匯入任務」逐層拉取後彙整；
 * 未提供即時 CPU／GPU／RAM 觀測端點，該區塊一律回報「未取得」，不以推測填補。
 */
import type { Dataset, DatasetPage, DatasetRunPage, DatasetVersion, VersionPage } from '../api/datasets'
import type { Research, ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../api/research'
import type { BudgetUsage, Run } from '../api/runs'
import type { HealthStatus } from '../health'

export const RESEARCH_LIMIT = 12
export const VERSIONS_PER_RESEARCH = 5
export const RUNS_PER_VERSION = 8
export const DATASET_LIMIT = 12
export const VERSIONS_PER_DATASET = 5
export const DATASET_RUNS_PER_DATASET = 5
export const UNKNOWN = '未取得'

const ACTIVE_RUN_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'])
const ACTIVE_VERSION_STATUSES = new Set(['VALIDATING', 'READY', 'QUEUED', 'RUNNING'])
const TYPE_ORDER = ['INGEST', 'PROFILE', 'SEARCH', 'FIT', 'VALIDATE']

const STOP_REASON_LABELS: Record<string, string> = {
  BUDGET_EXHAUSTED: '預算耗盡，後端停止本次任務。',
  NO_IMPROVEMENT: '連續迭代沒有改善，後端停止本次任務。',
  NUMERICAL_FAILURE: '數值失敗，後端停止本次任務。',
  AMBIGUOUS: '多候選無法區辨，後端以歧義停止。',
  USER_CANCELLED: '使用者取消。',
  COMPLETED: '任務完成。',
  DEPENDENCY_FAILURE: '依賴故障導致停止。',
  NO_VALID_CANDIDATE: '沒有合法候選，後端停止並回報證據不足。',
}

const OUTCOME_LABELS: Record<string, string> = {
  SUPPORTED: '支持',
  AMBIGUOUS: '無法區辨',
  INSUFFICIENT_EVIDENCE: '證據不足（拒答）',
  FALSIFIED: '被否證',
}

/** 跨來源的任務投影；資料集匯入頁籤沒有預算欄位，因此一律留 null。 */
export interface ConsoleRun {
  id: string
  type: string
  status: string
  created_at: string
  datasetId: string | null
  researchVersionId: string | null
  researchId: string | null
  stopReason: string | null
  outcomeStatus: string | null
  budgetUsage: BudgetUsage | null
}

export interface ConsoleSnapshot {
  readiness: HealthStatus
  researches: Research[]
  researchVersionsByResearch: Record<string, ResearchVersion[]>
  researchVersions: ResearchVersion[]
  researchRuns: ConsoleRun[]
  datasets: Dataset[]
  datasetVersionsByDataset: Record<string, DatasetVersion[]>
  datasetRuns: ConsoleRun[]
}

export interface ConsoleDeps {
  checkReadiness: () => Promise<HealthStatus>
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  listDatasets: (limit: number) => Promise<DatasetPage>
  listVersions: (datasetId: string, limit: number) => Promise<VersionPage>
  listDatasetRuns: (datasetId: string, limit: number) => Promise<DatasetRunPage>
}

export interface ConsoleLink {
  name: string
  params: Record<string, string>
}

function desc(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? 1 : -1
}

function takeRecent<T extends { created_at: string }>(rows: T[], limit: number): T[] {
  return [...rows].sort((left, right) => desc(left.created_at, right.created_at)).slice(0, limit)
}

function latestVersion(rows: DatasetVersion[]): DatasetVersion | null {
  return takeRecent(rows, 1)[0] ?? null
}

async function safe<T>(task: Promise<T>, fallback: T): Promise<T> {
  try {
    return await task
  } catch {
    return fallback
  }
}

function fromRun(run: Run, researchId: string | null): ConsoleRun {
  return {
    id: run.id,
    type: run.type,
    status: run.status,
    created_at: run.created_at,
    datasetId: run.dataset_id,
    researchVersionId: run.research_version_id,
    researchId,
    stopReason: run.stop_reason ?? null,
    outcomeStatus: run.outcome_status ?? null,
    budgetUsage: run.budget_usage ?? null,
  }
}

export async function buildConsoleSnapshot(deps: ConsoleDeps): Promise<ConsoleSnapshot> {
  const [readiness, researchPage, datasetPage] = await Promise.all([
    safe(deps.checkReadiness(), 'unavailable' satisfies HealthStatus),
    safe(deps.listResearches(RESEARCH_LIMIT), { items: [], next_cursor: null } satisfies ResearchPage),
    safe(deps.listDatasets(DATASET_LIMIT), { items: [], next_cursor: null } satisfies DatasetPage),
  ])

  const researches = researchPage.items
  const datasets = datasetPage.items

  const versionEntries = await Promise.all(
    researches.map(async (research) => [
      research.id,
      (
        await safe(deps.listResearchVersions(research.id, VERSIONS_PER_RESEARCH), {
          items: [],
          next_cursor: null,
        } satisfies ResearchVersionPage)
      ).items,
    ] as const),
  )
  const researchVersionsByResearch: Record<string, ResearchVersion[]> = Object.fromEntries(versionEntries)
  const researchVersions = takeRecent(Object.values(researchVersionsByResearch).flat(), 12)

  const researchRunGroups = await Promise.all(
    researchVersions.map(async (version) => {
      const page = await safe(deps.listResearchVersionRuns(version.id, RUNS_PER_VERSION), {
        items: [],
        next_cursor: null,
      } satisfies RunPage)
      return page.items.map((run) => fromRun(run, version.research_id))
    }),
  )

  const datasetVersionEntries = await Promise.all(
    datasets.map(async (dataset) => [
      dataset.id,
      (
        await safe(deps.listVersions(dataset.id, VERSIONS_PER_DATASET), {
          items: [],
          next_cursor: null,
        } satisfies VersionPage)
      ).items,
    ] as const),
  )
  const datasetVersionsByDataset: Record<string, DatasetVersion[]> = Object.fromEntries(datasetVersionEntries)

  const datasetRunGroups = await Promise.all(
    datasets.map(async (dataset) => {
      const page = await safe(deps.listDatasetRuns(dataset.id, DATASET_RUNS_PER_DATASET), {
        items: [],
        next_cursor: null,
      } satisfies DatasetRunPage)
      return page.items.map<ConsoleRun>((run) => ({
        id: run.id,
        type: run.type,
        status: run.status,
        created_at: run.created_at,
        datasetId: run.dataset_id,
        researchVersionId: null,
        researchId: null,
        stopReason: null,
        outcomeStatus: null,
        budgetUsage: null,
      }))
    }),
  )

  return {
    readiness,
    researches,
    researchVersionsByResearch,
    researchVersions,
    researchRuns: researchRunGroups.flat(),
    datasets,
    datasetVersionsByDataset,
    datasetRuns: datasetRunGroups.flat(),
  }
}

/** 資料集最新版本以 `created_at` 反序決定，與其他頁面一致；讀不到時回 null。 */
export function latestDatasetVersionOf(snapshot: ConsoleSnapshot, datasetId: string): DatasetVersion | null {
  return latestVersion(snapshot.datasetVersionsByDataset[datasetId] ?? [])
}

export function allRuns(snapshot: ConsoleSnapshot): ConsoleRun[] {
  return takeRecent([...snapshot.researchRuns, ...snapshot.datasetRuns], Number.MAX_SAFE_INTEGER)
}

export function runLink(run: ConsoleRun): ConsoleLink {
  return { name: 'run', params: { id: run.id } }
}

function runSource(run: ConsoleRun): string {
  if (run.researchId !== null && run.researchVersionId !== null) {
    return `研究版本 ${run.researchVersionId}（研究 ${run.researchId}）`
  }
  if (run.datasetId !== null) return `資料集 ${run.datasetId}`
  return UNKNOWN
}

export interface TimelineEntry {
  at: string
  title: string
  detail: string
  badge: string
  status: string
  to: ConsoleLink
}

/** 活動時間軸：全部已讀取的任務依建立時間反序排列，並標明可追溯來源。 */
export function buildActivityTimeline(snapshot: ConsoleSnapshot, limit = 20): TimelineEntry[] {
  return allRuns(snapshot)
    .slice(0, limit)
    .map((run) => ({
      at: run.created_at,
      title: `${run.type}／${run.status}`,
      detail: `來源：${runSource(run)}`,
      badge: run.id,
      status: run.status,
      to: runLink(run),
    }))
}

export interface ActivityBucket {
  key: string
  count: number
}

export interface ActivityAnalysis {
  total: number
  byType: ActivityBucket[]
  byStatus: ActivityBucket[]
  active: number
}

/** 事件分析只統計實際讀到的任務編號，不補任何未讀取頁面的推估值。 */
export function buildActivityAnalysis(snapshot: ConsoleSnapshot): ActivityAnalysis {
  const runs = allRuns(snapshot)
  const typeCounts = new Map<string, number>()
  const statusCounts = new Map<string, number>()
  for (const run of runs) {
    typeCounts.set(run.type, (typeCounts.get(run.type) ?? 0) + 1)
    statusCounts.set(run.status, (statusCounts.get(run.status) ?? 0) + 1)
  }
  const typeKeys = [...TYPE_ORDER.filter((key) => typeCounts.has(key)), ...[...typeCounts.keys()].filter((key) => !TYPE_ORDER.includes(key)).sort()]
  const statusKeys = [...statusCounts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0])).map(([key]) => key)
  return {
    total: runs.length,
    byType: typeKeys.map((key) => ({ key, count: typeCounts.get(key) ?? 0 })),
    byStatus: statusKeys.map((key) => ({ key, count: statusCounts.get(key) ?? 0 })),
    active: runs.filter((run) => ACTIVE_RUN_STATUSES.has(run.status)).length,
  }
}

export type PendingPriority = '高' | '中' | '低'

export interface PendingItem {
  id: string
  priority: PendingPriority
  title: string
  source: string
  status: string
  reason: string
  action: string
  to: ConsoleLink | null
}

const PRIORITY_ORDER: Record<PendingPriority, number> = { 高: 0, 中: 1, 低: 2 }

/**
 * 待處理佇列只由後端狀態與停止理由推導；每一條都附可追溯來源與下一步，不以推測補上待辦。
 *
 * 人工決策（批准／駁回／要求補充證據）需不可竄改稽核事件，後端尚未提供該 API，
 * 因此本清單只呈現「需要人為判讀」的項目，不代替使用者決定。
 */
export function buildPendingQueue(snapshot: ConsoleSnapshot): PendingItem[] {
  const items: PendingItem[] = []
  const push = (item: PendingItem): void => {
    items.push(item)
  }

  for (const run of snapshot.researchRuns) {
    const link = runLink(run)
    const source = runSource(run)
    if (run.status === 'FAILED') {
      push({
        id: `${run.id}:failed`,
        priority: '高',
        title: `${run.type} 任務失敗`,
        source,
        status: '待決策',
        reason: run.stopReason === null ? `後端未揭露 stop_reason；${UNKNOWN}` : STOP_REASON_LABELS[run.stopReason] ?? run.stopReason,
        action: '開啟任務詳情，依已保留產物決定是否建立新研究版本或新任務。',
        to: link,
      })
    }
    if (run.status === 'CANCEL_REQUESTED') {
      push({
        id: `${run.id}:cancel`,
        priority: '中',
        title: `${run.type} 停止中`,
        source,
        status: '待確認',
        reason: '已送出取消，後端尚未確認停止；不假稱資源已釋放。',
        action: '留在任務詳情觀察終態事件，避免重複送出取消。',
        to: link,
      })
    }
    if (run.stopReason === 'BUDGET_EXHAUSTED') {
      push({
        id: `${run.id}:budget`,
        priority: '中',
        title: `${run.type} 預算耗盡`,
        source,
        status: '待確認',
        reason: '預算耗盡，後端停止本次任務。',
        action: '檢查研究版本預算用量後決定是否放大預算或另建版本。',
        to: link,
      })
    }
    if (run.outcomeStatus === 'AMBIGUOUS' || run.outcomeStatus === 'INSUFFICIENT_EVIDENCE') {
      push({
        id: `${run.id}:outcome`,
        priority: '中',
        title: `${run.type} ${OUTCOME_LABELS[run.outcomeStatus] ?? run.outcomeStatus}`,
        source,
        status: '待決策',
        reason: '後端未以「成功」掩蓋歧義或拒答；需人工決定是否另建研究分支。',
        action: '開啟任務詳情比對候選差異與適用域。',
        to: link,
      })
    }
  }

  for (const version of snapshot.researchVersions) {
    const searhes = snapshot.researchRuns.filter((run) => run.researchVersionId === version.id && run.type === 'SEARCH')
    if (version.status === 'VALIDATING') {
      push({
        id: `${version.id}:validating`,
        priority: '中',
        title: '語意驗證進行中',
        source: `研究版本 ${version.id}（研究 ${version.research_id}）`,
        status: '待確認',
        reason: '後端回報 VALIDATING；確認前不得以結果覆蓋既有研究事實。',
        action: '等待 PROFILE 終態事件後再決定下一步。',
        to: { name: 'research-workbench', params: { id: version.research_id } },
      })
    }
    if (version.status === 'READY' && searhes.length === 0) {
      push({
        id: `${version.id}:nosearch`,
        priority: '低',
        title: '尚無搜尋任務',
        source: `研究版本 ${version.id}（研究 ${version.research_id}）`,
        status: '待處理',
        reason: '狀態為 READY 且此頁尚未讀到任何 SEARCH 任務。',
        action: '回到研究工作台確認是否要建立 SEARCH 任務。',
        to: { name: 'research-workbench', params: { id: version.research_id } },
      })
    }
  }

  for (const dataset of snapshot.datasets) {
    const versions = snapshot.datasetVersionsByDataset[dataset.id] ?? []
    const latest = latestVersion(versions)
    const ingestFailures = snapshot.datasetRuns.filter((run) => run.datasetId === dataset.id && run.status === 'FAILED')
    for (const run of ingestFailures) {
      push({
        id: `${run.id}:ingest`,
        priority: '高',
        title: '匯入任務失敗',
        source: `資料集 ${dataset.id}（${dataset.name}）`,
        status: '待決策',
        reason: '匯入任務狀態為 FAILED；資料集匯入投影未揭露停止理由。',
        action: '開啟任務詳情確認診斷產物後重新匯入。',
        to: runLink(run),
      })
    }
    if (latest === null) {
      push({
        id: `${dataset.id}:noversion`,
        priority: '低',
        title: '尚無資料版本',
        source: `資料集 ${dataset.id}（${dataset.name}）`,
        status: '待處理',
        reason: '此頁尚未讀到任何資料版本；不代表資料集為空。',
        action: '前往資料集工作區上傳資料或確認匯入任務。',
        to: { name: 'data-upload', params: { id: dataset.id } },
      })
    } else if (latest.status !== 'AVAILABLE') {
      push({
        id: `${dataset.id}:unavailable`,
        priority: '中',
        title: '資料版本不可用',
        source: `資料集 ${dataset.id}（${dataset.name}）`,
        status: '待審核',
        reason: `最新資料版本 ${latest.id} 狀態為 ${latest.status}。`,
        action: '在資料集工作區檢核版本狀態，必要時重新上傳。',
        to: { name: 'data-quality', params: { id: dataset.id } },
      })
    }
  }

  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => PRIORITY_ORDER[left.item.priority] - PRIORITY_ORDER[right.item.priority] || left.index - right.index)
    .map((entry) => entry.item)
}

export interface ResourceUsageRow {
  runId: string
  type: string
  status: string
  created_at: string
  cpuSeconds: number | null
  gpuSeconds: number | null
  tokens: number | null
  wallSeconds: number | null
  peakMemoryBytes: number | null
}

export interface ResourceTotals {
  runs: number
  disclosing: number
  cpuSeconds: number | null
  gpuSeconds: number | null
  tokens: number | null
  wallSeconds: number | null
  peakMemoryBytes: number | null
  candidatesGenerated: number | null
  candidatesAccepted: number | null
}

export interface BudgetRow {
  researchVersionId: string
  researchId: string
  status: string
  cpuUsed: number
  cpuLimit: number
  wallUsed: number
  wallLimit: number
  tokensUsed: number
  tokensLimit: number
  candidatesUsed: number
  candidatesLimit: number
}

export interface ResourceSummary {
  totals: ResourceTotals
  rows: ResourceUsageRow[]
  budgets: BudgetRow[]
  /** 後端沒有即時硬體觀測端點，這裡固定回報未取得。 */
  instantaneous: { label: string; value: string }[]
  note: string
}

function sumOrNull(values: (number | null)[]): number | null {
  const disclosed = values.filter((value): value is number => value !== null)
  if (disclosed.length === 0) return null
  return disclosed.reduce((total, value) => total + value, 0)
}

/** 資源監控只彙整任務文件已揭露的用量與研究版本帳本，缺欄位一律回報未取得。 */
export function buildResourceSummary(snapshot: ConsoleSnapshot): ResourceSummary {
  const rows: ResourceUsageRow[] = snapshot.researchRuns
    .filter((run) => run.budgetUsage !== null)
    .map((run) => {
      const usage = run.budgetUsage
      return {
        runId: run.id,
        type: run.type,
        status: run.status,
        created_at: run.created_at,
        cpuSeconds: usage === null ? null : usage.cpu_seconds,
        gpuSeconds: usage === null ? null : usage.gpu_seconds,
        tokens: usage === null ? null : usage.tokens,
        wallSeconds: usage === null ? null : usage.elapsed_wall_seconds,
        peakMemoryBytes: usage === null ? null : usage.peak_memory_bytes,
      }
    })
    .sort((left, right) => desc(left.created_at, right.created_at))

  const usages = snapshot.researchRuns.map((run) => run.budgetUsage)
  const totals: ResourceTotals = {
    runs: snapshot.researchRuns.length + snapshot.datasetRuns.length,
    disclosing: rows.length,
    cpuSeconds: sumOrNull(usages.map((usage) => (usage === null ? null : usage.cpu_seconds))),
    gpuSeconds: sumOrNull(usages.map((usage) => (usage === null ? null : usage.gpu_seconds))),
    tokens: sumOrNull(usages.map((usage) => (usage === null ? null : usage.tokens))),
    wallSeconds: sumOrNull(usages.map((usage) => (usage === null ? null : usage.elapsed_wall_seconds))),
    peakMemoryBytes: sumOrNull(usages.map((usage) => (usage === null ? null : usage.peak_memory_bytes))),
    candidatesGenerated: sumOrNull(usages.map((usage) => (usage === null ? null : usage.candidates_generated))),
    candidatesAccepted: sumOrNull(usages.map((usage) => (usage === null ? null : usage.candidates_accepted))),
  }

  const budgets: BudgetRow[] = snapshot.researchVersions.map((version) => {
    const used = version.research_budget_usage
    return {
      researchVersionId: version.id,
      researchId: version.research_id,
      status: version.status,
      cpuUsed: used.cpu_seconds,
      cpuLimit: version.budget.cpu_seconds,
      wallUsed: used.elapsed_wall_seconds,
      wallLimit: version.budget.wall_seconds,
      tokensUsed: used.tokens,
      tokensLimit: version.budget.tokens,
      candidatesUsed: used.candidates_generated,
      candidatesLimit: version.budget.candidate_limit,
    }
  })

  return {
    totals,
    rows,
    budgets,
    instantaneous: [
      { label: 'CPU', value: UNKNOWN },
      { label: 'GPU', value: UNKNOWN },
      { label: 'RAM', value: UNKNOWN },
    ],
    note: '後端目前只揭露任務文件內的用量與研究版本帳本，沒有即時 CPU／GPU／RAM 觀測端點；資料集匯入任務的投影也不含預算欄位，因此不含在用量彙總內。',
  }
}

export function activeVersionCount(snapshot: ConsoleSnapshot): number {
  return snapshot.researchVersions.filter((version) => ACTIVE_VERSION_STATUSES.has(version.status)).length
}

export function activeRunCount(snapshot: ConsoleSnapshot): number {
  return allRuns(snapshot).filter((run) => ACTIVE_RUN_STATUSES.has(run.status)).length
}

export function describeOutcome(code: string | null): string {
  if (code === null) return UNKNOWN
  return OUTCOME_LABELS[code] ?? code
}

export function describeStopReason(code: string | null): string {
  if (code === null) return UNKNOWN
  return STOP_REASON_LABELS[code] ?? code
}
