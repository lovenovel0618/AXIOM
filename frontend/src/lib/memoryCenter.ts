/**
 * 記憶模組（SSOT 27–31：知識庫／研究經驗／失敗案例／假設恢復／知識演化）共用推導層。
 *
 * 後端目前沒有專屬的知識庫、經驗或知識圖譜端點，因此這一層只從既有契約實體
 * （研究、研究版本、任務、證據包、品質報告、最終評估、驗證結果）推導；
 * 後端未揭露的欄位一律標示「未取得」，不以 0 或推測值代替。
 */
import type { EvidenceBundle, EvidenceStatus, QualityOutcome, QualityReport, Readiness } from './evidence'
import { parseEvidenceBundle, parseQualityReport } from './evidence'
import type { FinalEvaluation, SubmissionStatus } from './finalEvaluation'
import { SUBMISSION_STATUS_LABELS } from './finalEvaluation'
import { describeMetricReason, OUTCOME_DETAILS, type OutcomeStatus, type ValidationRun } from './evaluation'
import type { Run, RunPhase, RunStatus, RunType, StopReason } from '../api/runs'
import type {
  Research,
  ResearchPage,
  ResearchVersion,
  ResearchVersionPage,
  ResearchVersionStatus,
  RunPage,
} from '../api/research'

/** 後端未回報的欄位一律顯示這個字串，不以 0 或推測值代替。 */
export const MEMORY_UNKNOWN = '未取得'

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

export const PHASE_LABELS: Record<RunPhase, string> = {
  PROFILING: '資料剖析',
  FEASIBILITY: '可行性評估',
  RETRIEVING: '檢索',
  PLANNING: '規劃',
  SEARCHING: '搜尋',
  FITTING: '擬合',
  VALIDATING: '驗證',
  FINALIZING: '收尾',
}

