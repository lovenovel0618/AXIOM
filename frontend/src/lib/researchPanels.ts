/**
 * 研究模組（SSOT 08–10：研究詳情／研究分支圖／研究任務紀錄）共用推導層。
 *
 * 後端沒有研究層級的目標、成果摘要、分支圖與事件重播端點，這一層只由既有契約實體
 * （研究、研究版本、任務、凍結提交與最終評估）推導；未揭露欄位一律標示「未取得」，
 * 統計只涵蓋實際讀取到的頁面並標示截斷。
 */
import type {
  Research,
  ResearchPage,
  ResearchPurpose,
  ResearchVersion,
  ResearchVersionPage,
  ResearchVersionStatus,
  RunPage,
} from '../api/research'
import { isTerminal, type Run, type RunStatus, type RunType } from '../api/runs'
import type { FinalEvaluation } from './finalEvaluation'

export const RESEARCH_UNKNOWN = '未取得'

/** 讀取範圍：只統計實際讀到的頁面，超出即標示截斷。 */
export const RESEARCHES_READ = 12
export const VERSIONS_PER_RESEARCH = 8
export const RUNS_PER_VERSION = 12
export const EVALUATIONS_READ = 16

export type PanelTone = 'OK' | 'PENDING' | 'RUNNING' | 'FAILED' | 'NEUTRAL'

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

