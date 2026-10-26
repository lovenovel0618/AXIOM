/**
 * 研究清單載入器：一次讀取研究、各研究的最新版本與該版本的任務，組成清單快照。
 *
 * 單一研究或版本讀取失敗時只讓該列缺資料，不讓整頁失敗；後端仍有未讀取頁面時以
 * `hasMoreVersions` 明示，避免把「已讀取數」誤讀成總數。
 */
import { ref } from 'vue'
import { listResearchVersionRuns, listResearches, listResearchVersions } from '../api/research'
import { describeError } from './messages'
import {
  latestVersionOf,
  RESEARCH_LIMIT,
  VERSIONS_PER_RESEARCH,
  type CatalogSnapshot,
} from './researchCatalog'
import { client } from './session'

const RUNS_PER_VERSION = 50

const EMPTY: CatalogSnapshot = {
  researches: [],
  versionsByResearch: {},
  runsByVersion: {},
  moreVersionsByResearch: {},
}

export function useResearchCatalog() {
  const snapshot = ref<CatalogSnapshot>(EMPTY)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const page = await listResearches(client, RESEARCH_LIMIT)
      const versionsByResearch: CatalogSnapshot['versionsByResearch'] = {}
      const runsByVersion: CatalogSnapshot['runsByVersion'] = {}
      const moreVersionsByResearch: CatalogSnapshot['moreVersionsByResearch'] = {}

      await Promise.all(
        page.items.map(async (research) => {
          try {
            const versions = await listResearchVersions(client, research.id, VERSIONS_PER_RESEARCH)
            versionsByResearch[research.id] = versions.items
            moreVersionsByResearch[research.id] = versions.next_cursor !== null

            const latest = latestVersionOf(versions.items)
            if (latest === null) return
            try {
              runsByVersion[latest.id] = (await listResearchVersionRuns(client, latest.id, RUNS_PER_VERSION)).items
            } catch {
              // 任務讀取失敗時保持未知，不以 0 筆代替。
            }
          } catch {
            versionsByResearch[research.id] = []
            moreVersionsByResearch[research.id] = false
          }
        }),
      )

      snapshot.value = {
        researches: page.items,
        versionsByResearch,
        runsByVersion,
        moreVersionsByResearch,
      }
    } catch (cause) {
      snapshot.value = EMPTY
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return { snapshot, loading, error, load }
}
