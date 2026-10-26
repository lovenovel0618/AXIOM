/** 控制台三頁共用載入器：以同一份快照餵給活動中心、待處理事件與資源監控。 */
import { ref } from 'vue'
import { listDatasetRuns, listDatasets, listVersions } from '../api/datasets'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { checkReadiness } from '../health'
import { buildConsoleSnapshot, type ConsoleSnapshot } from './consoleCenter'
import { describeError } from './messages'
import { client } from './session'

export function useConsoleCenter() {
  const snapshot = ref<ConsoleSnapshot | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      snapshot.value = await buildConsoleSnapshot({
        checkReadiness: () => checkReadiness(),
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
        listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
        listDatasets: (limit) => listDatasets(client, '', limit),
        listVersions: (datasetId, limit) => listVersions(client, datasetId, limit),
        listDatasetRuns: (datasetId, limit) => listDatasetRuns(client, datasetId, '', limit),
      })
    } catch (cause) {
      snapshot.value = null
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return {
    snapshot,
    loading,
    error,
    load,
  }
}
