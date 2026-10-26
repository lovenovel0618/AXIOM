/**
 * 記憶模組（SSOT 27–31）共用的載入器：一次讀出研究 → 版本 → 任務，再補上證據包、
 * 品質報告與 frozen submission 的最終評估／驗證結果。
 *
 * 後端沒有專屬知識庫或知識圖譜端點，因此這一層只做既有契約的投影；任何單筆讀取失敗
 * 都只讓該項目保持「未取得」，不影響其他已揭露內容，也不以推測值代替。
 */
import { ref } from 'vue'
import { getArtifactContent } from '../api/artifacts'
import { getEvidenceBundle } from '../api/evidence'
import { getFinalEvaluation, getValidationRun } from '../api/evaluations'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { parseValidationRun } from './evaluation'
import { parseFinalEvaluation } from './finalEvaluation'
import { loadMemoryCenter, type MemoryCenter } from './memoryCenter'
import { describeError } from './messages'
import { client } from './session'

export function useMemoryCenter() {
  const center = ref<MemoryCenter | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      center.value = await loadMemoryCenter({
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
        getValidationRun: async (validationId) => {
          try {
            return parseValidationRun(await getValidationRun(client, validationId))
          } catch {
            return null
          }
        },
        getEvidenceBundle: async (bundleId) => await getEvidenceBundle(client, bundleId),
        getQualityReport: async (artifactId) => await getArtifactContent<unknown>(client, artifactId),
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
