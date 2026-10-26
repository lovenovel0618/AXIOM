/**
 * 逆向推導（SSOT 24）的載入器：先讀出研究 → 版本 → SEARCH 任務 → 候選，再逐條補公式 AST 與擬合參數。
 *
 * 公式或擬合單筆讀取失敗時該欄位保持未取得，畫面顯示「未取得」，不用推測值代替。
 */
import { ref } from 'vue'
import { getEquationVersion, getFitRun, listRunCandidates, type EquationVersion, type FitRun } from '../api/candidates'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { buildInverseDerivation, emptyInverseDerivation, type InverseDerivation } from './verificationInverse'
import { loadCandidateDetails, loadDiscoveriesCenter, type DiscoverySearchRun, type DiscoveriesCenter } from './discoveries'
import { describeError } from './messages'
import { client } from './session'

export function useInverseDerivation() {
  const center = ref<DiscoveriesCenter | null>(null)
  const equations = ref<Record<string, EquationVersion>>({})
  const fits = ref<Record<string, FitRun>>({})
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      center.value = await loadDiscoveriesCenter({
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
        listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
        listRunCandidates: (runId, limit) => listRunCandidates(client, runId, { limit }),
        getEquationVersion: (id) => getEquationVersion(client, id),
        getFitRun: (id) => getFitRun(client, id),
      })
      equations.value = {}
      fits.value = {}
    } catch (cause) {
      center.value = null
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  /** 只載入目前選定 SEARCH 任務的公式與擬合，避免替整份快照發請求。 */
  async function loadRunDetails(entry: DiscoverySearchRun | null): Promise<void> {
    if (entry === null) return
    const bundle = await loadCandidateDetails(
      {
        listResearches: (limit) => listResearches(client, limit),
        listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
        listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
        listRunCandidates: (runId, limit) => listRunCandidates(client, runId, { limit }),
        getEquationVersion: (id) => getEquationVersion(client, id),
        getFitRun: (id) => getFitRun(client, id),
      },
      entry.candidates,
      { equations: {}, fits: {} },
    )
    equations.value = { ...equations.value, ...bundle.equations }
    fits.value = { ...fits.value, ...bundle.fits }
  }

  function derive(entry: DiscoverySearchRun | null): InverseDerivation {
    return entry === null ? emptyInverseDerivation(null) : buildInverseDerivation(entry, equations.value, fits.value)
  }

  return { center, equations, fits, loading, error, load, loadRunDetails, derive }
}
