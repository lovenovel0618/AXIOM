/**
 * 設定模組（SSOT 39–40）共用的載入器：讀出服務就緒狀態，再補上研究與研究版本作為
 * 租戶識別與研究策略的來源。
 *
 * 後端沒有系統設定或治理政策端點，因此這一層只做既有契約的投影；讀取失敗一律回
 * 「未取得」，不影響其他已揭露內容。
 */
import { ref } from 'vue'
import { checkReadiness } from '../health'
import { listResearchVersions, listResearches } from '../api/research'
import { describeError } from './messages'
import { client } from './session'
import { loadSettingsCenter, type SettingsCenter } from './settingsCenter'

export function useSettingsCenter() {
  const center = ref<SettingsCenter | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      center.value = await loadSettingsCenter({
        checkReadiness: () => checkReadiness(),
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
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
