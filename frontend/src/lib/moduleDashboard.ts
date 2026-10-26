import type { CandidatePage } from '../api/candidates'
import type { Dataset, DatasetPage, DatasetVersion, VersionPage } from '../api/datasets'
import type { Research, ResearchPage, ResearchVersion, ResearchVersionPage, RunPage } from '../api/research'
import type { Run } from '../api/runs'
import type { HealthStatus } from '../health'

export type ModuleName =
  | 'overview'
  | 'discoveries'
  | 'verification'
  | 'memory'
  | 'model'
  | 'training'
  | 'settings'

export interface ModuleAction {
  label: string
  to: { name: string; params?: Record<string, string> }
}

export interface ModuleMetric {
  label: string
  value: string
  tone: 'good' | 'warn' | 'bad' | 'neutral'
  detail: string
}

export interface ModuleListItem {
  title: string
  subtitle: string
  badge: string
  to?: { name: string; params?: Record<string, string> }
}

export interface ModuleList {
  title: string
  empty: string
  items: ModuleListItem[]
}

export interface ModuleDashboard {
  section: string
  title: string
  summary: string
  actions: ModuleAction[]
  metrics: ModuleMetric[]
  lists: ModuleList[]
  note: string
}

interface Snapshot {
  readiness: HealthStatus
  researches: Research[]
  researchVersionsByResearch: Record<string, ResearchVersion[]>
  recentVersions: ResearchVersion[]
  runs: Run[]
  datasets: Dataset[]
  datasetVersionsByDataset: Record<string, DatasetVersion[]>
  candidateGroups: Record<string, CandidatePage['items']>
}

export interface ModuleDashboardDeps {
  checkReadiness: () => Promise<HealthStatus>
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  listDatasets: (limit: number) => Promise<DatasetPage>
  listVersions: (datasetId: string, limit: number) => Promise<VersionPage>
  listRunCandidates: (runId: string, limit: number) => Promise<CandidatePage>
}

const ACTIVE_VERSION_STATUSES = new Set(['VALIDATING', 'READY', 'QUEUED', 'RUNNING'])
const ACTIVE_RUN_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'])

function desc(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? 1 : -1
}

function takeRecent<T extends { created_at: string }>(rows: T[], limit: number): T[] {
  return [...rows].sort((left, right) => desc(left.created_at, right.created_at)).slice(0, limit)
}

function latestVersion(rows: ResearchVersion[]): ResearchVersion | null {
  return takeRecent(rows, 1)[0] ?? null
}

function latestDatasetVersion(rows: DatasetVersion[]): DatasetVersion | null {
  return takeRecent(rows, 1)[0] ?? null
}

function countLoadedCandidates(groups: Record<string, CandidatePage['items']>): number {
  return Object.values(groups).reduce((total, rows) => total + rows.length, 0)
}

async function safe<T>(task: Promise<T>, fallback: T): Promise<T> {
  try {
    return await task
  } catch {
    return fallback
  }
}

async function buildSnapshot(deps: ModuleDashboardDeps): Promise<Snapshot> {
  const [readiness, researchPage, datasetPage] = await Promise.all([
    safe(deps.checkReadiness(), 'unavailable' satisfies HealthStatus),
    safe(deps.listResearches(12), { items: [], next_cursor: null } satisfies ResearchPage),
    safe(deps.listDatasets(12), { items: [], next_cursor: null } satisfies DatasetPage),
  ])

  const researches = researchPage.items
  const datasets = datasetPage.items

  const researchVersionEntries = await Promise.all(
    researches.map(async (research) => [
      research.id,
      (await safe(deps.listResearchVersions(research.id, 5), {
        items: [],
        next_cursor: null,
      } satisfies ResearchVersionPage)).items,
    ] as const),
  )
  const researchVersionsByResearch = Object.fromEntries(researchVersionEntries)

  const recentVersions = takeRecent(
    Object.values(researchVersionsByResearch).flat(),
    6,
  )

  const runEntries = await Promise.all(
    recentVersions.map(async (version) =>
      (await safe(deps.listResearchVersionRuns(version.id, 8), {
        items: [],
        next_cursor: null,
      } satisfies RunPage)).items,
    ),
  )
  const runs = takeRecent(runEntries.flat(), 12)

  const datasetVersionEntries = await Promise.all(
    datasets.map(async (dataset) => [
      dataset.id,
      (await safe(deps.listVersions(dataset.id, 5), {
        items: [],
        next_cursor: null,
      } satisfies VersionPage)).items,
    ] as const),
  )
  const datasetVersionsByDataset = Object.fromEntries(datasetVersionEntries)

  const searchRuns = runs.filter((row) => row.type === 'SEARCH').slice(0, 4)
  const candidateEntries = await Promise.all(
    searchRuns.map(async (run) => [
      run.id,
      (await safe(deps.listRunCandidates(run.id, 20), {
        items: [],
        next_cursor: null,
      } satisfies CandidatePage)).items,
    ] as const),
  )
  const candidateGroups = Object.fromEntries(candidateEntries)

  return {
    readiness,
    researches,
    researchVersionsByResearch,
    recentVersions,
    runs,
    datasets,
    datasetVersionsByDataset,
    candidateGroups,
  }
}

