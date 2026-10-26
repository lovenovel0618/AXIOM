import { ref } from 'vue'
import { listRunCandidates } from '../api/candidates'
import { listDatasets, listVersions } from '../api/datasets'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { checkReadiness } from '../health'
import { loadModuleDashboard, type ModuleDashboard, type ModuleName } from './moduleDashboard'
import { describeError } from './messages'
import { client } from './session'

export function useModulePage(name: ModuleName) {
  const dashboard = ref<ModuleDashboard | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      dashboard.value = await loadModuleDashboard(name, {
        checkReadiness: () => checkReadiness(),
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
        listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
        listDatasets: (limit) => listDatasets(client, '', limit),
        listVersions: (datasetId, limit) => listVersions(client, datasetId, limit),
        listRunCandidates: (runId, limit) => listRunCandidates(client, runId, { limit }),
      })
    } catch (cause) {
      dashboard.value = null
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return {
    dashboard,
    loading,
    error,
    load,
  }
}