export const RUN_TYPE_LABELS: Record<RunType, string> = {
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

const RUN_STATUS_TONES: Record<RunStatus, PanelTone> = {
  QUEUED: 'PENDING',
  RUNNING: 'RUNNING',
  CANCEL_REQUESTED: 'RUNNING',
  SUCCEEDED: 'OK',
  FAILED: 'FAILED',
  CANCELLED: 'NEUTRAL',
}

const VERSION_STATUS_TONES: Record<ResearchVersionStatus, PanelTone> = {
  DRAFT: 'NEUTRAL',
  VALIDATING: 'RUNNING',
  READY: 'OK',
  QUEUED: 'PENDING',
  RUNNING: 'RUNNING',
  FAILED: 'FAILED',
  CANCELLED: 'NEUTRAL',
}

export function runStatusTone(status: RunStatus): PanelTone {
  return RUN_STATUS_TONES[status]
}

export function versionStatusTone(status: ResearchVersionStatus): PanelTone {
  return VERSION_STATUS_TONES[status]
}

export interface PanelRun {
  run: Run
  version: ResearchVersion
}

export interface PanelSample {
  version: ResearchVersion
  submissionId: string
  evaluation: FinalEvaluation | null
}

export interface ResearchScope {
  researchesRead: number
  versionsRead: number
  runsRead: number
  samplesRead: number
  truncated: boolean
}

export interface ResearchPanel {
  research: Research | null
  versions: ResearchVersion[]
  runs: PanelRun[]
  samples: PanelSample[]
  scope: ResearchScope
}

export interface ResearchPanelDeps {
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  getFinalEvaluation: (submissionId: string) => Promise<FinalEvaluation | null>
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

function asc(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? -1 : 1
}

function matches(keyword: string, values: Array<string | null>): boolean {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return true
  return values.some((value) => value !== null && value.toLowerCase().includes(needle))
}

/**
 * 讀取單一研究的面板資料：研究本身、其版本、每個版本的任務與凍結提交的最終評估。
 * 任一步失敗都只讓該部分留空，不以推測補值；找不到研究時其餘一律回空集合。
 */
export async function loadResearchPanel(
  deps: ResearchPanelDeps,
  researchId: string,
): Promise<ResearchPanel> {
  const page = await safe(
    () => deps.listResearches(RESEARCHES_READ),
    { items: [], next_cursor: null } satisfies ResearchPage,
  )
  const research = page.items.find((item) => item.id === researchId) ?? null
  let truncated = page.next_cursor !== null
  if (research === null) {
    return {
      research: null,
      versions: [],
      runs: [],
      samples: [],
      scope: { researchesRead: page.items.length, versionsRead: 0, runsRead: 0, samplesRead: 0, truncated },
    }
  }

  const versionPage = await safe(
    () => deps.listResearchVersions(researchId, VERSIONS_PER_RESEARCH),
    { items: [], next_cursor: null } satisfies ResearchVersionPage,
  )
  truncated = truncated || versionPage.next_cursor !== null
  const versions = [...versionPage.items].sort((left, right) => desc(left.created_at, right.created_at))

  const runs: PanelRun[] = []
  const samples: PanelSample[] = []
  let sampleBudget = EVALUATIONS_READ
  for (const version of versions) {
    const runPage = await safe(
      () => deps.listResearchVersionRuns(version.id, RUNS_PER_VERSION),
      { items: [], next_cursor: null } satisfies RunPage,
    )
    if (runPage.next_cursor !== null) truncated = true
    for (const run of runPage.items) runs.push({ run, version })
    for (const submissionId of version.frozen_submission_ids) {
      if (sampleBudget <= 0) {
        truncated = true
        break
      }
      sampleBudget -= 1
      const evaluation = await safe(() => deps.getFinalEvaluation(submissionId), null)
      samples.push({ version, submissionId, evaluation })
    }
  }

  return {
    research,
    versions,
    runs,
    samples,
    scope: {
      researchesRead: page.items.length,
      versionsRead: versions.length,
      runsRead: runs.length,
      samplesRead: samples.length,
      truncated,
    },
  }
}

/* ── SCREEN 08：研究詳情（目標、執行快照、成果與版本） ─────────────────── */

export interface ProfileGoal {
  label: string
  value: string
}

export interface ProfileSnapshot {
  versionId: string
  status: ResearchVersionStatus
  statusLabel: string
  tone: PanelTone
  purposeLabel: string
  revision: number
  createdAt: string
  budgetCpuSeconds: number
  budgetGpuSeconds: number
  budgetTokens: number
  usedCpuSeconds: number
  usedGpuSeconds: number
  usedTokens: number
  candidatesGenerated: number
  candidatesAccepted: number
  sealedFinalTest: boolean
  domainCount: number
  qualityReportId: string | null
  evidenceBundleCount: number
}

export interface ProfileOutcomes {
  declaredSubmissions: number
  evaluatedSubmissions: number
  failedSubmissions: number
  unknownSubmissions: number
  sealedTestCount: number
  qualityReportCount: number
  evidenceBundleCount: number
  candidatesGenerated: number
  candidatesAccepted: number
}

export interface ResearchProfile {
  researchId: string | null
  researchName: string
  tenantId: string | null
  createdAt: string | null
  goals: ProfileGoal[]
  snapshots: ProfileSnapshot[]
  outcomes: ProfileOutcomes
}

/** 版本未揭露語意概況時，每一項目標都以「未取得」呈現，不以推測值代替。 */
export function buildProfileGoals(version: ResearchVersion | null): ProfileGoal[] {
  if (version === null) {
    return [
      { label: '研究目的', value: RESEARCH_UNKNOWN },
      { label: '資料集版本', value: RESEARCH_UNKNOWN },
      { label: '目標量', value: RESEARCH_UNKNOWN },
      { label: '輸入量', value: RESEARCH_UNKNOWN },
      { label: '單位確認', value: RESEARCH_UNKNOWN },
      { label: '時間序列', value: RESEARCH_UNKNOWN },
      { label: '量測解析度', value: RESEARCH_UNKNOWN },
      { label: '分組欄位', value: RESEARCH_UNKNOWN },
    ]
  }
  const profile = version.semantic_profile
  return [
    { label: '研究目的', value: `${PURPOSE_LABELS[version.purpose]}（${version.purpose}）` },
    { label: '資料集版本', value: version.dataset_version_id },
    { label: '目標量', value: `${profile.target.name}（欄位 ${profile.target.source_column}）` },
    {
      label: '輸入量',
      value:
        profile.inputs.length === 0
          ? '無'
          : profile.inputs.map((item) => `${item.name}（欄位 ${item.source_column}）`).join('；'),
    },
    { label: '單位確認', value: profile.units_confirmed ? '已確認' : '未確認' },
    { label: '時間序列', value: profile.time_ordered ? '是' : '否' },
    { label: '量測解析度', value: profile.measurement_resolution ?? RESEARCH_UNKNOWN },
    { label: '分組欄位', value: profile.group_column ?? RESEARCH_UNKNOWN },
  ]
}

export function buildResearchProfile(panel: ResearchPanel): ResearchProfile {
  const latest = panel.versions[0] ?? null
  const snapshots: ProfileSnapshot[] = panel.versions.map((version) => ({
    versionId: version.id,
    status: version.status,
    statusLabel: VERSION_STATUS_LABELS[version.status],
    tone: VERSION_STATUS_TONES[version.status],
    purposeLabel: PURPOSE_LABELS[version.purpose],
    revision: version.revision,
    createdAt: version.created_at,
    budgetCpuSeconds: version.budget.cpu_seconds,
    budgetGpuSeconds: version.budget.gpu_seconds,
    budgetTokens: version.budget.tokens,
    usedCpuSeconds: version.research_budget_usage.cpu_seconds,
    usedGpuSeconds: version.research_budget_usage.gpu_seconds,
    usedTokens: version.research_budget_usage.tokens,
    candidatesGenerated: version.research_budget_usage.candidates_generated,
    candidatesAccepted: version.research_budget_usage.candidates_accepted,
    sealedFinalTest: version.observation_split.sealed_final_test,
    domainCount: version.domain.length,
    qualityReportId: version.quality_report_id,
    evidenceBundleCount: version.evidence_bundle_ids.length,
  }))

  const declaredSubmissions = panel.versions.reduce(
    (total, version) => total + version.frozen_submission_ids.length,
    0,
  )
  const evaluatedSubmissions = panel.samples.filter((sample) => sample.evaluation?.status === 'EVALUATED').length
  const failedSubmissions = panel.samples.filter((sample) => sample.evaluation?.status === 'FAILED').length
  const outcomes: ProfileOutcomes = {
    declaredSubmissions,
    evaluatedSubmissions,
    failedSubmissions,
    // 未讀取或未回報的最終評估不得以 0 或推測補上，一律計為未取得。
    unknownSubmissions: Math.max(0, declaredSubmissions - evaluatedSubmissions - failedSubmissions),
    sealedTestCount: panel.versions.filter((version) => version.observation_split.sealed_final_test).length,
    qualityReportCount: panel.versions.filter((version) => version.quality_report_id !== null).length,
    evidenceBundleCount: panel.versions.reduce(
      (total, version) => total + version.evidence_bundle_ids.length,
      0,
    ),
    candidatesGenerated: panel.versions.reduce(
      (total, version) => total + version.research_budget_usage.candidates_generated,
      0,
    ),
    candidatesAccepted: panel.versions.reduce(
      (total, version) => total + version.research_budget_usage.candidates_accepted,
      0,
    ),
  }

  return {
    researchId: panel.research?.id ?? null,
    researchName: panel.research?.name ?? RESEARCH_UNKNOWN,
    tenantId: panel.research?.tenant_id ?? null,
    createdAt: panel.research?.created_at ?? null,
    goals: buildProfileGoals(latest),
    snapshots,
    outcomes,
  }
}

export function summarizeResearchProfile(profile: ResearchProfile): {
  versions: number
  ready: number
  declaredSubmissions: number
  evaluatedSubmissions: number
} {
  return {
    versions: profile.snapshots.length,
    ready: profile.snapshots.filter((snapshot) => snapshot.status === 'READY').length,
    declaredSubmissions: profile.outcomes.declaredSubmissions,
    evaluatedSubmissions: profile.outcomes.evaluatedSubmissions,
  }
}

/* ── SCREEN 09：研究分支圖（研究 DAG、依賴與分支恢復） ─────────────────── */

export type ResearchNodeKind = 'RESEARCH' | 'VERSION' | 'RUN'

export interface ResearchNodeRecord {
  label: string
  value: string
}

export interface ResearchNode {
  id: string
  kind: ResearchNodeKind
  column: number
  row: number
  title: string
  subtitle: string
  badge: string
  tone: PanelTone
  records: ResearchNodeRecord[]
  runId: string | null
  versionId: string | null
  /** 同一版本同型任務的出現序號；大於 1 即代表重試。 */
  retryIndex: number
}

export interface ResearchEdge {
  from: string
  to: string
  branch: boolean
}

export interface ResearchGraph {
  nodes: ResearchNode[]
  edges: ResearchEdge[]
  columns: number
  rows: number
}

function numberText(value: number | null | undefined): string {
  return value === null || value === undefined ? RESEARCH_UNKNOWN : String(value)
}

function textOrUnknown(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? RESEARCH_UNKNOWN : value
}

/** 依建立時間排序，同時間保留原始次序，讓圖與後端建立順序一致。 */
function chronological(runs: Run[]): Run[] {
  return runs
    .map((run, index) => ({ run, index }))
    .sort((left, right) => {
      if (left.run.created_at === right.run.created_at) return left.index - right.index
      return asc(left.run.created_at, right.run.created_at)
    })
    .map((entry) => entry.run)
}

/** 計算每個任務在「同版本同型任務」中的重試序號。 */
function retryIndexes(runs: PanelRun[]): Map<string, number> {
  const result = new Map<string, number>()
  const grouped = new Map<string, PanelRun[]>()
  for (const entry of runs) {
    const key = `${entry.version.id}:${entry.run.type}`
    const bucket = grouped.get(key) ?? []
    bucket.push(entry)
    grouped.set(key, bucket)
  }
  for (const bucket of grouped.values()) {
    const ordered = bucket
      .map((entry, index) => ({ entry, index }))
      .sort((left, right) => {
        if (left.entry.run.created_at === right.entry.run.created_at) return left.index - right.index
        return asc(left.entry.run.created_at, right.entry.run.created_at)
      })
    ordered.forEach((item, position) => {
      result.set(item.entry.run.id, position + 1)
    })
  }
  return result
}

export function buildResearchGraph(panel: ResearchPanel): ResearchGraph {
  const nodes: ResearchNode[] = []
  const edges: ResearchEdge[] = []
  const rows = [0, 0, 0]

  function add(node: Omit<ResearchNode, 'column' | 'row'>): string {
    const column = node.kind === 'RESEARCH' ? 0 : node.kind === 'VERSION' ? 1 : 2
    const row = rows[column] ?? 0
    rows[column] = row + 1
    nodes.push({ ...node, column, row })
    return node.id
  }

  const researchId = panel.research?.id ?? null
  const rootId = add({
    id: `research:${researchId ?? 'unknown'}`,
    kind: 'RESEARCH',
    title: researchId === null ? '研究（未取得）' : '研究',
    subtitle: RESEARCH_UNKNOWN,
    badge: researchId === null ? '未取得' : `${String(panel.versions.length)} 個版本`,
    tone: researchId === null ? 'NEUTRAL' : 'OK',
    records: [
      { label: '研究識別碼', value: textOrUnknown(researchId) },
      { label: '名稱', value: textOrUnknown(panel.research?.name) },
      { label: '租戶', value: textOrUnknown(panel.research?.tenant_id) },
      { label: '建立時間', value: textOrUnknown(panel.research?.created_at) },
      { label: '版本數', value: String(panel.versions.length) },
      { label: '任務數', value: String(panel.runs.length) },
      { label: '依賴關係', value: '研究 → 研究版本 → 任務（僅契約明載歸屬，不推測語意依賴）' },
    ],
    runId: null,
    versionId: null,
    retryIndex: 1,
  })

  const retries = retryIndexes(panel.runs)
  const versionNodeIds = new Map<string, string>()
  for (const version of panel.versions) {
    const versionRuns = panel.runs.filter((entry) => entry.version.id === version.id)
    const nodeId = add({
      id: `version:${version.id}`,
      kind: 'VERSION',
      title: '研究版本',
      subtitle: `${PURPOSE_LABELS[version.purpose]}／控制版本 ${String(version.revision)}`,
      badge: VERSION_STATUS_LABELS[version.status],
      tone: VERSION_STATUS_TONES[version.status],
      records: [
        { label: '研究版本', value: version.id },
        { label: '狀態', value: `${VERSION_STATUS_LABELS[version.status]}（${version.status}）` },
        { label: '目的', value: PURPOSE_LABELS[version.purpose] },
        { label: '控制版本', value: String(version.revision) },
        { label: '任務數', value: String(versionRuns.length) },
        { label: '凍結提交', value: String(version.frozen_submission_ids.length) },
        { label: '證據包', value: countText(version.evidence_bundle_ids.length) },
        { label: '品質報告', value: textOrUnknown(version.quality_report_id) },
        { label: '建立時間', value: version.created_at },
      ],
      runId: null,
      versionId: version.id,
      retryIndex: 1,
    })
    versionNodeIds.set(version.id, nodeId)
    edges.push({ from: rootId, to: nodeId, branch: panel.versions.length > 1 })
  }

  const runNodeIds = new Map<string, string>()
  for (const version of panel.versions) {
    const versionRuns = chronological(
      panel.runs.filter((entry) => entry.version.id === version.id).map((entry) => entry.run),
    )
    const parent = versionNodeIds.get(version.id)
    if (parent === undefined) continue
    for (const run of versionRuns) {
      const retryIndex = retries.get(run.id) ?? 1
      const nodeId = add({
        id: `run:${run.id}`,
        kind: 'RUN',
        title: `${RUN_TYPE_LABELS[run.type]}任務`,
        subtitle: textOrUnknown(run.phase),
        badge: RUN_STATUS_LABELS[run.status],
        tone: RUN_STATUS_TONES[run.status],
        records: [
          { label: '任務識別碼', value: run.id },
          { label: '類型', value: `${RUN_TYPE_LABELS[run.type]}（${run.type}）` },
          { label: '狀態', value: `${RUN_STATUS_LABELS[run.status]}（${run.status}）` },
          { label: '階段', value: textOrUnknown(run.phase) },
          { label: '停止原因', value: textOrUnknown(run.stop_reason) },
          { label: '結果判定', value: textOrUnknown(run.outcome_status) },
          { label: '控制版本', value: String(run.revision) },
          { label: '重試序號', value: retryIndex > 1 ? `第 ${String(retryIndex)} 次（重試）` : '第 1 次' },
          { label: '子任務', value: String((run.child_run_ids ?? []).length) },
          {
            label: '用量',
            value:
              run.budget_usage === undefined
                ? RESEARCH_UNKNOWN
                : `CPU ${String(run.budget_usage.cpu_seconds)} 秒／GPU ${String(run.budget_usage.gpu_seconds)} 秒／Token ${String(run.budget_usage.tokens)}`,
          },
          { label: '建立時間', value: run.created_at },
        ],
        runId: run.id,
        versionId: version.id,
        retryIndex,
      })
      runNodeIds.set(run.id, nodeId)
      edges.push({ from: parent, to: nodeId, branch: versionRuns.length > 1 })
    }
  }

  const maxRows = rows.reduce((best, count) => Math.max(best, count), 0)
  return { nodes, edges, columns: rows.length, rows: maxRows }
}

function countText(count: number): string {
  return count === 0 ? '尚未產生' : String(count)
}

export function summarizeResearchGraph(panel: ResearchPanel): {
  versions: number
  runs: number
  branches: number
  retries: number
  failed: number
} {
  const retries = retryIndexes(panel.runs)
  const perVersion = new Map<string, number>()
  for (const entry of panel.runs) perVersion.set(entry.version.id, (perVersion.get(entry.version.id) ?? 0) + 1)
  return {
    versions: panel.versions.length,
    runs: panel.runs.length,
    branches: [...perVersion.values()].filter((count) => count > 1).length,
    retries: panel.runs.filter((entry) => (retries.get(entry.run.id) ?? 1) > 1).length,
    failed: panel.runs.filter((entry) => entry.run.status === 'FAILED' || entry.run.status === 'CANCELLED').length,
  }
}

/* ── SCREEN 10：研究任務紀錄（執行排程、重試、失敗與事件重播） ─────────── */

export interface TimelineEntry {
  runId: string
  versionId: string
  versionLabel: string
  versionStatus: ResearchVersionStatus
  versionStatusLabel: string
  type: RunType
  typeLabel: string
  status: RunStatus
  statusLabel: string
  tone: PanelTone
  phase: string
  stopReason: string
  outcomeStatus: string
  revision: number
  createdAt: string
  retryIndex: number
  isRetry: boolean
  terminal: boolean
  replayCursor: string
  childRuns: number
  artifacts: number
  cpuSeconds: number | null
  gpuSeconds: number | null
  tokens: number | null
}

export function buildResearchTimeline(panel: ResearchPanel): TimelineEntry[] {
  const retries = retryIndexes(panel.runs)
  return panel.runs
    .map((entry) => {
      const retryIndex = retries.get(entry.run.id) ?? 1
      const usage = entry.run.budget_usage
      return {
        entry,
        retryIndex,
        sortKey: entry.run.created_at,
      }
    })
    .sort((left, right) => desc(left.sortKey, right.sortKey))
    .map(({ entry, retryIndex }) => ({
      runId: entry.run.id,
      versionId: entry.version.id,
      versionLabel: `${VERSION_STATUS_LABELS[entry.version.status]}／控制版本 ${String(entry.version.revision)}`,
      versionStatus: entry.version.status,
      versionStatusLabel: VERSION_STATUS_LABELS[entry.version.status],
      type: entry.run.type,
      typeLabel: RUN_TYPE_LABELS[entry.run.type],
      status: entry.run.status,
      statusLabel: RUN_STATUS_LABELS[entry.run.status],
      tone: RUN_STATUS_TONES[entry.run.status],
      phase: textOrUnknown(entry.run.phase),
      stopReason: textOrUnknown(entry.run.stop_reason),
      outcomeStatus: textOrUnknown(entry.run.outcome_status),
      revision: entry.run.revision,
      createdAt: entry.run.created_at,
      retryIndex,
      isRetry: retryIndex > 1,
      terminal: isTerminal(entry.run.status),
      replayCursor: textOrUnknown(entry.run.current_event_cursor),
      childRuns: (entry.run.child_run_ids ?? []).length,
      artifacts: (entry.run.diagnostic_artifact_ids ?? []).length + (entry.run.research_trace_artifact_ids ?? []).length,
      cpuSeconds: entry.run.budget_usage?.cpu_seconds ?? null,
      gpuSeconds: entry.run.budget_usage?.gpu_seconds ?? null,
      tokens: entry.run.budget_usage?.tokens ?? null,
    }))
}

export function summarizeResearchTimeline(entries: TimelineEntry[]): {
  entries: number
  queued: number
  running: number
  failed: number
  retried: number
  terminal: number
} {
  return {
    entries: entries.length,
    queued: entries.filter((entry) => entry.status === 'QUEUED').length,
    running: entries.filter((entry) => !entry.terminal && entry.status !== 'QUEUED').length,
    failed: entries.filter((entry) => entry.status === 'FAILED').length,
    retried: entries.filter((entry) => entry.isRetry).length,
    terminal: entries.filter((entry) => entry.terminal).length,
  }
}

export function filterResearchTimeline(
  entries: TimelineEntry[],
  keyword: string,
  status: RunStatus | 'ALL' = 'ALL',
): TimelineEntry[] {
  return entries.filter((entry) => {
    if (status !== 'ALL' && entry.status !== status) return false
    return matches(keyword, [entry.runId, entry.typeLabel, entry.statusLabel, entry.type, entry.status, entry.versionId])
  })
}