function readinessMetric(readiness: HealthStatus): ModuleMetric {
  return {
    label: '服務狀態',
    value: readiness === 'ready' ? '已就緒' : '異常',
    tone: readiness === 'ready' ? 'good' : 'bad',
    detail: '根據 `/health/ready/` 即時回報，不做前端推測。',
  }
}

function versionBadge(version: ResearchVersion | null): string {
  return version?.status ?? 'NONE'
}

function datasetBadge(version: DatasetVersion | null): string {
  return version === null ? 'NONE' : `${version.status} / ${version.format}`
}

function routeForResearch(research: Research): ModuleListItem['to'] {
  return { name: 'researches', params: { id: research.id } }
}

function routeForRun(run: Run): ModuleListItem['to'] {
  return { name: 'run', params: { id: run.id } }
}

function routeForArtifact(id: string): ModuleListItem['to'] {
  return { name: 'artifact', params: { id } }
}

function buildOverview(snapshot: Snapshot): ModuleDashboard {
  const latestVersions = snapshot.researches.map((research) => latestVersion(snapshot.researchVersionsByResearch[research.id] ?? []))
  const analyzableDatasets = snapshot.datasets.filter((dataset) => {
    const version = latestDatasetVersion(snapshot.datasetVersionsByDataset[dataset.id] ?? [])
    return version?.status === 'AVAILABLE' && version.structure_preview_artifact_id !== null
  }).length

  return {
    section: '總覽',
    title: '系統總覽',
    summary: '集中查看研究、數據與任務的即時概況。',
    actions: [
      { label: '前往研究', to: { name: 'researches' } },
      { label: '前往資料', to: { name: 'datasets' } },
    ],
    metrics: [
      readinessMetric(snapshot.readiness),
      {
        label: '研究容器',
        value: String(snapshot.researches.length),
        tone: 'neutral',
        detail: '依目前前台可讀取的研究容器清單統計。',
      },
      {
        label: '活躍版本',
        value: String(latestVersions.filter((row) => row !== null && ACTIVE_VERSION_STATUSES.has(row.status)).length),
        tone: 'good',
        detail: '以各研究最新版本是否處於 validating/ready/queued/running 判定。',
      },
      {
        label: '可分析資料集',
        value: String(analyzableDatasets),
        tone: analyzableDatasets > 0 ? 'good' : 'warn',
        detail: '最新資料版本可用且具有結構預覽的資料集數量。',
      },
    ],
    lists: [
      {
        title: '最近研究',
        empty: '目前沒有研究容器。',
        items: takeRecent(snapshot.researches, 6).map((research) => ({
          title: research.name,
          subtitle: research.id,
          badge: versionBadge(latestVersion(snapshot.researchVersionsByResearch[research.id] ?? [])),
          to: routeForResearch(research),
        })),
      },
      {
        title: '最近資料集',
        empty: '目前沒有資料集。',
        items: takeRecent(snapshot.datasets, 6).map((dataset) => ({
          title: dataset.name,
          subtitle: dataset.id,
          badge: datasetBadge(latestDatasetVersion(snapshot.datasetVersionsByDataset[dataset.id] ?? [])),
          to: { name: 'datasets' },
        })),
      },
      {
        title: '最近任務',
        empty: '目前沒有最近任務可顯示。',
        items: snapshot.runs.slice(0, 6).map((run) => ({
          title: `${run.type} / ${run.status}`,
          subtitle: run.created_at,
          badge: run.id,
          to: routeForRun(run),
        })),
      },
    ],
    note: '總覽只顯示前台目前能直接讀取的研究、資料集與任務投影；沒有後端欄位的內容不補猜。',
  }
}

