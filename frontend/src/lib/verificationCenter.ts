import type { Artifact } from '../api/artifacts'
import type { Research, ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../api/research'
import type { Run } from '../api/runs'
import type { FinalEvaluation } from './finalEvaluation'
import { parseEvidenceBundle, parseQualityReport, type EvidenceBundle, type QualityReport } from './evidence'
import type { EmpiricalLevel, OutcomeStatus, ProofLevel, SplitRole, ValidationRun } from './evaluation'

/** 後端未回報的欄位一律顯示這個字串，不以 0 或推測值代替。 */
export const VERIFICATION_UNKNOWN = '未取得'

/** 誤差與證據矩陣的固定欄序；缺欄以「未取得」呈現，不省略。 */
export const SPLIT_ROLES: readonly SplitRole[] = ['FIT', 'DEVELOPMENT', 'FINAL_TEST']

export const SPLIT_ROLE_LABELS: Record<SplitRole, string> = {
  FIT: 'fit',
  DEVELOPMENT: 'development',
  FINAL_TEST: 'final_test',
}

export interface VerificationMetric {
  label: string
  value: string
  tone: 'good' | 'warn' | 'bad' | 'neutral'
  detail: string
}

export interface VerificationEvidenceRow {
  research: Research | null
  version: ResearchVersion
}

export interface VerificationSubmissionRow {
  research: Research | null
  version: ResearchVersion
  submissionId: string
  finalEvaluation: FinalEvaluation | null
  validations: ValidationRun[]
}

/** 一個研究版本的證據面：證據包與品質報告都只保留契約可解析的內容。 */
export interface VerificationEvidenceItem {
  research: Research | null
  version: ResearchVersion
  bundles: EvidenceBundle[]
  qualityReport: QualityReport | null
  /** 版本宣告了證據包或品質報告，但沒有任何一份可解析。 */
  unreadable: boolean
}

export interface VerificationCenter {
  metrics: VerificationMetric[]
  runs: Run[]
  evidenceRows: VerificationEvidenceRow[]
  submissionRows: VerificationSubmissionRow[]
  evidenceItems: VerificationEvidenceItem[]
  /** 證明產物的 metadata；抓不到的識別碼不會出現在這裡，由畫面顯示「未取得」。 */
  proofArtifacts: Record<string, Artifact>
}

export interface VerificationDeps {
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  getFinalEvaluation: (submissionId: string) => Promise<FinalEvaluation | null>
  getValidationRun: (validationId: string) => Promise<ValidationRun | null>
  getEvidenceBundle: (bundleId: string) => Promise<unknown>
  getQualityReport: (artifactId: string) => Promise<unknown>
  getArtifact: (artifactId: string) => Promise<Artifact>
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

export async function loadVerificationCenter(deps: VerificationDeps): Promise<VerificationCenter> {
  const researchPage = await safe(deps.listResearches(12), { items: [], next_cursor: null } satisfies ResearchPage)
  const researches = researchPage.items

  const versionEntries = await Promise.all(
    researches.map(async (research) => [
      research.id,
      (await safe(deps.listResearchVersions(research.id, 5), {
        items: [],
        next_cursor: null,
      } satisfies ResearchVersionPage)).items,
    ] as const),
  )
  const versionsByResearch = Object.fromEntries(versionEntries)
  const recentVersions = takeRecent(Object.values(versionsByResearch).flat(), 10)

  const runPages = await Promise.all(
    recentVersions.map(async (version) =>
      (await safe(deps.listResearchVersionRuns(version.id, 8), {
        items: [],
        next_cursor: null,
      } satisfies RunPage)).items,
    ),
  )
  const runs = takeRecent(runPages.flat(), 16)

  const evidenceRows = recentVersions
    .filter((version) => version.evidence_bundle_ids.length > 0 || version.quality_report_id !== null)
    .map((version) => ({
      research: researches.find((row) => row.id === version.research_id) ?? null,
      version,
    }))

  const submissionRows: VerificationSubmissionRow[] = []
  for (const version of recentVersions) {
    const research = researches.find((row) => row.id === version.research_id) ?? null
    for (const submissionId of version.frozen_submission_ids) {
      const finalEvaluation = await deps.getFinalEvaluation(submissionId)
      const validationIds = [...new Set((finalEvaluation?.slots ?? []).flatMap((slot) => (slot.validationRunId === null ? [] : [slot.validationRunId])))]
      const validations = (
        await Promise.all(validationIds.map(async (id) => await deps.getValidationRun(id)))
      ).filter((row): row is ValidationRun => row !== null)

      submissionRows.push({
        research,
        version,
        submissionId,
        finalEvaluation,
        validations,
      })
    }
  }

  const activeRuns = runs.filter((row) => ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(row.status)).length
  const failedRuns = runs.filter((row) => row.status === 'FAILED').length
  const successfulEvaluations = submissionRows.filter((row) => row.finalEvaluation?.status === 'EVALUATED').length

  const evidenceItems: VerificationEvidenceItem[] = []
  const proofArtifactIds = new Set<string>()

  for (const version of recentVersions) {
    if (version.evidence_bundle_ids.length === 0 && version.quality_report_id === null) continue
    const research = researches.find((row) => row.id === version.research_id) ?? null
    const bundles: EvidenceBundle[] = []
    for (const bundleId of version.evidence_bundle_ids) {
      const parsed = await safe(deps.getEvidenceBundle(bundleId).then(parseEvidenceBundle), null)
      if (parsed === null) continue
      bundles.push(parsed)
      for (const artifactId of parsed.proofArtifactIds) proofArtifactIds.add(artifactId)
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

  const proofArtifacts: Record<string, Artifact> = {}
  await Promise.all(
    [...proofArtifactIds].map(async (artifactId) => {
      const artifact = await safe(deps.getArtifact(artifactId), null)
      if (artifact !== null) proofArtifacts[artifactId] = artifact
    }),
  )

  return {
    metrics: [
      {
        label: '最近任務',
        value: String(runs.length),
        tone: runs.length > 0 ? 'good' : 'warn',
        detail: '最近研究版本中可讀到的任務投影數量。',
      },
      {
        label: '進行中任務',
        value: String(activeRuns),
        tone: activeRuns > 0 ? 'good' : 'warn',
        detail: '狀態為 queued/running/cancel_requested 的任務數量。',
      },
      {
        label: '失敗任務',
        value: String(failedRuns),
        tone: failedRuns > 0 ? 'bad' : 'good',
        detail: '最近任務中狀態為 FAILED 的數量。',
      },
      {
        label: '已評估提交',
        value: String(successfulEvaluations),
        tone: successfulEvaluations > 0 ? 'good' : 'warn',
        detail: '最近 frozen submission 中已取得 final evaluation 的數量。',
      },
    ],
    runs,
    evidenceRows,
    submissionRows,
    evidenceItems,
    proofArtifacts,
  }
}

export interface VerificationMatrixCell {
  validationId: string
  splitRole: SplitRole
  outcome: OutcomeStatus
  empiricalLevel: EmpiricalLevel
  proofLevel: ProofLevel
  mae: number | null
  rmse: number | null
  validCoverage: number
}

export interface VerificationMatrixRow {
  submissionId: string
  researchName: string
  versionId: string
  cells: VerificationMatrixCell[]
  /** 沒有任何 validation run 的切分角色；必須在矩陣上明示缺欄。 */
  missingRoles: SplitRole[]
}

/**
 * 多面向證據矩陣：只依已讀到的 validation run 建立，每個 submission 一列、切分角色為欄。
 * 沒有 validation run 的角色列為缺欄，不以 0 或合成值補上。
 */
export function buildEvidenceMatrix(rows: VerificationSubmissionRow[]): VerificationMatrixRow[] {
  return rows.map((row) => {
    const cells: VerificationMatrixCell[] = row.validations.map((validation) => ({
      validationId: validation.id,
      splitRole: validation.splitRole,
      outcome: validation.outcome,
      empiricalLevel: validation.empiricalLevel,
      proofLevel: validation.proofLevel,
      mae: validation.mae,
      rmse: validation.rmse,
      validCoverage: validation.validCoverage,
    }))
    const present = new Set(cells.map((cell) => cell.splitRole))
    return {
      submissionId: row.submissionId,
      researchName: row.research?.name ?? '未命名研究',
      versionId: row.version.id,
      cells,
      missingRoles: SPLIT_ROLES.filter((role) => !present.has(role)),
    }
  })
}
