/**
 * 數據模組（SSOT 11–17）的載入器：清單頁只讀「資料集 → 最近版本」，資料集工作區頁再加讀
 * 結構預覽與匯入任務。
 *
 * 後端沒有單筆資料集端點，工作區以清單比對取得目標資料集；任何單筆讀取失敗只讓該項目保持
 * 「未取得」，不影響其他已揭露內容。
 */
import { ref } from 'vue'
import { getArtifactContent } from '../api/artifacts'
import {
  listDatasetRuns,
  listDatasets,
  listVersions,
  type Dataset,
  type DatasetVersion,
  type RunRecord,
} from '../api/datasets'
import { DATASETS_READ, VERSIONS_PER_DATASET, loadDataCenter, type DataCenter } from './dataCenter'
import { describeError } from './messages'
import { parseSourceMetadata, type SourceMetadata } from './semantics'
import { client } from './session'

/** 結構預覽產物不可信：無法解析或讀取失敗都回 null（未取得），不讓整頁失敗。 */
export async function fetchStructureMetadata(artifactId: string): Promise<SourceMetadata | null> {
  try {
    return parseSourceMetadata(await getArtifactContent<unknown>(client, artifactId))
  } catch {
    return null
  }
}

export function useDataCenter() {
  const center = ref<DataCenter | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      center.value = await loadDataCenter({
        listDatasets: (limit) => listDatasets(client, '', limit),
        listVersions: (datasetId, limit) => listVersions(client, datasetId, limit),
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

export interface DatasetWorkspace {
  dataset: Dataset | null
  versions: DatasetVersion[]
  runs: RunRecord[]
  metadataByArtifact: Record<string, SourceMetadata | null>
  versionTruncated: boolean
}

export function useDatasetWorkspace(datasetId: () => string) {
  const workspace = ref<DatasetWorkspace | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function loadMetadata(versions: DatasetVersion[]): Promise<Record<string, SourceMetadata | null>> {
    const ids = [
      ...new Set(
        versions
          .map((version) => version.structure_preview_artifact_id)
          .filter((id): id is string => id !== null),
      ),
    ]
    const entries = await Promise.all(
      ids.map(async (id) => [id, await fetchStructureMetadata(id)] as const),
    )
    return Object.fromEntries(entries)
  }

  async function load(): Promise<void> {
    const id = datasetId()
    loading.value = true
    error.value = ''
    try {
      if (id === '') {
        workspace.value = null
        return
      }
      const page = await listDatasets(client, '', DATASETS_READ)
      const dataset = page.items.find((row) => row.id === id) ?? null
      if (dataset === null) {
        workspace.value = { dataset: null, versions: [], runs: [], metadataByArtifact: {}, versionTruncated: false }
        return
      }
      const versionPage = await listVersions(client, id, VERSIONS_PER_DATASET + 1)
      const versionTruncated = versionPage.next_cursor !== null || versionPage.items.length > VERSIONS_PER_DATASET
      const versions = versionPage.items.slice(0, VERSIONS_PER_DATASET)
      let runs: RunRecord[] = []
      try {
        runs = (await listDatasetRuns(client, id)).items
      } catch {
        runs = []
      }
      workspace.value = {
        dataset,
        versions,
        runs,
        metadataByArtifact: await loadMetadata(versions),
        versionTruncated,
      }
    } catch (cause) {
      workspace.value = null
      error.value = describeError(cause)
    } finally {
      loading.value = false
    }
  }

  return { workspace, loading, error, load }
}