function buildDiscoveries(snapshot: Snapshot): ModuleDashboard {
  const candidateRows = Object.entries(snapshot.candidateGroups).flatMap(([runId, rows]) =>
    rows.map((candidate) => ({ runId, candidate })),
  )
  const versionsWithFrozen = snapshot.recentVersions.filter((version) => version.frozen_submission_ids.length > 0).length
  const versionsWithEvidence = snapshot.recentVersions.filter((version) => version.evidence_bundle_ids.length > 0).length

  return {
    section: '發現',
    title: '發現中心',
    summary: '從最近 SEARCH 任務與候選分支查看目前的假設生成狀態。',
    actions: [{ label: '回研究清單', to: { name: 'researches' } }],
    metrics: [
      {
        label: '最近 SEARCH',
        value: String(snapshot.runs.filter((row) => row.type === 'SEARCH').length),
        tone: 'neutral',
        detail: '取自最近研究版本的 SEARCH 任務清單。',
      },
      {
        label: '最近候選',
        value: String(countLoadedCandidates(snapshot.candidateGroups)),
        tone: countLoadedCandidates(snapshot.candidateGroups) > 0 ? 'good' : 'warn',
        detail: '只統計目前已讀取的 SEARCH 候選頁面。',
      },
      {
        label: '已凍結版本',
        value: String(versionsWithFrozen),
        tone: versionsWithFrozen > 0 ? 'good' : 'warn',
        detail: '最近研究版本中已產生 frozen submission 的數量。',
      },
      {
        label: '具證據版本',
        value: String(versionsWithEvidence),
        tone: versionsWithEvidence > 0 ? 'good' : 'warn',
        detail: '最近研究版本中已掛上 evidence bundle 的數量。',
      },
    ],
    lists: [
      {
        title: 'SEARCH 任務',
        empty: '最近沒有 SEARCH 任務。',
        items: snapshot.runs
          .filter((row) => row.type === 'SEARCH')
          .slice(0, 6)
          .map((run) => ({
            title: `${run.type} / ${run.status}`,
            subtitle: run.created_at,
            badge: run.id,
            to: routeForRun(run),
          })),
      },
      {
        title: '候選分支',
        empty: '最近沒有已載入的候選。',
        items: candidateRows.slice(0, 8).map(({ runId, candidate }) => ({
          title: `候選 #${candidate.development_rank ?? 'NA'} / ${candidate.validation_status}`,
          subtitle: `${candidate.source} / ${candidate.id}`,
          badge: runId,
          to: { name: 'run', params: { id: runId } },
        })),
      },
      {
        title: '研究版本',
        empty: '最近沒有研究版本。',
        items: snapshot.recentVersions.slice(0, 6).map((version) => ({
          title: `${version.purpose} / ${version.status}`,
          subtitle: version.id,
          badge: `${version.frozen_submission_ids.length} 凍結 / ${version.evidence_bundle_ids.length} 證據`,
          to: { name: 'researches', params: { id: version.research_id } },
        })),
      },
    ],
    note: '發現中心目前聚焦最近 SEARCH 與候選分支；全域公式庫與更深的比較介面仍待後端與前端後續接線。',
  }
}

