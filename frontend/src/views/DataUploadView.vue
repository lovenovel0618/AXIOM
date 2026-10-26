<script setup lang="ts">
/**
 * 資料上傳精靈（SSOT SCREEN 12，wizard）：匯入、映射、檢核與不可變快照。
 *
 * 四道程序逐項依後端已揭露狀態判定（版本、結構預覽、可判定檢核、版本狀態）；研究目標、
 * AUTO／DEEP 預算與外部傳輸審核在後端沒有對應欄位或端點，一律標示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DataTabs from '../components/DataTabs.vue'
import {
  DATASET_VERSION_STATUS_LABELS,
  FORMAT_LABELS,
  buildUploadSteps,
  metadataForVersion,
  resolveVersionId,
  stepStatusLabel,
  type WizardStep,
} from '../lib/dataCenter'
import { describeError } from '../lib/messages'
import { withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'
import { useDatasetWorkspace } from '../lib/useDataCenter'
import { uploadDatasetFile, type UploadStage } from '../lib/upload'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const { workspace, loading, error, load } = useDatasetWorkspace(() => datasetId.value)

const selectedVersionId = ref(readQueryString(route.query, 'version'))
const uploading = ref(false)
const stage = ref<UploadStage | null>(null)
const notice = ref('')

const stageLabel: Record<UploadStage, string> = {
  hashing: '計算內容雜湊…',
  session: '建立上傳工作階段…',
  transfer: '傳輸檔案位元組…',
  complete: '排入匯入任務…',
}

const versions = computed(() => workspace.value?.versions ?? [])
const runs = computed(() => workspace.value?.runs ?? [])
const selectedVersion = computed(() => versions.value.find((row) => row.id === selectedVersionId.value) ?? null)
const selectedMetadata = computed(() =>
  metadataForVersion(workspace.value?.metadataByArtifact ?? {}, selectedVersion.value),
)
const steps = computed<WizardStep[]>(() => buildUploadSteps(selectedVersion.value, selectedMetadata.value, runs.value))
const doneCount = computed(() => steps.value.filter((step) => step.status === 'PASS').length)
const backRef = readQueryString(route.query, 'ref')

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file === undefined || uploading.value) return
  uploading.value = true
  error.value = ''
  notice.value = ''
  try {
    const outcome = await uploadDatasetFile(client, datasetId.value, file, (next) => {
      stage.value = next
    })
    const renewed = outcome.renewedSession
      ? '原上傳工作階段已過期，已另建新工作階段並重新傳輸檔案（不提供續傳）。'
      : ''
    notice.value = `已上傳 ${file.name}（SHA-256 ${outcome.checksum.slice(0, 12)}…），匯入任務狀態：${outcome.run.status}。${renewed}版本會在任務完成後出現，可重新載入。`
    await load()
    selectedVersionId.value = resolveVersionId(versions.value, selectedVersionId.value)
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    uploading.value = false
    stage.value = null
  }
}

function selectVersion(id: string): void {
  selectedVersionId.value = id
}

onMounted(async () => {
  await load()
  selectedVersionId.value = resolveVersionId(versions.value, readQueryString(route.query, 'version'))
})

watch(
  () => route.params.id,
  async () => {
    if (route.name !== 'data-upload') return
    await load()
    selectedVersionId.value = resolveVersionId(versions.value, readQueryString(route.query, 'version'))
  },
)

watch(selectedVersionId, async (value) => {
  await replaceQueryState(router, route, { version: value })
})
</script>

<template>
  <section>
    <DataTabs :dataset-id="datasetId" />

    <div class="head">
      <div>
        <div class="eyebrow">數據 / 第 12 頁</div>
        <h1>資料上傳精靈</h1>
        <p class="muted">
          匯入、映射、檢核與不可變快照｜四道程序只依後端已揭露狀態判定，未揭露的欄位標示「未取得」而非以預設值送出。
        </p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'datasets' }"><button type="button">返回資料集清單</button></RouterLink>
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && workspace === null" class="muted">載入中…</p>
    <p v-else-if="workspace === null" class="bad">{{ error === '' ? '未取得此資料集，可能已被刪除或不在可見範圍內。' : error }}</p>
    <template v-else>
      <div class="row">
        <div>
          <strong>{{ workspace.dataset === null ? '未取得資料集' : workspace.dataset.name }}</strong>
          <div class="mono record-value">{{ datasetId }}</div>
        </div>
        <span class="tag">已完成程序 {{ doneCount }} / {{ steps.length }}</span>
      </div>

      <div class="layout cols2" style="margin-top: 16px;">
        <section class="card">
          <h3>精靈程序</h3>
          <p class="muted">依序為匯入與不可變登記、欄位映射、完整性檢核與不可變快照。</p>
          <ol class="step-list">
            <li v-for="(step, index) in steps" :key="step.key" class="step-row">
              <span class="step-index">{{ index + 1 }}</span>
              <div class="step-body">
                <div class="step-head">
                  <strong>{{ step.label }}</strong>
                  <span
                    class="tag"
                    :class="step.status === 'PASS' ? 'good' : step.status === 'FAIL' ? 'bad' : 'muted'"
                  >{{ stepStatusLabel(step.status) }}</span>
                </div>
                <div class="muted">{{ step.detail }}</div>
              </div>
            </li>
          </ol>

          <h3 style="margin-top: 22px;">上傳資料檔</h3>
          <div class="field">
            <label for="data-upload-file">資料檔</label>
            <input
              id="data-upload-file"
              type="file"
              accept=".csv,.json,.parquet"
              :disabled="uploading"
              @change="onFile"
            >
          </div>
          <p class="muted">支援格式：CSV、JSON、PARQUET（上限 50 MiB）。</p>
          <p v-if="uploading && stage !== null" class="tag" aria-live="polite">{{ stageLabel[stage] }}</p>
        </section>

        <section class="card">
          <h3>版本與不可變快照</h3>
          <p v-if="versions.length === 0" class="muted">此資料集尚無版本；上傳完成並待匯入任務成功後才會出現。</p>
          <table v-else>
            <thead>
              <tr><th>建立時間</th><th>格式</th><th>列數</th><th>狀態</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in versions" :key="row.id">
                <td>{{ row.created_at }}</td>
                <td>{{ FORMAT_LABELS[row.format] }}</td>
                <td>{{ row.row_count }}</td>
                <td>
                  <span class="tag" :class="row.status === 'AVAILABLE' ? 'good' : 'bad'">
                    {{ DATASET_VERSION_STATUS_LABELS[row.status] }}
                  </span>
                </td>
                <td>
                  <button type="button" :class="{ primary: row.id === selectedVersionId }" @click="selectVersion(row.id)">
                    檢視程序
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <h3 style="margin-top: 22px;">匯入任務</h3>
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
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">研究目標與問題定義</div>
          <p class="unknown-value">未取得</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">AUTO／DEEP 與預算設定</div>
          <p class="unknown-value">未取得</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">外部傳輸與權限審核</div>
          <p class="unknown-value">未取得</p>
        </section>
      </div>

      <p v-if="error !== ''" class="bad" style="margin-top: 16px;">{{ error }}</p>
      <output v-if="notice" class="good" style="display: block; margin-top: 16px;">{{ notice }}</output>
    </template>
  </section>
</template>

<style scoped>
.step-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-row {
  display: flex;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
}

.step-index {
  width: 26px;
  height: 26px;
  flex: none;
  border-radius: 50%;
  background: #12345b;
  color: #8ec7ff;
  display: grid;
  place-items: center;
  font-size: 12px;
}

.step-body {
  min-width: 0;
  flex: 1;
}

.step-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.unknown-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 16px;
}

.unknown-card {
  border-style: dashed;
}

.unknown-value {
  margin: 8px 0 0;
  color: #9fb3c8;
}

.record-value {
  max-width: 100%;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .unknown-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .unknown-grid {
    grid-template-columns: 1fr;
  }
}
</style>
