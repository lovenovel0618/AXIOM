<script setup lang="ts">
/** 資料集工作區：版本、結構預覽、完整性檢核與版本比較，全部由後端已揭露資料推導。 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { getArtifactContent } from '../api/artifacts'
import {
  listDatasetRuns,
  listDatasets,
  listVersions,
  type Dataset,
  type DatasetVersion,
  type DatasetVersionStatus,
  type RunRecord,
} from '../api/datasets'
import { createResearch, createResearchVersion, getResearchVersion, validateDraft } from '../api/research'
import {
  buildDatasetDigest,
  buildQualityChecks,
  compareVersions,
  recentVersions,
  summarizeStructure,
} from '../lib/datasetWorkbench'
import { describeError } from '../lib/messages'
import { withBackRef } from '../lib/navigationState'
import { buildQuickResearchDraft, quickResearchName } from '../lib/quickResearch'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { parseSourceMetadata, type SourceMetadata } from '../lib/semantics'
import { client } from '../lib/session'
import { uploadDatasetFile, type UploadStage } from '../lib/upload'

const route = useRoute()
const router = useRouter()

const dataset = ref<Dataset | null>(null)
const versions = ref<DatasetVersion[]>([])
const runs = ref<RunRecord[]>([])
const selectedVersionId = ref(readQueryString(route.query, 'version'))
const compareBaseId = ref(readQueryString(route.query, 'base'))
const compareTargetId = ref(readQueryString(route.query, 'target'))

const metadataCache = ref<Record<string, SourceMetadata | null>>({})
const selectedMetadata = ref<SourceMetadata | null>(null)
const baseMetadata = ref<SourceMetadata | null>(null)
const targetMetadata = ref<SourceMetadata | null>(null)

const loading = ref(false)
const uploading = ref(false)
const analyzing = ref(false)
const stage = ref<UploadStage | null>(null)
const error = ref('')
const notice = ref('')

const stageLabel: Record<UploadStage, string> = {
  hashing: '計算內容雜湊…',
  session: '建立上傳工作階段…',
  transfer: '傳輸檔案位元組…',
  complete: '排入匯入任務…',
}

const statusLabel: Record<DatasetVersionStatus, string> = {
  AVAILABLE: '可用',
  UNAVAILABLE: '不可用',
}

const unsupportedNotice = '支援格式：CSV、JSON、PARQUET（上限 50 MiB）。'

const datasetId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const backRefQuery = computed(() => withBackRef(route.fullPath))
const digest = computed(() => buildDatasetDigest(versions.value))
const compareOptions = computed(() => recentVersions(versions.value))

const latestAvailableVersion = computed<DatasetVersion | null>(
  () => versions.value.find((row) => row.status === 'AVAILABLE' && row.structure_preview_artifact_id !== null) ?? null,
)

const selectedVersion = computed<DatasetVersion | null>(
  () => versions.value.find((row) => row.id === selectedVersionId.value) ?? null,
)
const selectedStructure = computed(() => summarizeStructure(selectedMetadata.value))
const checks = computed(() =>
  selectedVersion.value === null ? [] : buildQualityChecks(selectedVersion.value, selectedMetadata.value),
)

const baseVersion = computed<DatasetVersion | null>(
  () => versions.value.find((row) => row.id === compareBaseId.value) ?? null,
)
const targetVersion = computed<DatasetVersion | null>(
  () => versions.value.find((row) => row.id === compareTargetId.value) ?? null,
)
const diff = computed(() =>
  baseVersion.value === null || targetVersion.value === null
    ? null
    : compareVersions(baseVersion.value, targetVersion.value, baseMetadata.value, targetMetadata.value),
)

function resolveSelectedVersion(): string {
  const requested = readQueryString(route.query, 'version')
  if (requested !== '' && versions.value.some((row) => row.id === requested)) return requested
  return versions.value[0]?.id ?? ''
}

async function ensureMetadata(artifactId: string | null): Promise<SourceMetadata | null> {
  if (artifactId === null) return null
  const cached = metadataCache.value[artifactId]
  if (cached !== undefined) return cached
  let parsed: SourceMetadata | null = null
  try {
    parsed = parseSourceMetadata(await getArtifactContent<unknown>(client, artifactId))
  } catch {
    parsed = null
  }
  metadataCache.value = { ...metadataCache.value, [artifactId]: parsed }
  return parsed
}

async function refreshMetadata(): Promise<void> {
  selectedMetadata.value = await ensureMetadata(selectedVersion.value?.structure_preview_artifact_id ?? null)
  baseMetadata.value = await ensureMetadata(baseVersion.value?.structure_preview_artifact_id ?? null)
  targetMetadata.value = await ensureMetadata(targetVersion.value?.structure_preview_artifact_id ?? null)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const page = await listDatasets(client)
    const found = page.items.find((row) => row.id === datasetId.value) ?? null
    dataset.value = found
    if (found === null) {
      versions.value = []
      runs.value = []
      notice.value = ''
      return
    }
    versions.value = (await listVersions(client, found.id)).items
    selectedVersionId.value = resolveSelectedVersion()
    await reloadRuns()
    await refreshMetadata()
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

async function reloadVersions(): Promise<void> {
  if (dataset.value === null) return
  try {
    versions.value = (await listVersions(client, dataset.value.id)).items
    selectedVersionId.value = resolveSelectedVersion()
    await refreshMetadata()
  } catch (cause) {
    error.value = describeError(cause)
  }
}

/** AX-44：重開頁面時用這份清單尋回 INGEST 任務；失敗只提示，不清空既有畫面。 */
async function reloadRuns(): Promise<void> {
  if (dataset.value === null) return
  try {
    runs.value = (await listDatasetRuns(client, dataset.value.id)).items
  } catch (cause) {
    error.value = describeError(cause)
  }
}