function buildVerification(snapshot: Snapshot): ModuleDashboard {
  const failedRuns = snapshot.runs.filter((row) => row.status === 'FAILED').length
  const activeRuns = snapshot.runs.filter((row) => ACTIVE_RUN_STATUSES.has(row.status)).length
  const evidenceBundles = snapshot.recentVersions.reduce((total, version) => total + version.evidence_bundle_ids.length, 0)
  const qualityArtifacts = snapshot.recentVersions.filter((version) => version.quality_report_id !== null).length

  return {
    section: '驗證',
    title: '驗證中心',
    summary: '整理最近任務、證據與最終評估前置狀態。',
    actions: [{ label: '前往研究', to: { name: 'researches' } }],
    metrics: [
      {
        label: '最近任務',
        value: String(snapshot.runs.length),
        tone: 'neutral',
        detail: '依最近研究版本實際拉到的 run 投影數量。',
      },
      {
        label: '進行中任務',
        value: String(activeRuns),
        tone: activeRuns > 0 ? 'good' : 'warn',
        detail: '任務狀態為 queued/running/cancel_requested。',
      },
      {
        label: '失敗任務',
        value: String(failedRuns),
        tone: failedRuns > 0 ? 'bad' : 'good',
        detail: '最近任務中狀態為 FAILED 的數量。',
      },
      {
        label: '證據掛載',
        value: `${String(evidenceBundles)} / ${String(qualityArtifacts)}`,
        tone: evidenceBundles > 0 || qualityArtifacts > 0 ? 'good' : 'warn',
        detail: '格式為 evidence bundle 數量 / quality report 版本數量。',
      },
    ],
    lists: [
      {
        title: '最近任務',
        empty: '目前沒有可檢視的最近任務。',
        items: snapshot.runs.slice(0, 8).map((run) => ({
          title: `${run.type} / ${run.status}`,
          subtitle: run.created_at,
          badge: run.id,
          to: routeForRun(run),
        })),
      },
      {
        title: '證據版本',
        empty: '最近版本尚未掛上證據。',
        items: snapshot.recentVersions
          .filter((version) => version.evidence_bundle_ids.length > 0 || version.quality_report_id !== null)
          .slice(0, 8)
          .map((version) => ({
            title: `${version.purpose} / ${version.status}`,
            subtitle: version.id,
            badge:
              version.quality_report_id !== null
                ? 'QUALITY'
                : `${version.evidence_bundle_ids.length} BUNDLE`,
            to:
              version.quality_report_id !== null
                ? routeForArtifact(version.quality_report_id)
                : { name: 'researches', params: { id: version.research_id } },
          })),
      },
      {
        title: '盲測前置',
        empty: '最近版本尚未進入封存／盲測前置階段。',
        items: snapshot.recentVersions
          .filter((version) => version.observation_split.sealed_test_id !== null || version.frozen_submission_ids.length > 0)
          .slice(0, 8)
          .map((version) => ({
            title: `${version.status} / ${version.purpose}`,
            subtitle: version.id,
            badge:
              version.frozen_submission_ids.length > 0
                ? `${version.frozen_submission_ids.length} FROZEN`
                : 'SEALED READY',
            to: { name: 'researches', params: { id: version.research_id } },
          })),
      },
    ],
    note: '驗證中心目前以任務、證據與封存前置為主；更完整的全域最終評估中心仍待後續接上專屬 API。',
  }
}

function buildMemory(snapshot: Snapshot): ModuleDashboard {
  const evidenceVersions = snapshot.recentVersions.filter((version) => version.evidence_bundle_ids.length > 0)

  return {
    section: '記憶',
    title: '知識與記憶',
    summary: '以目前可讀的研究與證據，整理可回顧的脈絡入口。',
    actions: [{ label: '回總覽', to: { name: 'overview' } }],
    metrics: [
      {
        label: '可回顧研究',
        value: String(snapshot.researches.length),
        tone: 'neutral',
        detail: '前台目前可讀取的研究容器數量。',
      },
      {
        label: '具證據版本',
        value: String(evidenceVersions.length),
        tone: evidenceVersions.length > 0 ? 'good' : 'warn',
        detail: '最近研究版本中已掛證據包的版本數。',
      },
      {
        label: '可追溯任務',
        value: String(snapshot.runs.length),
        tone: snapshot.runs.length > 0 ? 'good' : 'warn',
        detail: '目前可從前台直接深連結的任務投影數量。',
      },
      readinessMetric(snapshot.readiness),
    ],
    lists: [
      {
        title: '最近研究',
        empty: '目前沒有研究可回顧。',
        items: takeRecent(snapshot.researches, 8).map((research) => ({
          title: research.name,
          subtitle: research.id,
          badge: versionBadge(latestVersion(snapshot.researchVersionsByResearch[research.id] ?? [])),
          to: routeForResearch(research),
        })),
      },
      {
        title: '證據版本',
        empty: '最近沒有證據版本。',
        items: evidenceVersions.slice(0, 8).map((version) => ({
          title: `${version.purpose} / ${version.status}`,
          subtitle: version.id,
          badge: `${version.evidence_bundle_ids.length} BUNDLE`,
          to: { name: 'researches', params: { id: version.research_id } },
        })),
      },
      {
        title: '可追溯任務',
        empty: '目前沒有可追溯任務。',
        items: snapshot.runs.slice(0, 8).map((run) => ({
          title: `${run.type} / ${run.status}`,
          subtitle: run.created_at,
          badge: run.id,
          to: routeForRun(run),
        })),
      },
    ],
    note: '記憶模組目前先用研究、證據與任務回溯入口承接；真正的知識庫結構仍待獨立後端模組。',
  }
}

