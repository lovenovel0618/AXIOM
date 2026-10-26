import type { Candidate, CandidatePage, EquationVersion, FitRun } from '../api/candidates'
import type { Research, ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../api/research'
import type { Run } from '../api/runs'

export interface DiscoverySearchRun {
  run: Run
  research: Research | null
  version: ResearchVersion | null
  candidates: Candidate[]
}

export interface DiscoveriesMetric {
  label: string
  value: string
  tone: 'good' | 'warn' | 'bad' | 'neutral'
  detail: string
}

export interface DiscoveriesCenter {
  metrics: DiscoveriesMetric[]
  searchRuns: DiscoverySearchRun[]
  recentVersions: ResearchVersion[]
}

export interface DiscoveriesDeps {
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  listRunCandidates: (runId: string, limit: number) => Promise<CandidatePage>
  getEquationVersion: (id: string) => Promise<EquationVersion>
  getFitRun: (id: string) => Promise<FitRun>
}

export interface CandidateDetailBundle {
  equations: Record<string, EquationVersion>
  fits: Record<string, FitRun>
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

export async function loadDiscoveriesCenter(deps: DiscoveriesDeps): Promise<DiscoveriesCenter> {
  const researchPage = await safe(deps.listResearches(12), { items: [], next_cursor: null } satisfies ResearchPage)
  const researches = researchPage.items

  const researchEntries = await Promise.all(
    researches.map(async (research) => [
      research.id,
      (await safe(deps.listResearchVersions(research.id, 5), {
        items: [],
        next_cursor: null,
      } satisfies ResearchVersionPage)).items,
    ] as const),
  )
  const versionsByResearch = Object.fromEntries(researchEntries)
  const recentVersions = takeRecent(Object.values(versionsByResearch).flat(), 10)

  const searchRuns: DiscoverySearchRun[] = []
  for (const version of recentVersions) {
    const research = researches.find((row) => row.id === version.research_id) ?? null
    const runPage = await safe(deps.listResearchVersionRuns(version.id, 10), {
      items: [],
      next_cursor: null,
    } satisfies RunPage)
    const rows = runPage.items
      .filter((run) => run.type === 'SEARCH')
      .sort((left, right) => desc(left.created_at, right.created_at))

    for (const run of rows) {
      const candidatePage = await safe(deps.listRunCandidates(run.id, 20), {
        items: [],
        next_cursor: null,
      } satisfies CandidatePage)
      searchRuns.push({
        run,
        research,
        version,
        candidates: candidatePage.items,
      })
    }
  }

  const loadedCandidates = searchRuns.reduce((total, row) => total + row.candidates.length, 0)
  const runsWithCandidates = searchRuns.filter((row) => row.candidates.length > 0).length
  const versionsWithFrozen = recentVersions.filter((row) => row.frozen_submission_ids.length > 0).length

  return {
    metrics: [
      {
        label: 'SEARCH 任務',
        value: String(searchRuns.length),
        tone: searchRuns.length > 0 ? 'good' : 'warn',
        detail: '最近研究版本中可讀取的 SEARCH 任務數量。',
      },
      {
        label: '已載入候選',
        value: String(loadedCandidates),
        tone: loadedCandidates > 0 ? 'good' : 'warn',
        detail: '目前已實際抓到的候選頁面總和，不推測未載入頁面。',
      },
      {
        label: '有分支任務',
        value: String(runsWithCandidates),
        tone: runsWithCandidates > 0 ? 'good' : 'warn',
        detail: '至少有一條候選的 SEARCH 任務數量。',
      },
      {
        label: '已凍結版本',
        value: String(versionsWithFrozen),
        tone: versionsWithFrozen > 0 ? 'good' : 'warn',
        detail: '最近研究版本中已進入 frozen submission 的數量。',
      },
    ],
    searchRuns: searchRuns.sort((left, right) => desc(left.run.created_at, right.run.created_at)),
    recentVersions,
  }
}

export async function loadCandidateDetails(
  deps: DiscoveriesDeps,
  candidates: Candidate[],
  existing: CandidateDetailBundle,
): Promise<CandidateDetailBundle> {
  const next: CandidateDetailBundle = {
    equations: { ...existing.equations },
    fits: { ...existing.fits },
  }

  const equationIds = [...new Set(candidates.map((row) => row.equation_version_id))]
  const fitIds = [...new Set(candidates.flatMap((row) => row.fit_run_ids))]

  await Promise.all(
    equationIds.map(async (id) => {
      if (next.equations[id] !== undefined) return
      try {
        next.equations[id] = await deps.getEquationVersion(id)
      } catch {
        // 單筆缺失保持空白，不用推測公式內容。
      }
    }),
  )

  await Promise.all(
    fitIds.map(async (id) => {
      if (next.fits[id] !== undefined) return
      try {
        next.fits[id] = await deps.getFitRun(id)
      } catch {
        // 單筆缺失保持空白，不用推測擬合參數。
      }
    }),
  )

  return next
}
