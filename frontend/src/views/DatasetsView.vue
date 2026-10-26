<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { getArtifactContent } from '../api/artifacts'
import {
  createDataset,
  listDatasetRuns,
  listDatasets,
  listVersions,
  type Dataset,
  type DatasetVersion,
  type DatasetVersionStatus,
  type RunRecord,
} from '../api/datasets'
import { createResearch, createResearchVersion, getResearchVersion, validateDraft } from '../api/research'
import { describeError } from '../lib/messages'
import { buildQuickResearchDraft, quickResearchName } from '../lib/quickResearch'
import { parseSourceMetadata } from '../lib/semantics'
import { client } from '../lib/session'
import { uploadDatasetFile, type UploadStage } from '../lib/upload'

const router = useRouter()
const datasets = ref<Dataset[]>([])
const versions = ref<DatasetVersion[]>([])
const runs = ref<RunRecord[]>([])
const selected = ref<Dataset | null>(null)
const name = ref('')
const busy = ref(false)
const uploading = ref(false)
const analyzing = ref(false)
const stage = ref<UploadStage | null>(null)
const error = ref('')
const notice = ref('')
const lastRun = ref<RunRecord | null>(null)

const latestAvailableVersion = computed<DatasetVersion | null>(() =>
  versions.value.find((row) => row.status === 'AVAILABLE' && row.structure_preview_artifact_id !== null) ?? null,
)

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

