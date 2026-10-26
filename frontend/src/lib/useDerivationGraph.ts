/**
 * 研究推演（SSOT 21）載入器：以單一研究版本為單位，載入任務、候選、品質與評估，
 * 交給 `buildFlow` 推導流程圖；缺任何一層只少對應節點，不以推測補位。
 */
import { ref } from 'vue'
import { getArtifactContent } from '../api/artifacts'
import { getEquationVersion, getFitRun, listRunCandidates, type Candidate, type EquationVersion, type FitRun } from '../api/candidates'
import { getFinalEvaluation, getValidationRun } from '../api/evaluations'
import {
  fetchResearchEventBatch,
  getResearchVersion,
  listResearchVersionRuns,
  listResearchVersions,
  listResearches,
  type Research,
  type ResearchVersion,
} from '../api/research'
import { parseQualityReport, type QualityReport } from './evidence'
import type { RunEventEnvelope } from './events'
import { parseValidationRun, type ValidationRun } from './evaluation'
import { parseFinalEvaluation, type FinalEvaluation } from './finalEvaluation'
import { buildFlow, type FlowGraph } from './flow'
import { describeError } from './messages'
import { client } from './session'

const RUNS_LIMIT = 50
const CANDIDATE_LIMIT = 50
const RESEARCH_LIMIT = 50

export function useDerivationGraph() {
  const researches = ref<Research[]>([])
  const versions = ref<ResearchVersion[]>([])
  const version = ref<ResearchVersion | null>(null)
  const equations = ref<Record<string, EquationVersion>>({})
  const fits = ref<Record<string, FitRun>>({})
  const graph = ref<FlowGraph | null>(null)

  const loading = ref(false)
  const graphLoading = ref(false)
  const error = ref('')

  async function loadIndex(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      researches.value = (await listResearches(client, RESEARCH_LIMIT)).items
    } catch (cause) {
      researches.value = []
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  /** 讀取某研究的版本清單；研究不存在或讀取失敗時清空版本與流程圖。 */
  async function selectResearch(researchId: string): Promise<void> {
    versions.value = []
    version.value = null
    graph.value = null
    if (researchId === '') return

    try {
      versions.value = (await listResearchVersions(client, researchId)).items
    } catch (cause) {
      versions.value = []
      error.value = describeError(cause)
    }
  }

  async function loadGraph(versionId: string): Promise<void> {
    if (versionId === '') {
      version.value = null
      graph.value = null
      return
    }

    graphLoading.value = true
    error.value = ''
    try {
      const current = await getResearchVersion(client, versionId)
      version.value = current
      versions.value = versions.value.map((row) => (row.id === current.id ? current : row))

      const runPage = await listResearchVersionRuns(client, versionId, RUNS_LIMIT)
      const collectedCandidates: Candidate[] = []
      for (const run of runPage.items) {
        if (run.type !== 'SEARCH') continue
        try {
          const page = await listRunCandidates(client, run.id, { limit: CANDIDATE_LIMIT })
          collectedCandidates.push(...page.items)
        } catch {
          // 候選分頁單獨失敗時保留其餘資料。
        }
      }

      const nextEquations: Record<string, EquationVersion> = {}
      const nextFits: Record<string, FitRun> = {}
      const equationIds = [...new Set(collectedCandidates.map((row) => row.equation_version_id))]
      const fitIds = [...new Set(collectedCandidates.flatMap((row) => row.fit_run_ids))]
      await Promise.all([
        ...equationIds.map(async (id) => {
          try {
            nextEquations[id] = await getEquationVersion(client, id)
          } catch {
            // 單筆缺失不推測公式內容。
          }
        }),
        ...fitIds.map(async (id) => {
          try {
            nextFits[id] = await getFitRun(client, id)
          } catch {
            // 單筆缺失不推測擬合參數。
          }
        }),
      ])

      const evaluations: Record<string, ValidationRun> = {}
      const validationIds = new Set(collectedCandidates.flatMap((row) => row.validation_run_ids))
      for (const run of runPage.items) if (run.type === 'VALIDATE') validationIds.add(run.id)
      for (const validationId of validationIds) {
        try {
          const parsed = parseValidationRun(await getValidationRun(client, validationId))
          if (parsed !== null) evaluations[validationId] = parsed
        } catch {
          // 逐筆缺失不拋全域錯。
        }
      }

      const finalEvaluations: Record<string, FinalEvaluation> = {}
      for (const submissionId of current.frozen_submission_ids) {
        try {
          const parsed = parseFinalEvaluation(await getFinalEvaluation(client, submissionId))
          if (parsed !== null) finalEvaluations[submissionId] = parsed
        } catch {
          // 評估尚未產生時保持空白狀態。
        }
      }

      let quality: QualityReport | null = null
      if (current.quality_report_id !== null) {
        try {
          quality = parseQualityReport(await getArtifactContent<unknown>(client, current.quality_report_id))
        } catch {
          quality = null
        }
      }

      let events: RunEventEnvelope[] = []
      try {
        events = (await fetchResearchEventBatch(client, versionId, null)).events
      } catch {
        // 事件讀取失敗時流程圖仍可顯示，只是節點沒有事件紀錄。
      }

      equations.value = nextEquations
      fits.value = nextFits
      graph.value = buildFlow({
        version: current,
        runs: runPage.items,
        candidates: collectedCandidates,
        equations: nextEquations,
        fits: nextFits,
        evaluations,
        finalEvaluations,
        quality,
        events,
      })
    } catch (cause) {
      version.value = null
      graph.value = null
      error.value = describeError(cause)
    } finally {
      graphLoading.value = false
    }
  }

  return {
    researches,
    versions,
    version,
    equations,
    fits,
    graph,
    loading,
    graphLoading,
    error,
    loadIndex,
    selectResearch,
    loadGraph,
  }
}