function buildModel(snapshot: Snapshot): ModuleDashboard {
  const typeCounts = {
    PROFILE: snapshot.runs.filter((row) => row.type === 'PROFILE').length,
    SEARCH: snapshot.runs.filter((row) => row.type === 'SEARCH').length,
    VALIDATE: snapshot.runs.filter((row) => row.type === 'VALIDATE').length,
  }

  return {
    section: '模型',
    title: '模型管理',
    summary: '目前以前台可見的執行型別與服務狀態，呈現模型工作負載訊號。',
    actions: [{ label: '回總覽', to: { name: 'overview' } }],
    metrics: [
      readinessMetric(snapshot.readiness),
      {
        label: 'PROFILE 任務',
        value: String(typeCounts.PROFILE),
        tone: typeCounts.PROFILE > 0 ? 'good' : 'warn',
        detail: '最近工作流中由模型驅動的 PROFILE 任務數量。',
      },
      {
        label: 'SEARCH 任務',
        value: String(typeCounts.SEARCH),
        tone: typeCounts.SEARCH > 0 ? 'good' : 'warn',
        detail: '最近工作流中 SEARCH 任務數量。',
      },
      {
        label: 'VALIDATE 任務',
        value: String(typeCounts.VALIDATE),
        tone: typeCounts.VALIDATE > 0 ? 'good' : 'warn',
        detail: '最近工作流中 VALIDATE 任務數量。',
      },
    ],
    lists: [
      {
        title: '最近模型工作負載',
        empty: '最近沒有模型相關任務。',
        items: snapshot.runs.slice(0, 8).map((run) => ({
          title: `${run.type} / ${run.status}`,
          subtitle: run.created_at,
          badge: run.id,
          to: routeForRun(run),
        })),
      },
      {
        title: '活躍研究版本',
        empty: '目前沒有活躍研究版本。',
        items: snapshot.recentVersions
          .filter((version) => ACTIVE_VERSION_STATUSES.has(version.status))
          .slice(0, 8)
          .map((version) => ({
            title: `${version.purpose} / ${version.status}`,
            subtitle: version.id,
            badge: version.research_id,
            to: { name: 'researches', params: { id: version.research_id } },
          })),
      },
      {
        title: '可分析資料集',
        empty: '目前沒有具備分析條件的資料集。',
        items: snapshot.datasets
          .filter((dataset) => {
            const version = latestDatasetVersion(snapshot.datasetVersionsByDataset[dataset.id] ?? [])
            return version?.status === 'AVAILABLE' && version.structure_preview_artifact_id !== null
          })
          .slice(0, 8)
          .map((dataset) => ({
            title: dataset.name,
            subtitle: dataset.id,
            badge: datasetBadge(latestDatasetVersion(snapshot.datasetVersionsByDataset[dataset.id] ?? [])),
            to: { name: 'datasets' },
          })),
      },
    ],
    note: '目前前台尚未有獨立模型註冊 API，因此模型頁先誠實顯示實際運行訊號，而不是虛構模型清單。',
  }
}

function buildTraining(snapshot: Snapshot): ModuleDashboard {
  const datasetVersions = Object.values(snapshot.datasetVersionsByDataset).flat()
  const availableVersions = datasetVersions.filter((version) => version.status === 'AVAILABLE').length

  return {
    section: '訓練',
    title: '訓練中心',
    summary: '以資料集與可用版本的現況，作為後續訓練流程的準備基線。',
    actions: [{ label: '前往資料', to: { name: 'datasets' } }],
    metrics: [
      {
        label: '資料集',
        value: String(snapshot.datasets.length),
        tone: snapshot.datasets.length > 0 ? 'good' : 'warn',
        detail: '目前前台可讀取的資料集數量。',
      },
      {
        label: '資料版本',
        value: String(datasetVersions.length),
        tone: datasetVersions.length > 0 ? 'good' : 'warn',
        detail: '目前拉到的資料版本頁面總量。',
      },
      {
        label: '可用版本',
        value: String(availableVersions),
        tone: availableVersions > 0 ? 'good' : 'warn',
        detail: '狀態為 AVAILABLE 的資料版本數量。',
      },
      readinessMetric(snapshot.readiness),
    ],
    lists: [
      {
        title: '最近資料集',
        empty: '目前沒有資料集。',
        items: takeRecent(snapshot.datasets, 8).map((dataset) => ({
          title: dataset.name,
          subtitle: dataset.id,
          badge: datasetBadge(latestDatasetVersion(snapshot.datasetVersionsByDataset[dataset.id] ?? [])),
          to: { name: 'datasets' },
        })),
      },
      {
        title: '最近資料版本',
        empty: '目前沒有資料版本。',
        items: takeRecent(datasetVersions, 8).map((version) => ({
          title: `${version.format} / ${version.status}`,
          subtitle: version.id,
          badge: `${version.row_count} rows`,
          to:
            version.structure_preview_artifact_id === null
              ? { name: 'datasets' }
              : routeForArtifact(version.structure_preview_artifact_id),
        })),
      },
      {
        title: '可分析來源',
        empty: '目前沒有可直接分析的資料來源。',
        items: snapshot.datasets
          .filter((dataset) => {
            const version = latestDatasetVersion(snapshot.datasetVersionsByDataset[dataset.id] ?? [])
            return version?.status === 'AVAILABLE' && version.structure_preview_artifact_id !== null
          })
          .slice(0, 8)
          .map((dataset) => ({
            title: dataset.name,
            subtitle: dataset.id,
            badge: 'READY',
            to: { name: 'datasets' },
          })),
      },
    ],
    note: '訓練頁目前仍以前置資料盤點為主；正式訓練任務與模型發布流程還需要獨立後端模組支撐。',
  }
}