async function loadDatasets(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    datasets.value = (await listDatasets(client)).items
    if (selected.value !== null) {
      const still = datasets.value.find((row) => row.id === selected.value?.id)
      selected.value = still ?? null
      if (still === null) {
        versions.value = []
        runs.value = []
      }
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
  versions.value = []
  runs.value = []
  try {
    versions.value = (await listVersions(client, dataset.id)).items
  } catch (cause) {
    versions.value = []
    error.value = describeError(cause)
  }
  await reloadRuns()
}

async function reloadVersions(): Promise<void> {
  if (selected.value === null) return
  try {
    versions.value = (await listVersions(client, selected.value.id)).items
  } catch (cause) {
    error.value = describeError(cause)
  }
}

/** AX-44：重開匯入頁時以這份清單尋回 INGEST 任務；失敗只提示，不清空既有畫面。 */
async function reloadRuns(): Promise<void> {
  const dataset = selected.value
  if (dataset === null) return
  try {
    runs.value = (await listDatasetRuns(client, dataset.id)).items
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
    const renewed = outcome.renewedSession
      ? '原上傳工作階段已過期，已另建新工作階段並重新傳輸檔案（不提供續傳）。'
      : ''
    notice.value = `已上傳 ${file.name}（SHA-256 ${outcome.checksum.slice(0, 12)}…），匯入任務狀態：${outcome.run.status}。${renewed}版本會在任務完成後出現，可重新載入。`
    await reloadRuns()
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    uploading.value = false
    stage.value = null
  }
}

async function analyzeDataset(): Promise<void> {
  const dataset = selected.value
  const version = latestAvailableVersion.value
  if (dataset === null || version === null || analyzing.value) return
  if (version.structure_preview_artifact_id === null) {
    error.value = '此資料集版本沒有結構預覽，無法自動建立分析草稿。'
    return
  }

  analyzing.value = true
  error.value = ''
  notice.value = ''
  try {
    const content = await getArtifactContent<unknown>(client, version.structure_preview_artifact_id)
    const metadata = parseSourceMetadata(content)
    if (metadata === null) {
      error.value = '結構預覽產物格式不符，無法自動建立分析草稿。'
      return
    }
    const draft = buildQuickResearchDraft(version, metadata)
    if (draft.request === null) {
      error.value = `無法自動建立分析草稿：${draft.problems.join('；')}`
      return
    }

    const research = await createResearch(client, quickResearchName(dataset.name))
    const createdVersion = await createResearchVersion(client, research.id, draft.request)
    const run = await validateDraft(client, createdVersion.id, createdVersion.revision)
    const freshVersion = await getResearchVersion(client, createdVersion.id)
    notice.value = `已從資料集「${dataset.name}」建立研究並啟動分析，任務狀態：${run.status}。`
    await router.push({
      name: 'researches',
      params: { id: research.id },
      query: { version: freshVersion.id },
    })
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    analyzing.value = false
  }
}

onMounted(loadDatasets)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">數據 / SCREEN</div>
        <h1>資料集清單</h1>
        <p class="muted">資料來源、版本、權限與品質狀態都在這裡管理。</p>
      </div>
      <div class="actions">
        <button type="button" @click="loadDatasets">重新載入</button>
        <button type="button" class="primary" :disabled="busy || name === ''" @click="submitDataset">新增 / 執行</button>
      </div>
    </div>

    <div class="layout cols2">
      <section class="card">
        <h3>搜尋與篩選</h3>
        <div class="formgrid">
          <div class="field">
            <label>新資料集名稱</label>
            <input v-model="name" name="dataset-name" maxlength="200" placeholder="請輸入資料集名稱">
          </div>
          <div class="field">
            <label>狀態</label>
            <select disabled>
              <option>全部</option>
            </select>
          </div>
        </div>
        <div class="actions">
          <button type="button" class="primary" :disabled="busy || name === ''" @click="submitDataset">建立新項目</button>
          <button type="button" @click="name = ''">匯出清單</button>
        </div>

        <h3 style="margin-top: 24px;">項目清單</h3>
        <p v-if="busy" class="muted">載入中…</p>
        <p v-else-if="datasets.length === 0" class="muted">尚無資料集，請先建立一個。</p>
        <table v-else>
          <thead>
            <tr>
              <th>編號</th>
              <th>名稱</th>
              <th>建立時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in datasets" :key="row.id">
              <td class="mono">{{ row.id }}</td>
              <td>{{ row.name }}</td>
              <td>{{ row.created_at }}</td>
              <td><button type="button" @click="select(row)">開啟</button></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="card">
        <h3>資料集詳情</h3>
        <template v-if="selected === null">
          <p class="muted">請先從左側資料集清單選擇一筆。</p>
        </template>
        <template v-else>
          <div class="row">
            <div>
              <strong>{{ selected.name }}</strong>
              <div class="mono">{{ selected.id }}</div>
            </div>
            <button
              type="button"
              class="primary"
              :disabled="uploading || analyzing || latestAvailableVersion === null"
              @click="analyzeDataset"
            >
              {{ analyzing ? '分析中…' : '分析' }}
            </button>
          </div>

          <div class="field">
            <label>上傳資料檔</label>
            <input type="file" accept=".csv,.json,.parquet" :disabled="uploading" @change="onFile">
          </div>
          <p class="muted">{{ unsupportedNotice }}</p>
          <p v-if="uploading && stage !== null" class="tag" aria-live="polite">{{ stageLabel[stage] }}</p>
          <p v-if="latestAvailableVersion === null" class="muted">需先有至少一個可用版本才能分析。</p>

          <h3 style="margin-top: 22px;">版本</h3>
          <div class="actions" style="margin-bottom: 10px;">
            <button type="button" :disabled="uploading" @click="reloadVersions">重新載入</button>
          </div>
          <p v-if="versions.length === 0" class="muted">此資料集尚無版本。</p>
          <table v-else>
            <thead>
              <tr><th>建立時間</th><th>格式</th><th>列數</th><th>狀態</th><th>結構預覽</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in versions" :key="row.id">
                <td>{{ row.created_at }}</td>
                <td>{{ row.format }}</td>
                <td>{{ row.row_count }}</td>
                <td><span class="tag">{{ statusLabel[row.status] }}</span></td>
                <td>
                  <RouterLink v-if="row.structure_preview_artifact_id !== null" :to="{ name: 'artifact', params: { id: row.structure_preview_artifact_id } }">結構預覽</RouterLink>
                  <span v-else class="muted">無結構預覽</span>
                </td>
              </tr>
            </tbody>
          </table>

          <h3 style="margin-top: 22px;">匯入任務</h3>
          <div class="actions" style="margin-bottom: 10px;">
            <button type="button" :disabled="uploading" @click="reloadRuns">重新載入</button>
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
                <td><RouterLink :to="{ name: 'run', params: { id: row.id } }">查看任務</RouterLink></td>
              </tr>
            </tbody>
          </table>
        </template>
      </section>
    </div>

    <p v-if="error" class="bad" style="margin-top: 16px;">{{ error }}</p>
    <output v-if="notice" class="good" style="display: block; margin-top: 16px;">
      {{ notice }}
      <template v-if="lastRun !== null">
        <RouterLink :to="{ name: 'run', params: { id: lastRun.id } }">查看任務</RouterLink>
      </template>
    </output>
  </section>
</template>

<style scoped>
.good a { color: inherit; text-decoration: underline; }
</style>
