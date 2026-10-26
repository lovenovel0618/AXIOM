/**
 * 模型模組（SSOT 32–35）共用載入器：一次讀出研究 → 版本 → 任務，再以任務與版本的預算用量推導
 * 資源、延遲與 Token 成本。
 *
 * 後端沒有模型 registry、路由策略、基準測試或儲存配額端點，因此這一層只做既有契約的投影；
 * 任何單筆讀取失敗都只讓該項目保持「未取得」，不影響其他已揭露內容。
 */
import { ref } from 'vue'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { loadModelCenter, type ModelCenter } from './modelCenter'
import { describeError } from './messages'
import { client } from './session'

export function useModelCenter() {
  const center = ref<ModelCenter | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      center.value = await loadModelCenter({
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
        listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
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