async function selectVersion(id: string): Promise<void> {
  selectedVersionId.value = id
  await refreshMetadata()
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const current = dataset.value
  if (file === undefined || current === null || uploading.value) return
  uploading.value = true
  error.value = ''
  notice.value = ''
  try {
    const outcome = await uploadDatasetFile(client, current.id, file, (next) => {
      stage.value = next
    })
    versions.value = outcome.versions
    const renewed = outcome.renewedSession
      ? '原上傳工作階段已過期，已另建新工作階段並重新傳輸檔案（不提供續傳）。'
      : ''
    notice.value = `已上傳 ${file.name}（SHA-256 ${outcome.checksum.slice(0, 12)}…），匯入任務狀態：${outcome.run.status}。${renewed}版本會在任務完成後出現，可重新載入。`
    await reloadRuns()
    await refreshMetadata()
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    uploading.value = false
    stage.value = null
  }
}

async function analyzeDataset(): Promise<void> {
  const current = dataset.value
  const version = latestAvailableVersion.value
  if (current === null || version === null || analyzing.value) return
  const previewId = version.structure_preview_artifact_id
  if (previewId === null) {
    error.value = '此資料集版本沒有結構預覽，無法自動建立分析草稿。'
    return
  }

  analyzing.value = true
  error.value = ''
  notice.value = ''
  try {
    const metadata = await ensureMetadata(previewId)
    if (metadata === null) {
      error.value = '結構預覽產物格式不符，無法自動建立分析草稿。'
      return
    }
    const draft = buildQuickResearchDraft(version, metadata)
    if (draft.request === null) {
      error.value = `無法自動建立分析草稿：${draft.problems.join('；')}`
      return
    }

    const research = await createResearch(client, quickResearchName(current.name))
    const createdVersion = await createResearchVersion(client, research.id, draft.request)
    const run = await validateDraft(client, createdVersion.id, createdVersion.revision)
    const freshVersion = await getResearchVersion(client, createdVersion.id)
    notice.value = `已從資料集「${current.name}」建立研究並啟動分析，任務狀態：${run.status}。`
    await router.push({
      name: 'research-workbench',
      params: { id: research.id },
      query: { version: freshVersion.id },
    })
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    analyzing.value = false
  }
}

onMounted(load)

watch(
  () => route.params.id,
  async () => {
    if (route.name !== 'dataset') return
    await load()
  },
)

watch(selectedVersionId, async (value) => {
  await replaceQueryState(router, route, { version: value })
})

watch(compareBaseId, async (value) => {
  await replaceQueryState(router, route, { base: value })
})

watch(compareTargetId, async (value) => {
  await replaceQueryState(router, route, { target: value })
})