function buildSettings(snapshot: Snapshot): ModuleDashboard {
  const activeRuns = snapshot.runs.filter((row) => ACTIVE_RUN_STATUSES.has(row.status)).length

  return {
    section: '設定',
    title: '系統設定',
    summary: '集中檢視目前系統就緒度與前台可見的工作量訊號。',
    actions: [{ label: '回總覽', to: { name: 'overview' } }],
    metrics: [
      readinessMetric(snapshot.readiness),
      {
        label: '研究容器',
        value: String(snapshot.researches.length),
        tone: 'neutral',
        detail: '目前前台可讀取的研究容器數量。',
      },
      {
        label: '資料集',
        value: String(snapshot.datasets.length),
        tone: 'neutral',
        detail: '目前前台可讀取的資料集數量。',
      },
      {
        label: '進行中任務',
        value: String(activeRuns),
        tone: activeRuns > 0 ? 'good' : 'warn',
        detail: '任務狀態為 queued/running/cancel_requested 的數量。',
      },
    ],
    lists: [
      {
        title: '系統訊號',
        empty: '目前沒有系統訊號。',
        items: [
          {
            title: snapshot.readiness === 'ready' ? 'Ready endpoint 正常' : 'Ready endpoint 異常',
            subtitle: '來源：/health/ready/',
            badge: snapshot.readiness,
          },
          {
            title: `研究 ${String(snapshot.researches.length)} / 資料集 ${String(snapshot.datasets.length)}`,
            subtitle: '來源：前台已授權 API',
            badge: 'INVENTORY',
          },
          {
            title: `最近任務 ${String(snapshot.runs.length)} 筆`,
            subtitle: '來源：最近研究版本 run 投影',
            badge: 'RUNS',
          },
        ],
      },
      {
        title: '最近任務',
        empty: '目前沒有最近任務。',
        items: snapshot.runs.slice(0, 8).map((run) => ({
          title: `${run.type} / ${run.status}`,
          subtitle: run.created_at,
          badge: run.id,
          to: routeForRun(run),
        })),
      },
      {
        title: '最近研究版本',
        empty: '目前沒有最近研究版本。',
        items: snapshot.recentVersions.slice(0, 8).map((version) => ({
          title: `${version.purpose} / ${version.status}`,
          subtitle: version.id,
          badge: version.research_id,
          to: { name: 'researches', params: { id: version.research_id } },
        })),
      },
    ],
    note: '設定頁目前先提供系統就緒度與前台可見訊號；真正的帳號、權限與策略設定 API 尚待補齊。',
  }
}

export async function loadModuleDashboard(
  name: ModuleName,
  deps: ModuleDashboardDeps,
): Promise<ModuleDashboard> {
  const snapshot = await buildSnapshot(deps)
  switch (name) {
    case 'overview':
      return buildOverview(snapshot)
    case 'discoveries':
      return buildDiscoveries(snapshot)
    case 'verification':
      return buildVerification(snapshot)
    case 'memory':
      return buildMemory(snapshot)
    case 'model':
      return buildModel(snapshot)
    case 'training':
      return buildTraining(snapshot)
    case 'settings':
      return buildSettings(snapshot)
  }
}
