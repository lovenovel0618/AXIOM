/**
 * 隱藏變數探索（SSOT 20）載入器：逐版本讀取 PROFILE 產出的結構評估產物。
 *
 * 產物缺失或契約不符都照實記錄（`parseFailed`），不以中介資料反推內在維度。
 */
import { ref } from 'vue'
import { getArtifactContent } from '../api/artifacts'
import { listResearchVersions, listResearches, type ResearchVersionPage } from '../api/research'
import { RECENT_VERSIONS_READ, RESEARCHES_READ, VERSIONS_PER_RESEARCH, takeRecent } from './discoveries'
import { describeError } from './messages'
import { client } from './session'
import {
  buildLatentRows,
  parseStructureAssessment,
  summarizeLatent,
  type LatentSnapshot,
  type StructureAssessment,
} from './structureAssessment'

const EMPTY_VERSION_PAGE: ResearchVersionPage = { items: [], next_cursor: null }

export function useLatentExploration() {
  const snapshot = ref<LatentSnapshot | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const researchPage = await listResearches(client, RESEARCHES_READ)

      const entries = await Promise.all(
        researchPage.items.map(async (research) => {
          try {
            return [research.id, await listResearchVersions(client, research.id, VERSIONS_PER_RESEARCH)] as const
          } catch {
            return [research.id, EMPTY_VERSION_PAGE] as const
          }
        }),
      )

      const allVersions = entries.flatMap(([, page]) => page.items)
      const recent = takeRecent(allVersions, RECENT_VERSIONS_READ)
      const truncated = researchPage.next_cursor !== null || entries.some(([, page]) => page.next_cursor !== null)

      const assessments: Record<string, StructureAssessment | null> = {}
      const parseFailures = new Set<string>()

      await Promise.all(
        recent.map(async (version) => {
          const artifactId = version.structure_assessment_artifact_id
          if (artifactId === null) return
          try {
            const parsed = parseStructureAssessment(await getArtifactContent<unknown>(client, artifactId))
            if (parsed === null) parseFailures.add(artifactId)
            else assessments[artifactId] = parsed
          } catch {
            parseFailures.add(artifactId)
          }
        }),
      )

      const rows = buildLatentRows(recent, researchPage.items, assessments, parseFailures)
      snapshot.value = {
        rows,
        summary: summarizeLatent(rows),
        scope: {
          researchesRead: researchPage.items.length,
          versionsRead: allVersions.length,
          truncated,
        },
      }
    } catch (cause) {
      snapshot.value = null
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return { snapshot, loading, error, load }
}
