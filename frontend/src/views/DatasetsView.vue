<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  createDataset,
  listDatasets,
  listVersions,
  type Dataset,
  type DatasetVersion,
  type DatasetVersionStatus,
  type RunRecord,
} from '../api/datasets'
import { describeError } from '../lib/messages'
import { client } from '../lib/session'
import { uploadDatasetFile, type UploadStage } from '../lib/upload'

const datasets = ref<Dataset[]>([])
const versions = ref<DatasetVersion[]>([])
const selected = ref<Dataset | null>(null)
const name = ref('')
const busy = ref(false)
const uploading = ref(false)
const stage = ref<UploadStage | null>(null)
const error = ref('')
const notice = ref('')
const lastRun = ref<RunRecord | null>(null)

const stageLabel: Record<UploadStage, string> = {
  hashing: '計算內容雜湊…',
  session: '建立上傳工作階段…',
  transfer: '傳輸檔案位元組…',
  complete: '排入匯入任務…',
}

const statusLabel: Record<DatasetVersionStatus, string> = {
  AVAILABLE: '可用',
  UNAVAILABLE: '不可用',
  REVOKED: '已撤銷',
}

const unsupportedNotice = '支援格式：CSV、JSON、PARQUET（上限 50 MiB）。'

async function loadDatasets(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    datasets.value = (await listDatasets(client)).items
    if (selected.value !== null) {
      const still = datasets.value.find((row) => row.id === selected.value?.id)
      selected.value = still ?? null
      if (still === null) versions.value = []
    }
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    busy.value = false
  }
}

async function submitDataset(): Promise<void> {
  if (busy.value || name.value === '') return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const created = await createDataset(client, name.value)
    name.value = ''
    datasets.value = [created, ...datasets.value]
    notice.value = `已建立資料集「${created.name}」。`
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    busy.value = false
  }
}

async function select(dataset: Dataset): Promise<void> {
  selected.value = dataset
  error.value = ''
  notice.value = ''
  try {
    versions.value = (await listVersions(client, dataset.id)).items
  } catch (cause) {
    versions.value = []
    error.value = describeError(cause)
  }
}

async function reloadVersions(): Promise<void> {
  if (selected.value === null) return
  try {
    versions.value = (await listVersions(client, selected.value.id)).items
  } catch (cause) {
    error.value = describeError(cause)
  }
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const dataset = selected.value
  if (file === undefined || dataset === null || uploading.value) return
  uploading.value = true
  error.value = ''
  notice.value = ''
  lastRun.value = null
  try {
    const outcome = await uploadDatasetFile(client, dataset.id, file, (next) => {
      stage.value = next
    })
    versions.value = outcome.versions
    lastRun.value = outcome.run
    notice.value = `已上傳 ${file.name}（SHA-256 ${outcome.checksum.slice(0, 12)}…），匯入任務狀態：${outcome.run.status}。版本會在任務完成後出現，可重新載入。`
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    uploading.value = false
    stage.value = null
  }
}

onMounted(loadDatasets)
</script>

<template>
  <div class="grid">
    <section class="panel">
      <div class="panel-head">
        <h2>資料集</h2>
        <button type="button" :disabled="busy" @click="loadDatasets">重新載入</button>
      </div>

      <form class="create" @submit.prevent="submitDataset">
        <label>
          新資料集名稱
          <input v-model="name" name="dataset-name" maxlength="200" required>
        </label>
        <button type="submit" :disabled="busy || name === ''">建立資料集</button>
      </form>

      <p v-if="busy" class="muted">載入中…</p>
      <p v-else-if="datasets.length === 0" class="muted">尚無資料集，請先建立一個。</p>
      <ul v-else class="list">
        <li v-for="row in datasets" :key="row.id">
          <button type="button" :aria-pressed="selected?.id === row.id" :class="{ active: selected?.id === row.id }" @click="select(row)">
            <span class="name">{{ row.name }}</span>
            <span class="mono id">{{ row.id }}</span>
          </button>
        </li>
      </ul>
    </section>

    <section class="panel">
      <h2>上傳與版本</h2>
      <template v-if="selected === null">
        <p class="muted">請從左側選擇一個資料集。</p>
      </template>
      <template v-else>
        <p class="muted">目前資料集：<strong>{{ selected.name }}</strong></p>
        <p class="muted">{{ unsupportedNotice }}</p>
        <label class="upload">
          選擇檔案上傳
          <input type="file" accept=".csv,.json,.parquet" :disabled="uploading" @change="onFile">
        </label>
        <p v-if="uploading && stage !== null" class="progress" aria-live="polite">{{ stageLabel[stage] }}</p>

        <div class="panel-head">
          <h3>版本</h3>
          <button type="button" :disabled="uploading" @click="reloadVersions">重新載入</button>
        </div>
        <p v-if="versions.length === 0" class="muted">此資料集尚無版本。</p>
        <table v-else>
          <thead>
            <tr><th>建立時間</th><th>格式</th><th>列數</th><th>狀態</th><th>SHA-256</th><th>結構預覽</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in versions" :key="row.id">
              <td>{{ row.created_at }}</td>
              <td>{{ row.format }}</td>
              <td>{{ row.row_count }}</td>
              <td>{{ statusLabel[row.status] }}</td>
              <td class="mono">{{ row.sha256.slice(0, 16) }}…</td>
              <td>
                <template v-if="row.structure_preview_artifact_id !== null">
                  <RouterLink :to="{ name: 'artifact', params: { id: row.structure_preview_artifact_id } }">結構預覽</RouterLink>
                </template>
                <span v-else class="muted">無結構預覽</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="versions.length > 0" class="muted">
          原始位元組以非 PROJECT 存取等級保存，後端不對 API 開放讀取；表格只連到純結構預覽產物。
        </p>
      </template>
    </section>
  </div>

  <p v-if="error" class="alert" role="alert">{{ error }}</p>
  <output v-if="notice" class="notice">
    {{ notice }}
    <template v-if="lastRun !== null">
      <RouterLink :to="{ name: 'run', params: { id: lastRun.id } }">查看任務</RouterLink>
    </template>
  </output>

  <section class="pending" aria-label="尚未啟用功能">
    <h2>尚未啟用</h2>
    <p class="muted">下列功能屬後續里程碑，介面不提供操作也不以假資料填充：</p>
    <ul>
      <li>候選公式、推演與證據檢視</li>
      <li>基準測試、模型管理與封存評分</li>
      <li>搜尋進度與候選凍結</li>
    </ul>
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: minmax(16rem, 1fr) minmax(20rem, 2fr);
  gap: 1.25rem;
  align-items: start;
}
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  padding: 1.25rem;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
h2 {
  margin: 0 0 0.75rem;
  font-size: 1.15rem;
}
h3 {
  margin: 1.25rem 0 0.5rem;
  font-size: 1rem;
}
.create,
.upload {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.create label,
.upload {
  font-size: 0.9rem;
}
.create label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.list button {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.2rem;
  text-align: left;
}
.list button.active {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent);
}
.name {
  font-weight: 600;
}
.id {
  color: var(--text-muted);
}
.muted {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.progress {
  padding: 0.5rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--surface-muted);
}
.alert {
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--danger-surface);
  color: var(--danger);
}
.notice {
  display: block;
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--surface-muted);
}
.pending {
  margin-top: 1.5rem;
  border: 1px dashed var(--border);
  border-radius: 0.75rem;
  padding: 1rem 1.25rem;
}
.pending ul {
  margin: 0.5rem 0 0;
  color: var(--text-muted);
  font-size: 0.9rem;
}
@media (max-width: 48rem) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