watch([baseVersion, targetVersion], refreshMetadata)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">數據 / DATASET</div>
        <h1>{{ dataset === null ? '資料集工作區' : dataset.name }}</h1>
        <p class="muted">
          版本、結構預覽、完整性檢核與版本比較都在這裡，僅呈現後端已揭露的欄位。
        </p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'datasets', query: backRefQuery }"><button type="button">返回資料集清單</button></RouterLink>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading" class="muted">載入中…</p>
    <p v-else-if="dataset === null" class="bad">未取得此資料集，可能已被刪除或不在可見範圍內。</p>
    <template v-else>
      <div class="row">
        <div>
          <strong>{{ dataset.name }}</strong>
          <div class="mono">{{ dataset.id }}</div>
        </div>
        <div class="actions">
          <span class="tag">建立 {{ dataset.created_at }}</span>
          <button
            type="button"
            class="primary"
            :disabled="uploading || analyzing || latestAvailableVersion === null"
            title="以最新可用版本建立研究草稿並啟動分析"
            @click="analyzeDataset"
          >
            {{ analyzing ? '分析中…' : '分析' }}
          </button>
        </div>
      </div>

      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">版本數</div>
          <div class="metric-value">{{ digest.versionCount }}</div>
          <p class="muted">可用 {{ digest.availableCount }} / 不可用 {{ digest.unavailableCount }}</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">總列數</div>
          <div class="metric-value">{{ digest.totalRows }}</div>
          <p class="muted">所有版本列數加總</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">結構預覽</div>
          <div class="metric-value">{{ digest.previewCount }}</div>
          <p class="muted">具備結構預覽產物的版本數</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">格式</div>
          <div class="metric-value">{{ digest.formats.length }}</div>
          <p class="muted">{{ digest.formats.length === 0 ? '未取得' : digest.formats.join('、') }}</p>
        </section>
      </div>

      <div class="layout cols2" style="margin-top: 16px;">
        <section class="card">
          <h3>版本清單</h3>
          <div class="actions" style="margin-bottom: 10px;">
            <button type="button" :disabled="uploading" @click="reloadVersions">重新載入版本</button>
          </div>
          <p v-if="versions.length === 0" class="muted">此資料集尚無版本，請先上傳資料檔。</p>
          <table v-else>
            <thead>
              <tr><th>建立時間</th><th>格式</th><th>列數</th><th>狀態</th><th>指紋</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in versions" :key="row.id">
                <td>{{ row.created_at }}</td>
                <td>{{ row.format }}</td>
                <td>{{ row.row_count }}</td>
                <td><span class="tag">{{ statusLabel[row.status] }}</span></td>
                <td class="mono">{{ row.sha256.slice(0, 12) }}…</td>
                <td>
                  <button type="button" :class="{ primary: row.id === selectedVersionId }" @click="selectVersion(row.id)">
                    檢視
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <h3 style="margin-top: 22px;">匯入任務</h3>
          <div class="actions" style="margin-bottom: 10px;">
            <button type="button" :disabled="uploading" @click="reloadRuns">重新載入任務</button>
          </div>
          <p v-if="runs.length === 0" class="muted">此資料集尚無匯入任務。</p>
          <table v-else>
            <thead>
              <tr><th>建立時間</th><th>類型</th><th>狀態</th><th>任務</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in runs" :key="row.id">
                <td class="mono">{{ row.created_at }}</td>
                <td>{{ row.type }}</td>
                <td><span class="tag">{{ row.status }}</span></td>
                <td>
                  <RouterLink :to="{ name: 'run', params: { id: row.id }, query: withBackRef(route.fullPath) }">查看任務</RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>上傳新版本</h3>
          <div class="field">
            <label>資料檔</label>
            <input type="file" accept=".csv,.json,.parquet" :disabled="uploading" @change="onFile">
          </div>
          <p class="muted">{{ unsupportedNotice }}</p>
          <p v-if="uploading && stage !== null" class="tag" aria-live="polite">{{ stageLabel[stage] }}</p>
          <p v-if="latestAvailableVersion === null" class="muted">需先有至少一個可用版本才能分析。</p>

          <h3 style="margin-top: 22px;">資料預覽</h3>
          <template v-if="selectedVersion === null">
            <p class="muted">請先從左側版本清單選擇一筆。</p>
          </template>
          <template v-else>
            <div class="row compact">
              <span>版本</span>
              <span class="mono">{{ selectedVersion.id }}</span>
            </div>
            <div class="row compact">
              <span>結構預覽列數</span>
              <span>{{ selectedStructure === null ? '未取得' : selectedStructure.rowCount }}</span>
            </div>
            <template v-if="selectedStructure === null">
              <p class="muted">未取得此版本的結構預覽內容，欄位清單從缺。</p>
            </template>
            <template v-else>
              <table style="margin-top: 10px;">
                <thead><tr><th>欄位</th><th>實體型別</th></tr></thead>
                <tbody>
                  <tr v-for="column in selectedStructure.columns" :key="column.name">
                    <td class="mono">{{ column.name }}</td>
                    <td>{{ column.physical_type === '' ? '未提供' : column.physical_type }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-if="selectedStructure.duplicateNames.length !== 0" class="bad">
                欄位名稱重複：{{ selectedStructure.duplicateNames.join('、') }}
              </p>
            </template>
          </template>

          <h3 style="margin-top: 22px;">完整性檢核</h3>
          <p v-if="selectedVersion === null" class="muted">選擇版本後顯示檢核結果。</p>
          <div v-else class="list-rows">
            <div v-for="check in checks" :key="check.label" class="check-row">
              <span class="tag" :class="check.status === 'PASS' ? 'good' : check.status === 'FAIL' ? 'bad' : 'muted'">
                {{ check.status === 'PASS' ? '通過' : check.status === 'FAIL' ? '未通過' : '未取得' }}
              </span>
              <div>
                <strong>{{ check.label }}</strong>
                <div class="muted">{{ check.detail }}</div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <section class="card" style="margin-top: 16px;">
        <h3>版本比較</h3>
        <div class="formgrid">
          <div class="field">
            <label>基準版本</label>
            <select v-model="compareBaseId">
              <option value="">未選擇</option>
              <option v-for="row in compareOptions" :key="`base:${row.id}`" :value="row.id">
                {{ row.created_at }} · {{ row.format }} · {{ row.row_count }} 列
              </option>
            </select>
          </div>
          <div class="field">
            <label>對照版本</label>
            <select v-model="compareTargetId">
              <option value="">未選擇</option>
              <option v-for="row in compareOptions" :key="`target:${row.id}`" :value="row.id">
                {{ row.created_at }} · {{ row.format }} · {{ row.row_count }} 列
              </option>
            </select>
          </div>
        </div>

        <p v-if="diff === null" class="muted">請選擇兩個版本以顯示差異。</p>
        <template v-else>
          <div class="row compact">
            <span>列數差異（對照 − 基準）</span>
            <span :class="diff.rowDelta === 0 ? '' : diff.rowDelta > 0 ? 'good' : 'bad'">
              {{ diff.rowDelta > 0 ? '+' : '' }}{{ diff.rowDelta }}
            </span>
          </div>
          <div class="row compact">
            <span>檔案內容</span>
            <span>{{ diff.sameFile ? '指紋相同' : '指紋不同' }}</span>
          </div>
          <div class="row compact">
            <span>格式變更</span>
            <span>{{ diff.formatChanged ? '有變更' : '未變更' }}</span>
          </div>
          <div class="row compact">
            <span>狀態變更</span>
            <span>{{ diff.statusChanged ? '有變更' : '未變更' }}</span>
          </div>
          <div class="row compact">
            <span>新增欄位</span>
            <span>{{ diff.columnsAdded === null ? '未取得（需兩邊皆有結構預覽）' : diff.columnsAdded.length === 0 ? '無' : diff.columnsAdded.join('、') }}</span>
          </div>
          <div class="row compact">
            <span>移除欄位</span>
            <span>{{ diff.columnsRemoved === null ? '未取得（需兩邊皆有結構預覽）' : diff.columnsRemoved.length === 0 ? '無' : diff.columnsRemoved.join('、') }}</span>
          </div>
        </template>
      </section>

      <p v-if="error" class="bad" style="margin-top: 16px;">{{ error }}</p>
      <output v-if="notice" class="good" style="display: block; margin-top: 16px;">{{ notice }}</output>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-card {
  min-height: 140px;
}

.metric-value {
  font-size: 28px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 10px 12px;
  background: #0e1e31;
}

.compact {
  padding: 10px 0;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
