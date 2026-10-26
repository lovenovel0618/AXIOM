/**
 * 研究模組（SSOT 08–10）共用載入器：以研究識別碼一次讀出研究、其版本、每個版本的任務，
 * 以及凍結提交的最終評估。
 *
 * 後端沒有研究層級的目標、成果摘要、分支圖與事件重播端點，因此這一層只做既有契約的
 * 投影；任一單筆讀取失敗都只讓該部分留空，不以推測補值。
 */
import { ref } from 'vue'
import { getFinalEvaluation } from '../api/evaluations'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { parseFinalEvaluation } from './finalEvaluation'
import { describeError } from './messages'
import { loadResearchPanel, type ResearchPanel } from './researchPanels'
import { client } from './session'

export function useResearchPanel() {
  const panel = ref<ResearchPanel | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(researchId: string): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      panel.value = await loadResearchPanel(
        {
          listResearches: (limit) => listResearches(client, limit),
          listResearchVersions: (id, limit) => listResearchVersions(client, id, limit),
          listResearchVersionRuns: (id, limit) => listResearchVersionRuns(client, id, limit),
          getFinalEvaluation: async (submissionId) => {
            try {
              return parseFinalEvaluation(await getFinalEvaluation(client, submissionId))
            } catch {
              return null
            }
          },
        },
        researchId,
      )
    } catch (cause) {
      panel.value = null
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return { panel, loading, error, load }
}