export const STOP_REASON_LABELS: Record<StopReason, string> = {
  BUDGET_EXHAUSTED: '預算耗盡',
  NO_IMPROVEMENT: '無進一步改善',
  NUMERICAL_FAILURE: '數值失敗',
  AMBIGUOUS: '結果歧義',
  USER_CANCELLED: '使用者取消',
  COMPLETED: '完成',
  DEPENDENCY_FAILURE: '相依任務失敗',
  NO_VALID_CANDIDATE: '無有效候選',
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

/** 讀取範圍；後端沒有全域端點，所有統計都只涵蓋實際讀到的頁面。 */
export const RESEARCHES_READ = 12
export const VERSIONS_PER_RESEARCH = 5
export const RECENT_VERSIONS_READ = 12
export const RUNS_PER_VERSION = 8
export const RECENT_RUNS_READ = 16

export interface MemoryRun {
  run: Run
  research: Research | null
  version: ResearchVersion | null
}

export interface MemoryEvidenceItem {
  research: Research | null
  version: ResearchVersion
  bundles: EvidenceBundle[]
  qualityReport: QualityReport | null
  /** 版本宣告了證據包或品質報告，但沒有任何一份可解析。 */
  unreadable: boolean
}

export interface MemorySubmissionRow {
  research: Research | null
  version: ResearchVersion
  submissionId: string
  finalEvaluation: FinalEvaluation | null
  validations: ValidationRun[]
}

export interface MemoryScope {
  researchesRead: number
  versionsRead: number
  runsRead: number
  truncated: boolean
}

export interface MemoryCenter {
  researches: Research[]
  versions: ResearchVersion[]
  runs: MemoryRun[]
  evidenceItems: MemoryEvidenceItem[]
  submissionRows: MemorySubmissionRow[]
  scope: MemoryScope
}

export interface MemoryDeps {
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  getFinalEvaluation: (submissionId: string) => Promise<FinalEvaluation | null>
  getValidationRun: (validationId: string) => Promise<ValidationRun | null>
  getEvidenceBundle: (bundleId: string) => Promise<unknown>
  getQualityReport: (artifactId: string) => Promise<unknown>
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

export async function loadMemoryCenter(deps: MemoryDeps): Promise<MemoryCenter> {
  const researchPage = await safe(deps.listResearches(RESEARCHES_READ), { items: [], next_cursor: null } satisfies ResearchPage)
  const researches = researchPage.items

  const versionEntries = await Promise.all(
    researches.map(async (research) => [
      research.id,
      (await safe(deps.listResearchVersions(research.id, VERSIONS_PER_RESEARCH), {
        items: [],
        next_cursor: null,
      } satisfies ResearchVersionPage)).items,
    ] as const),
  )
  const versionsByResearch = Object.fromEntries(versionEntries)
  const recentVersions = takeRecent(Object.values(versionsByResearch).flat(), RECENT_VERSIONS_READ)

  const runPages = await Promise.all(
    recentVersions.map(async (version) =>
      (await safe(deps.listResearchVersionRuns(version.id, RUNS_PER_VERSION), {
        items: [],
        next_cursor: null,
      } satisfies RunPage)).items,
    ),
  )
  const runs: MemoryRun[] = []
  for (const run of takeRecent(runPages.flat(), RECENT_RUNS_READ)) {
    const version = recentVersions.find((row) => row.id === run.research_version_id) ?? null
    runs.push({
      run,
      version,
      research: version === null ? null : researches.find((row) => row.id === version.research_id) ?? null,
    })
  }
  runs.sort((left, right) => desc(left.run.created_at, right.run.created_at))

  const evidenceItems: MemoryEvidenceItem[] = []
  for (const version of recentVersions) {
    if (version.evidence_bundle_ids.length === 0 && version.quality_report_id === null) continue
    const research = researches.find((row) => row.id === version.research_id) ?? null
    const bundles: EvidenceBundle[] = []
    for (const bundleId of version.evidence_bundle_ids) {
      const parsed = await safe(deps.getEvidenceBundle(bundleId).then(parseEvidenceBundle), null)
      if (parsed !== null) bundles.push(parsed)
    }
    const qualityReport =
      version.quality_report_id === null
        ? null
        : await safe(deps.getQualityReport(version.quality_report_id).then(parseQualityReport), null)
    evidenceItems.push({
      research,
      version,
      bundles,
      qualityReport,
      unreadable: bundles.length === 0 && qualityReport === null,
    })
  }

  const submissionRows: MemorySubmissionRow[] = []
  for (const version of recentVersions) {
    const research = researches.find((row) => row.id === version.research_id) ?? null
    for (const submissionId of version.frozen_submission_ids) {
      const finalEvaluation = await deps.getFinalEvaluation(submissionId)
      const validationIds = [
        ...new Set(
          (finalEvaluation?.slots ?? []).flatMap((slot) => (slot.validationRunId === null ? [] : [slot.validationRunId])),
        ),
      ]
      const validations = (await Promise.all(validationIds.map(async (id) => await deps.getValidationRun(id)))).filter(
        (row): row is ValidationRun => row !== null,
      )
      submissionRows.push({ research, version, submissionId, finalEvaluation, validations })
    }
  }

  const truncated =
    researchPage.next_cursor !== null ||
    versionEntries.some(([, items]) => items.length >= VERSIONS_PER_RESEARCH) ||
    runPages.some((items) => items.length >= RUNS_PER_VERSION)

  return {
    researches,
    versions: recentVersions,
    runs,
    evidenceItems,
    submissionRows,
    scope: {
      researchesRead: researches.length,
      versionsRead: recentVersions.length,
      runsRead: runs.length,
      truncated,
    },
  }
}

// ---------------------------------------------------------------------------
// 知識庫（SSOT 27）：已驗證結論、來源與檢索
// ---------------------------------------------------------------------------

export interface KnowledgeRow {
  versionId: string
  researchId: string | null
  researchName: string
  versionStatus: ResearchVersionStatus
  bundleCount: number
  /** 沒有任何證據包時為 null，由畫面顯示「未取得」。 */
  bundleStatus: EvidenceStatus | null
  proofArtifactCount: number
  declaredValidationCount: number
  quality: QualityOutcome | null
  readiness: Readiness | null
  outcomes: Record<OutcomeStatus, number>
  verifiedConclusions: number
  /** 檢索用的主題與標籤後端未提供。 */
  retrievalTags: string
  createdAt: string
}

const EMPTY_OUTCOMES: Record<OutcomeStatus, number> = {
  SUPPORTED: 0,
  AMBIGUOUS: 0,
  INSUFFICIENT_EVIDENCE: 0,
  FALSIFIED: 0,
}

/** 已驗證結論只由實際讀到的證據包與驗證結果組出；缺欄一律標示未取得。 */
export function buildKnowledgeRows(center: MemoryCenter): KnowledgeRow[] {
  const rows = center.evidenceItems.map((item) => {
    const outcomes: Record<OutcomeStatus, number> = { ...EMPTY_OUTCOMES }
    for (const submission of center.submissionRows) {
      if (submission.version.id !== item.version.id) continue
      for (const validation of submission.validations) outcomes[validation.outcome] += 1
    }
    const activeStatuses = item.bundles.map((bundle) => bundle.status)
    const bundleStatus: EvidenceStatus | null =
      activeStatuses.length === 0 ? null : activeStatuses.includes('ACTIVE') ? 'ACTIVE' : 'QUARANTINED'
    return {
      versionId: item.version.id,
      researchId: item.research?.id ?? null,
      researchName: item.research?.name ?? '未命名研究',
      versionStatus: item.version.status,
      bundleCount: item.bundles.length,
      bundleStatus,
      proofArtifactCount: item.bundles.reduce((total, bundle) => total + bundle.proofArtifactIds.length, 0),
      declaredValidationCount: item.bundles.reduce((total, bundle) => total + bundle.validationIds.length, 0),
      quality: item.qualityReport?.quality ?? null,
      readiness: item.qualityReport?.readiness ?? null,
      outcomes,
      verifiedConclusions: outcomes.SUPPORTED,
      retrievalTags: MEMORY_UNKNOWN,
      createdAt: item.version.created_at,
    } satisfies KnowledgeRow
  })
  return rows.sort((left, right) => desc(left.createdAt, right.createdAt))
}

export function summarizeKnowledgeRows(rows: KnowledgeRow[]): {
  conclusions: number
  evidenceBacked: number
  quarantined: number
  blockedQuality: number
} {
  return {
    conclusions: rows.reduce((total, row) => total + row.verifiedConclusions, 0),
    evidenceBacked: rows.filter((row) => row.bundleCount > 0).length,
    quarantined: rows.filter((row) => row.bundleStatus === 'QUARANTINED').length,
    blockedQuality: rows.filter((row) => row.quality === 'BLOCKED').length,
  }
}

// ---------------------------------------------------------------------------
// 研究經驗（SSOT 28）：策略成功與失敗經驗及條件
// ---------------------------------------------------------------------------

export type ExperienceVerdict = 'SUCCESS' | 'FAILURE' | 'ABORTED' | 'ACTIVE'

export const EXPERIENCE_VERDICT_LABELS: Record<ExperienceVerdict, string> = {
  SUCCESS: '成功',
  FAILURE: '失敗',
  ABORTED: '中止',
  ACTIVE: '進行中',
}

export function runVerdict(status: RunStatus): ExperienceVerdict {
  if (status === 'SUCCEEDED') return 'SUCCESS'
  if (status === 'FAILED') return 'FAILURE'
  if (status === 'CANCELLED') return 'ABORTED'
  return 'ACTIVE'
}

/** 凍結提交狀態一律經過標籤對照；讀不到投影時顯示「未取得」，不落回原始碼。 */
function submissionStatusLabel(finalEvaluation: FinalEvaluation | null): string {
  const status: SubmissionStatus | null = finalEvaluation?.status ?? null
  return status === null ? MEMORY_UNKNOWN : SUBMISSION_STATUS_LABELS[status]
}

export interface ExperienceEntry {
  runId: string
  runType: RunType
  status: RunStatus
  verdict: ExperienceVerdict
  outcome: OutcomeStatus | null
  stopReason: StopReason | null
  phase: RunPhase | null
  researchId: string | null
  researchName: string
  versionId: string | null
  /** 已揭露的執行條件：所屬版本的評估政策雜湊。 */
  condition: string
  /** 後端未提供經驗摘要或策略名稱。 */
  lesson: string
  createdAt: string
}

export function buildExperienceTimeline(center: MemoryCenter): ExperienceEntry[] {
  return center.runs.map((entry) => ({
    runId: entry.run.id,
    runType: entry.run.type,
    status: entry.run.status,
    verdict: runVerdict(entry.run.status),
    outcome: entry.run.outcome_status ?? null,
    stopReason: entry.run.stop_reason ?? null,
    phase: entry.run.phase ?? null,
    researchId: entry.research?.id ?? null,
    researchName: entry.research?.name ?? '未命名研究',
    versionId: entry.version?.id ?? null,
    condition: entry.version === null ? MEMORY_UNKNOWN : entry.version.evaluation_policy_hash,
    lesson: MEMORY_UNKNOWN,
    createdAt: entry.run.created_at,
  }))
}

export function summarizeExperience(entries: ExperienceEntry[]): Record<ExperienceVerdict, number> {
  const counts: Record<ExperienceVerdict, number> = { SUCCESS: 0, FAILURE: 0, ABORTED: 0, ACTIVE: 0 }
  for (const entry of entries) counts[entry.verdict] += 1
  return counts
}

// ---------------------------------------------------------------------------
// 失敗案例（SSOT 29）：否定證據、數值失敗與修復可能
// ---------------------------------------------------------------------------

export type FailureCategory =
  | 'RUN_FAILED'
  | 'SUBMISSION_FAILED'
  | 'FALSIFIED'
  | 'QUALITY_BLOCKED'
  | 'EVIDENCE_QUARANTINED'

export const FAILURE_CATEGORY_LABELS: Record<FailureCategory, string> = {
  RUN_FAILED: '任務失敗',
  SUBMISSION_FAILED: '提交評估失敗',
  FALSIFIED: '假設被否證',
  QUALITY_BLOCKED: '品質檢核未通過',
  EVIDENCE_QUARANTINED: '證據已隔離',
}

export interface FailureRow {
  key: string
  category: FailureCategory
  researchId: string | null
  researchName: string
  versionId: string | null
  sourceId: string
  reason: string
  details: string[]
  /** 後端未揭露修復建議。 */
  repair: string
  createdAt: string
}

export function buildFailureRows(center: MemoryCenter): FailureRow[] {
  const rows: FailureRow[] = []
  const versionById = new Map(center.versions.map((version) => [version.id, version] as const))

  for (const entry of center.runs) {
    if (entry.run.status !== 'FAILED') continue
    rows.push({
      key: `run:${entry.run.id}`,
      category: 'RUN_FAILED',
      researchId: entry.research?.id ?? null,
      researchName: entry.research?.name ?? '未命名研究',
      versionId: entry.version?.id ?? null,
      sourceId: entry.run.id,
      reason: entry.run.stop_reason === null || entry.run.stop_reason === undefined
        ? '後端未揭露停止理由'
        : STOP_REASON_LABELS[entry.run.stop_reason],
      details: [`任務型別：${RUN_TYPE_LABELS[entry.run.type]}`],
      repair: MEMORY_UNKNOWN,
      createdAt: entry.run.created_at,
    })
  }

  for (const submission of center.submissionRows) {
    if (submission.finalEvaluation?.status === 'FAILED') {
      rows.push({
        key: `submission:${submission.submissionId}`,
        category: 'SUBMISSION_FAILED',
        researchId: submission.research?.id ?? null,
        researchName: submission.research?.name ?? '未命名研究',
        versionId: submission.version.id,
        sourceId: submission.submissionId,
        reason: '最終評估狀態為 FAILED',
        details: [`指標版本：${submission.finalEvaluation.metricVersion}`],
        repair: MEMORY_UNKNOWN,
        createdAt: submission.version.created_at,
      })
    }

    for (const validation of submission.validations) {
      if (validation.outcome !== 'FALSIFIED') continue
      const reasons = Object.entries(validation.metricReasons).map(
        ([name, code]) => `${name}：${describeMetricReason(code)}`,
      )
      rows.push({
        key: `validation:${validation.id}`,
        category: 'FALSIFIED',
        researchId: submission.research?.id ?? null,
        researchName: submission.research?.name ?? '未命名研究',
        versionId: submission.version.id,
        sourceId: validation.id,
        reason: OUTCOME_DETAILS[validation.outcome],
        details: [
          `切分角色：${validation.splitRole}`,
          `失敗列 / 有效列 / 選定列：${String(validation.failedCount)} / ${String(validation.validCount)} / ${String(validation.selectedCount)}`,
          ...reasons,
        ],
        repair: MEMORY_UNKNOWN,
        createdAt: validation.createdAt,
      })
    }
  }

  for (const item of center.evidenceItems) {
    if (item.qualityReport?.quality === 'BLOCKED') {
      rows.push({
        key: `quality:${item.version.id}`,
        category: 'QUALITY_BLOCKED',
        researchId: item.research?.id ?? null,
        researchName: item.research?.name ?? '未命名研究',
        versionId: item.version.id,
        sourceId: item.version.quality_report_id ?? item.version.id,
        reason: item.qualityReport.blockingCode ?? '品質檢核未通過，後端未揭露阻擋代碼',
        details: item.qualityReport.remaining.map((code) => `待完成：${code}`),
        repair: MEMORY_UNKNOWN,
        createdAt: item.version.created_at,
      })
    }

    for (const bundle of item.bundles) {
      if (bundle.status !== 'QUARANTINED') continue
      rows.push({
        key: `bundle:${bundle.id}`,
        category: 'EVIDENCE_QUARANTINED',
        researchId: item.research?.id ?? null,
        researchName: item.research?.name ?? '未命名研究',
        versionId: item.version.id,
        sourceId: bundle.id,
        reason: '證據包狀態為 QUARANTINED',
        details: [`版本：${versionById.get(item.version.id)?.id ?? item.version.id}`],
        repair: MEMORY_UNKNOWN,
        createdAt: item.version.created_at,
      })
    }
  }

  return rows.sort((left, right) => desc(left.createdAt, right.createdAt))
}

export function summarizeFailures(rows: FailureRow[]): Record<FailureCategory, number> {
  const counts: Record<FailureCategory, number> = {
    RUN_FAILED: 0,
    SUBMISSION_FAILED: 0,
    FALSIFIED: 0,
    QUALITY_BLOCKED: 0,
    EVIDENCE_QUARANTINED: 0,
  }
  for (const row of rows) counts[row.category] += 1
  return counts
}

// ---------------------------------------------------------------------------
// 假設恢復（SSOT 30）：恢復條件、重新評估與候選佇列
// ---------------------------------------------------------------------------

export interface RecoveryRow {
  versionId: string
  researchId: string | null
  researchName: string
  versionStatus: ResearchVersionStatus
  /** 該版本對應到的失敗類別。 */
  blockers: FailureCategory[]
  evidenceReadiness: string
  reEvaluation: string
  searchRunCount: number
  /** 後端未揭露恢復條件。 */
  condition: string
  createdAt: string
}

const EVIDENCE_READINESS_LABELS: Record<EvidenceStatus, string> = {
  ACTIVE: '證據包有效',
  QUARANTINED: '證據包已隔離',
}

/** 只有實際出現失敗的版本才進入恢復清單；恢復條件後端未揭露，一律標示未取得。 */
export function buildRecoveryRows(center: MemoryCenter, failures: FailureRow[]): RecoveryRow[] {
  const blockersByVersion = new Map<string, Set<FailureCategory>>()
  for (const row of failures) {
    if (row.versionId === null) continue
    const set = blockersByVersion.get(row.versionId) ?? new Set<FailureCategory>()
    set.add(row.category)
    blockersByVersion.set(row.versionId, set)
  }

  const rows: RecoveryRow[] = []
  for (const version of center.versions) {
    const blockers = blockersByVersion.get(version.id)
    if (blockers === undefined) continue

    const item = center.evidenceItems.find((entry) => entry.version.id === version.id) ?? null
    const submissions = center.submissionRows.filter((entry) => entry.version.id === version.id)
    const searchRunCount = center.runs.filter(
      (entry) => entry.version?.id === version.id && entry.run.type === 'SEARCH',
    ).length

    const evidenceReadiness =
      item === null || item.bundles.length === 0
        ? MEMORY_UNKNOWN
        : item.bundles.some((bundle) => bundle.status === 'ACTIVE')
          ? EVIDENCE_READINESS_LABELS.ACTIVE
          : EVIDENCE_READINESS_LABELS.QUARANTINED

    const reEvaluation =
      submissions.length === 0
        ? '尚無凍結提交'
        : submissions
            .map((entry) => submissionStatusLabel(entry.finalEvaluation))
            .filter((status, index, all) => all.indexOf(status) === index)
            .join('、')

    rows.push({
      versionId: version.id,
      researchId: version.research_id,
      researchName: center.researches.find((row) => row.id === version.research_id)?.name ?? '未命名研究',
      versionStatus: version.status,
      blockers: [...blockers],
      evidenceReadiness,
      reEvaluation,
      searchRunCount,
      condition: MEMORY_UNKNOWN,
      createdAt: version.created_at,
    })
  }

  return rows.sort((left, right) => desc(left.createdAt, right.createdAt))
}

// ---------------------------------------------------------------------------
// 知識演化（SSOT 31）：版本、修正、撤回與證據更新
// ---------------------------------------------------------------------------

export type EvolutionNodeKind = 'RESEARCH' | 'VERSION' | 'EVIDENCE' | 'QUALITY' | 'SUBMISSION'

export const EVOLUTION_NODE_LABELS: Record<EvolutionNodeKind, string> = {
  RESEARCH: '研究',
  VERSION: '版本',
  EVIDENCE: '證據包',
  QUALITY: '品質報告',
  SUBMISSION: '凍結提交',
}

export interface EvolutionNode {
  id: string
  kind: EvolutionNodeKind
  label: string
  status: string
}

export interface EvolutionEdge {
  from: string
  to: string
  label: string
}

export interface EvolutionGraph {
  nodes: EvolutionNode[]
  edges: EvolutionEdge[]
}

/** 知識演化只依實際實體與其引用關係建圖；節點不存在時不補造節點。 */
export function buildEvolutionGraph(center: MemoryCenter): EvolutionGraph {
  const nodes = new Map<string, EvolutionNode>()
  const edges: EvolutionEdge[] = []

  const addNode = (node: EvolutionNode): void => {
    if (!nodes.has(node.id)) nodes.set(node.id, node)
  }

  for (const research of center.researches) {
    addNode({ id: `research:${research.id}`, kind: 'RESEARCH', label: research.name, status: '存在' })
  }

  for (const item of center.evidenceItems) {
    const versionId = `version:${item.version.id}`
    addNode({
      id: versionId,
      kind: 'VERSION',
      label: item.version.id,
      status: VERSION_STATUS_LABELS[item.version.status],
    })
    if (item.research !== null) {
      addNode({ id: `research:${item.research.id}`, kind: 'RESEARCH', label: item.research.name, status: '存在' })
      edges.push({ from: `research:${item.research.id}`, to: versionId, label: '包含版本' })
    }

    if (item.unreadable) {
      addNode({
        id: `quality:${item.version.id}:unreadable`,
        kind: 'QUALITY',
        label: '品質報告無法解析（契約不符）',
        status: '不可讀',
      })
      edges.push({ from: versionId, to: `quality:${item.version.id}:unreadable`, label: '品質報告' })
    }

    if (item.qualityReport !== null) {
      const qualityId = `quality:${item.version.id}`
      addNode({
        id: qualityId,
        kind: 'QUALITY',
        label: `品質檢核 ${item.qualityReport.quality}`,
        status: item.qualityReport.readiness,
      })
      edges.push({ from: versionId, to: qualityId, label: '品質報告' })
    }

    for (const bundle of item.bundles) {
      const bundleId = `bundle:${bundle.id}`
      addNode({ id: bundleId, kind: 'EVIDENCE', label: bundle.id, status: bundle.status })
      edges.push({ from: versionId, to: bundleId, label: '證據' })
    }
  }

  for (const submission of center.submissionRows) {
    const versionId = `version:${submission.version.id}`
    addNode({
      id: versionId,
      kind: 'VERSION',
      label: submission.version.id,
      status: VERSION_STATUS_LABELS[submission.version.status],
    })
    if (submission.research !== null) {
      addNode({
        id: `research:${submission.research.id}`,
        kind: 'RESEARCH',
        label: submission.research.name,
        status: '存在',
      })
      edges.push({ from: `research:${submission.research.id}`, to: versionId, label: '包含版本' })
    }
    const submissionId = `submission:${submission.submissionId}`
    addNode({
      id: submissionId,
      kind: 'SUBMISSION',
      label: submission.submissionId,
      status: submission.finalEvaluation?.status ?? MEMORY_UNKNOWN,
    })
    edges.push({ from: versionId, to: submissionId, label: '凍結提交' })
  }

  const uniqueEdges = edges.filter(
    (edge, index, all) => all.findIndex((row) => row.from === edge.from && row.to === edge.to) === index,
  )

  return { nodes: [...nodes.values()], edges: uniqueEdges }
}

export interface EvolutionEntry {
  versionId: string
  researchId: string | null
  researchName: string
  revision: number
  versionStatus: ResearchVersionStatus
  evidenceStatus: EvidenceStatus | null
  quality: QualityOutcome | null
  submissionCount: number
  submissionStatus: string
  createdAt: string
}

export function buildEvolutionTimeline(center: MemoryCenter): EvolutionEntry[] {
  const rows: EvolutionEntry[] = center.versions.map((version) => {
    const item = center.evidenceItems.find((entry) => entry.version.id === version.id) ?? null
    const submissions = center.submissionRows.filter((entry) => entry.version.id === version.id)
    const statuses = submissions.map((entry) => submissionStatusLabel(entry.finalEvaluation))
    return {
      versionId: version.id,
      researchId: version.research_id,
      researchName: center.researches.find((row) => row.id === version.research_id)?.name ?? '未命名研究',
      revision: version.revision,
      versionStatus: version.status,
      evidenceStatus:
        item === null || item.bundles.length === 0
          ? null
          : item.bundles.some((bundle) => bundle.status === 'ACTIVE')
            ? 'ACTIVE'
            : 'QUARANTINED',
      quality: item?.qualityReport?.quality ?? null,
      submissionCount: submissions.length,
      submissionStatus: statuses.length === 0 ? '尚無凍結提交' : [...new Set(statuses)].join('、'),
      createdAt: version.created_at,
    }
  })
  return rows.sort((left, right) => desc(left.createdAt, right.createdAt))
}

export function summarizeEvolution(center: MemoryCenter): {
  versions: number
  revisions: number
  quarantinedEvidence: number
  withdrawn: number
} {
  const revisions = center.versions.reduce((total, version) => total + version.revision, 0)
  const quarantinedEvidence = center.evidenceItems.reduce(
    (total, item) => total + item.bundles.filter((bundle) => bundle.status === 'QUARANTINED').length,
    0,
  )
  const withdrawn = center.versions.filter(
    (version) => version.status === 'FAILED' || version.status === 'CANCELLED',
  ).length
  return { versions: center.versions.length, revisions, quarantinedEvidence, withdrawn }
}
