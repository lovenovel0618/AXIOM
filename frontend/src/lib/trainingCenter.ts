/**
 * 訓練模組（SSOT 36–38：訓練資料集／微調任務／模型版本發布）共用推導層。
 *
 * 後端沒有微調、LoRA、模型發布或訓練監控端點，因此這一層只從既有契約實體
 * （研究、研究版本、任務、凍結提交與其最終評估）推導；後端未揭露的欄位一律標示
 * 「未取得」，不以 0 或推測值代替，統計範圍也只涵蓋實際讀取到的頁面。
 */
import type { FinalEvaluation } from './finalEvaluation'
import type { Run, RunStatus, RunType } from '../api/runs'
import type {
  Research,
  ResearchPage,
  ResearchPurpose,
  ResearchVersion,
  ResearchVersionPage,
  ResearchVersionStatus,
  RunPage,
} from '../api/research'

/** 後端未回報的欄位一律顯示這個字串，不以 0 或推測值代替。 */
export const TRAINING_UNKNOWN = '未取得'

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

export const VERSION_STATUS_LABELS: Record<ResearchVersionStatus, string> = {
  DRAFT: '草稿',
  VALIDATING: '驗證中',
  READY: '就緒',
  QUEUED: '排隊中',
  RUNNING: '執行中',
  FAILED: '失敗',
  CANCELLED: '已取消',
}

export const PURPOSE_LABELS: Record<ResearchPurpose, string> = {
  DESCRIPTION: '描述',
  PREDICTION: '預測',
  MECHANISM: '機制',
}

/** 讀取範圍；後端沒有全域端點，所有統計都只涵蓋實際讀到的頁面。 */
export const RESEARCHES_READ = 12
export const VERSIONS_PER_RESEARCH = 5
export const RECENT_VERSIONS_READ = 12
export const RUNS_PER_VERSION = 8
export const RECENT_RUNS_READ = 16
export const SAMPLE_READS = 24

export interface TrainingRun {
  run: Run
  research: Research | null
  version: ResearchVersion | null
}

export interface TrainingSample {
  version: ResearchVersion
  research: Research | null
  submissionId: string
  /** 讀不到時為 null，代表「未取得」，不代表沒有評估。 */
  evaluation: FinalEvaluation | null
}

export interface TrainingScope {
  researchesRead: number
  versionsRead: number
  runsRead: number
  samplesRead: number
  truncated: boolean
}

export interface TrainingCenter {
  researches: Research[]
  versions: ResearchVersion[]
  runs: TrainingRun[]
  samples: TrainingSample[]
  scope: TrainingScope
}

