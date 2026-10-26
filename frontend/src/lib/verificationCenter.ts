import type { Research, ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../api/research'
import type { Run } from '../api/runs'
import type { FinalEvaluation } from './finalEvaluation'
import type { ValidationRun } from './evaluation'

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

export interface VerificationCenter {
  metrics: VerificationMetric[]
  runs: Run[]
  evidenceRows: VerificationEvidenceRow[]
  submissionRows: VerificationSubmissionRow[]
}

export interface VerificationDeps {
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  getFinalEvaluation: (submissionId: string) => Promise<FinalEvaluation | null>
  getValidationRun: (validationId: string) => Promise<ValidationRun | null>
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
  }
}
