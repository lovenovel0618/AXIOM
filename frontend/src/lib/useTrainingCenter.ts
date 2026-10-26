/**
 * 訓練模組（SSOT 36–38）共用的載入器：一次讀出研究 → 版本 → 任務，再補上凍結提交的
 * 最終評估作為訓練樣本。
 *
 * 後端沒有微調、LoRA、模型發布或訓練監控端點，因此這一層只做既有契約的投影；任何單筆
 * 讀取失敗都只讓該項目保持「未取得」，不影響其他已揭露內容。
 */
import { ref } from 'vue'
import { getFinalEvaluation } from '../api/evaluations'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { parseFinalEvaluation } from './finalEvaluation'
import { describeError } from './messages'
import { client } from './session'
import { loadTrainingCenter, type TrainingCenter } from './trainingCenter'

export function useTrainingCenter() {
  const center = ref<TrainingCenter | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      center.value = await loadTrainingCenter({
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
        listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
        getFinalEvaluation: async (submissionId) => {
          try {
            return parseFinalEvaluation(await getFinalEvaluation(client, submissionId))
          } catch {
            return null
          }
        },
      })
    } catch (cause) {
      center.value = null
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return { center, loading, error, load }
}
