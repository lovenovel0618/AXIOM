/**
 * 候選公式庫（SSOT 18）與公式比較（SSOT 19）共用的載入器。
 *
 * 先讀出發現快照（研究 → 版本 → SEARCH 任務 → 候選），再逐條補上公式 AST。
 * 公式單筆讀取失敗時該列保持未載入，畫面顯示「未取得」，不以推測值代替。
 */
import { ref } from 'vue'
import { getEquationVersion, getFitRun, listRunCandidates, type EquationVersion } from '../api/candidates'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { loadCandidateEquations, loadDiscoveriesCenter, type DiscoveriesCenter } from './discoveries'
import { describeError } from './messages'
import { client } from './session'

export function useDiscoveryCatalog() {
  const center = ref<DiscoveriesCenter | null>(null)
  const equations = ref<Record<string, EquationVersion>>({})
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const next = await loadDiscoveriesCenter({
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
        listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
        listRunCandidates: (runId, limit) => listRunCandidates(client, runId, { limit }),
        getEquationVersion: (id) => getEquationVersion(client, id),
        getFitRun: (id) => getFitRun(client, id),
      })
      center.value = next
      equations.value = await loadCandidateEquations(
        (id) => getEquationVersion(client, id),
        next.searchRuns.flatMap((row) => row.candidates),
        {},
      )
    } catch (cause) {
      center.value = null
      equations.value = {}
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return { center, equations, loading, error, load }
}