export interface TrainingDeps {
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

export async function loadTrainingCenter(deps: TrainingDeps): Promise<TrainingCenter> {
  let truncated = false
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
  const researchById = new Map(researchPage.items.map((research) => [research.id, research]))

  const runGroups = await Promise.all(
    versions.map(async (version) => {
      const page = await safe(
        () => deps.listResearchVersionRuns(version.id, RUNS_PER_VERSION),
        { items: [], next_cursor: null } satisfies RunPage,
      )
      if (page.next_cursor !== null) truncated = true
      return page.items.map((run) => ({
        run,
        research: researchById.get(version.research_id) ?? null,
        version,
      }))
    }),
  )

  const allRuns = runGroups.flat().sort((a, b) => desc(a.run.created_at, b.run.created_at))
  if (allRuns.length > RECENT_RUNS_READ) truncated = true
  const runs = allRuns.slice(0, RECENT_RUNS_READ)

  const pending: Omit<TrainingSample, 'evaluation'>[] = []
  for (const version of versions) {
    const research = researchById.get(version.research_id) ?? null
    for (const submissionId of version.frozen_submission_ids) {
      pending.push({ version, research, submissionId })
    }
  }
  if (pending.length > SAMPLE_READS) truncated = true
  const selectedSamples = pending.slice(0, SAMPLE_READS)
  const samples = await Promise.all(
    selectedSamples.map(async (entry) => ({
      ...entry,
      evaluation: await safe(() => deps.getFinalEvaluation(entry.submissionId), null),
    })),
  )

  return {
    researches: researchPage.items,
    versions,
    runs,
    samples,
    scope: {
      researchesRead: researchPage.items.length,
      versionsRead: versions.length,
      runsRead: runs.length,
      samplesRead: samples.length,
      truncated,
    },
  }
}

export interface TrainingSampleCounts {
  declared: number
  evaluated: number
  running: number
  failed: number
  unknown: number
}

function countSamples(samples: TrainingSample[]): TrainingSampleCounts {
  const counts: TrainingSampleCounts = { declared: samples.length, evaluated: 0, running: 0, failed: 0, unknown: 0 }
  for (const sample of samples) {
    const status = sample.evaluation?.status ?? null
    if (status === null) counts.unknown += 1
    else if (status === 'EVALUATED') counts.evaluated += 1
    else if (status === 'FAILED') counts.failed += 1
    else counts.running += 1
  }
  return counts
}

/** SCREEN 36｜訓練資料集：只列宣告了凍結提交的研究版本，樣本與標籤取自可讀的評估。 */
export interface TrainingDatasetRow {
  versionId: string
  researchId: string | null
  researchName: string
  versionStatus: ResearchVersionStatus
  purposeLabel: string
  samples: TrainingSampleCounts
  /** 版本固定的評估政策指紋，可作為標籤政策的追溯鍵。 */
  labelPolicyHash: string
  /** 第一筆可讀評估的計量版本；全部未取得時為「未取得」。 */
  metricVersion: string
  qualityReportId: string | null
  createdAt: string
}

export function buildTrainingDatasets(center: TrainingCenter): TrainingDatasetRow[] {
  const researchById = new Map(center.researches.map((research) => [research.id, research]))
  const samplesByVersion = new Map<string, TrainingSample[]>()
  for (const sample of center.samples) {
    const bucket = samplesByVersion.get(sample.version.id)
    if (bucket === undefined) samplesByVersion.set(sample.version.id, [sample])
    else bucket.push(sample)
  }

  const rows: TrainingDatasetRow[] = []
  for (const version of center.versions) {
    if (version.frozen_submission_ids.length === 0) continue
    const samples = samplesByVersion.get(version.id) ?? []
    const metric = samples.find((sample) => sample.evaluation !== null)?.evaluation?.metricVersion ?? TRAINING_UNKNOWN
    rows.push({
      versionId: version.id,
      researchId: researchById.get(version.research_id)?.id ?? null,
      researchName: researchById.get(version.research_id)?.name ?? TRAINING_UNKNOWN,
      versionStatus: version.status,
      purposeLabel: PURPOSE_LABELS[version.purpose],
      samples: countSamples(samples),
      labelPolicyHash: version.evaluation_policy_hash,
      metricVersion: metric,
      qualityReportId: version.quality_report_id,
      createdAt: version.created_at,
    })
  }
  return rows.sort((a, b) => desc(a.createdAt, b.createdAt))
}

export interface TrainingDatasetSummary {
  datasets: number
  declared: number
  evaluated: number
  failed: number
}

export function summarizeTrainingDatasets(rows: TrainingDatasetRow[]): TrainingDatasetSummary {
  const summary: TrainingDatasetSummary = { datasets: rows.length, declared: 0, evaluated: 0, failed: 0 }
  for (const row of rows) {
    summary.declared += row.samples.declared
    summary.evaluated += row.samples.evaluated
    summary.failed += row.samples.failed
  }
  return summary
}

/** SCREEN 37｜微調任務：後端沒有微調端點，只投影既有任務與其版本預算配額。 */
export interface FinetuneRow {
  runId: string
  taskClass: RunType
  taskLabel: string
  researchId: string | null
  researchName: string
  versionId: string | null
  status: RunStatus
  quotaCpuSeconds: number | null
  quotaGpuSeconds: number | null
  quotaWallSeconds: number | null
  quotaTokens: number | null
  usedCpuSeconds: number | null
  usedGpuSeconds: number | null
  usedTokens: number | null
  /** LoRA 目標、基底模型、檢查點與資源配額政策後端未揭露。 */
  adapterTarget: string
  baseModel: string
  checkpoint: string
  createdAt: string
}

export function buildFinetuneRows(center: TrainingCenter): FinetuneRow[] {
  const researchById = new Map(center.researches.map((research) => [research.id, research]))
  const rows = center.runs.map((entry) => {
    const version = entry.version
    const research = version === null ? null : researchById.get(version.research_id) ?? entry.research
    const usage = entry.run.budget_usage
    return {
      runId: entry.run.id,
      taskClass: entry.run.type,
      taskLabel: RUN_TYPE_LABELS[entry.run.type],
      researchId: research?.id ?? null,
      researchName: research?.name ?? TRAINING_UNKNOWN,
      versionId: version?.id ?? null,
      status: entry.run.status,
      quotaCpuSeconds: version?.budget.cpu_seconds ?? null,
      quotaGpuSeconds: version?.budget.gpu_seconds ?? null,
      quotaWallSeconds: version?.budget.wall_seconds ?? null,
      quotaTokens: version?.budget.tokens ?? null,
      usedCpuSeconds: usage?.cpu_seconds ?? null,
      usedGpuSeconds: usage?.gpu_seconds ?? null,
      usedTokens: usage?.tokens ?? null,
      adapterTarget: TRAINING_UNKNOWN,
      baseModel: TRAINING_UNKNOWN,
      checkpoint: TRAINING_UNKNOWN,
      createdAt: entry.run.created_at,
    } satisfies FinetuneRow
  })
  return rows.sort((a, b) => desc(a.createdAt, b.createdAt))
}

export interface FinetuneSummary {
  tasks: number
  active: number
  failed: number
  quotaCpuSeconds: number | null
  quotaGpuSeconds: number | null
}

export function summarizeFinetune(rows: FinetuneRow[]): FinetuneSummary {
  let active = 0
  let failed = 0
  const cpu: number[] = []
  const gpu: number[] = []
  for (const row of rows) {
    if (row.status === 'FAILED') failed += 1
    else if (row.status !== 'SUCCEEDED' && row.status !== 'CANCELLED') active += 1
    if (row.quotaCpuSeconds !== null) cpu.push(row.quotaCpuSeconds)
    if (row.quotaGpuSeconds !== null) gpu.push(row.quotaGpuSeconds)
  }
  return {
    tasks: rows.length,
    active,
    failed,
    quotaCpuSeconds: cpu.length === 0 ? null : cpu.reduce((total, value) => total + value, 0),
    quotaGpuSeconds: gpu.length === 0 ? null : gpu.reduce((total, value) => total + value, 0),
  }
}

/** SCREEN 38｜模型版本發布：只列已凍結或已就緒的版本，發布資訊一律「未取得」。 */
export interface ReleaseRow {
  versionId: string
  researchId: string | null
  researchName: string
  versionStatus: ResearchVersionStatus
  revision: number
  policyHash: string
  declaredSubmissions: number
  evaluatedSubmissions: number
  modelName: string
  modelVersion: string
  releaseChannel: string
  releasedAt: string
  createdAt: string
}

export function buildReleaseRows(center: TrainingCenter): ReleaseRow[] {
  const researchById = new Map(center.researches.map((research) => [research.id, research]))
  const samplesByVersion = new Map<string, TrainingSample[]>()
  for (const sample of center.samples) {
    const bucket = samplesByVersion.get(sample.version.id)
    if (bucket === undefined) samplesByVersion.set(sample.version.id, [sample])
    else bucket.push(sample)
  }

  const rows: ReleaseRow[] = []
  for (const version of center.versions) {
    const declared = version.frozen_submission_ids.length
    if (declared === 0 && version.status !== 'READY') continue
    const samples = samplesByVersion.get(version.id) ?? []
    rows.push({
      versionId: version.id,
      researchId: researchById.get(version.research_id)?.id ?? null,
      researchName: researchById.get(version.research_id)?.name ?? TRAINING_UNKNOWN,
      versionStatus: version.status,
      revision: version.revision,
      policyHash: version.evaluation_policy_hash,
      declaredSubmissions: declared,
      evaluatedSubmissions: countSamples(samples).evaluated,
      modelName: TRAINING_UNKNOWN,
      modelVersion: TRAINING_UNKNOWN,
      releaseChannel: TRAINING_UNKNOWN,
      releasedAt: TRAINING_UNKNOWN,
      createdAt: version.created_at,
    })
  }
  return rows.sort((a, b) => desc(a.createdAt, b.createdAt))
}

export interface ReleaseSummary {
  versions: number
  ready: number
  submissions: number
  evaluated: number
}

export function summarizeReleases(rows: ReleaseRow[]): ReleaseSummary {
  const summary: ReleaseSummary = { versions: rows.length, ready: 0, submissions: 0, evaluated: 0 }
  for (const row of rows) {
    if (row.versionStatus === 'READY') summary.ready += 1
    summary.submissions += row.declaredSubmissions
    summary.evaluated += row.evaluatedSubmissions
  }
  return summary
}

function matches(keyword: string, values: (string | null)[]): boolean {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return true
  return values.some((value) => value !== null && value.toLowerCase().includes(needle))
}

export function filterTrainingDatasets(rows: TrainingDatasetRow[], keyword: string): TrainingDatasetRow[] {
  return rows.filter((row) => matches(keyword, [row.researchName, row.versionId, row.purposeLabel]))
}

export function filterFinetuneRows(rows: FinetuneRow[], keyword: string): FinetuneRow[] {
  return rows.filter((row) => matches(keyword, [row.researchName, row.runId, row.taskLabel]))
}

export function filterReleaseRows(rows: ReleaseRow[], keyword: string): ReleaseRow[] {
  return rows.filter((row) => matches(keyword, [row.researchName, row.versionId, row.policyHash]))
}
