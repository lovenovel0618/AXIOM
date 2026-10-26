/**
 * 驗證模組（SSOT 22–26）共用的載入器：一次讀出研究 → 版本 → 任務 → frozen submission 快照，
 * 再補上證據包、品質報告與證明產物 metadata。
 *
 * 任何單筆讀取失敗都只讓該項目保持「未取得」，不影響其他已揭露內容，也不以推測值代替。
 */
import { ref } from 'vue'
import { getArtifact, getArtifactContent } from '../api/artifacts'
import { getEvidenceBundle } from '../api/evidence'
import { getFinalEvaluation, getValidationRun } from '../api/evaluations'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { parseValidationRun } from './evaluation'
import { parseFinalEvaluation } from './finalEvaluation'
import { describeError } from './messages'
import { client } from './session'
import { loadVerificationCenter, type VerificationCenter } from './verificationCenter'

export function useVerificationCenter() {
  const center = ref<VerificationCenter | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      center.value = await loadVerificationCenter({
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
        getArtifact: async (artifactId) => await getArtifact(client, artifactId),
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
