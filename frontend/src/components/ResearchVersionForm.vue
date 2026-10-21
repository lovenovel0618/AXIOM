<script setup lang="ts">
/**
 * 語意確認表單：由結構預覽帶入欄位，人工指定映射、值域、切分與政策。
 * 送出前顯示完整請求內容；後端仍是唯一權威，前端不代替它放行或判定品質。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { getArtifactContent } from '../api/artifacts'
import { listDatasets, listVersions, type Dataset, type DatasetVersion } from '../api/datasets'
import { createResearchVersion, type ResearchVersion } from '../api/research'
import { describeError } from '../lib/messages'
import { client } from '../lib/session'
import {
  buildDraftRequest,
  DEFAULT_VERSION_FORM,
  parseSourceMetadata,
  sequentialSplit,
  type SourceMetadata,
  type VersionFormModel,
} from '../lib/semantics'

const props = defineProps<{ researchId: string }>()
const emit = defineEmits<{ created: [ResearchVersion] }>()

const datasets = ref<Dataset[]>([])
const versions = ref<DatasetVersion[]>([])
const selectedDatasetId = ref('')
const metadata = ref<SourceMetadata | null>(null)
const form = ref<VersionFormModel>({ ...DEFAULT_VERSION_FORM })
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const notice = ref('')

const partitions = computed(() => sequentialSplit(form.value.rowCount))
const draft = computed(() => buildDraftRequest(form.value))
const availableVersions = computed<DatasetVersion[]>(() =>
  versions.value.filter((row) => row.status === 'AVAILABLE' && row.structure_preview_artifact_id !== null),
)

async function loadDatasets(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    datasets.value = (await listDatasets(client)).items
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

async function loadVersions(): Promise<void> {
  versions.value = []
  form.value.datasetVersionId = ''
  metadata.value = null
  form.value.rowCount = 0
  if (selectedDatasetId.value === '') return
  loading.value = true
  error.value = ''
  try {
    versions.value = (await listVersions(client, selectedDatasetId.value)).items
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

async function loadMetadata(): Promise<void> {
  metadata.value = null
  form.value.rowCount = 0
  const version = versions.value.find((row) => row.id === form.value.datasetVersionId)
  if (version === undefined || version.structure_preview_artifact_id === null) return
  loading.value = true
  error.value = ''
  try {
    const content = await getArtifactContent<unknown>(client, version.structure_preview_artifact_id)
    const parsed = parseSourceMetadata(content)
    if (parsed === null) {
      error.value = '結構預覽產物格式不符，無法帶入欄位；請改選其他版本。'
      return
    }
    metadata.value = parsed
    form.value.rowCount = parsed.row_count
    const names = parsed.columns.map((column) => column.name)
    if (!names.includes(form.value.inputColumn)) form.value.inputColumn = names[0] ?? ''
    if (!names.includes(form.value.targetColumn)) form.value.targetColumn = names[1] ?? ''
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

async function submit(): Promise<void> {
  const outcome = draft.value
  if (outcome.request === null || submitting.value) return
  submitting.value = true
  error.value = ''
  notice.value = ''
  try {
    const version = await createResearchVersion(client, props.researchId, outcome.request)
    notice.value = `已建立研究版本，狀態 ${version.status}；固定切分與評估政策已保存，尚未執行任何驗證。`
    emit('created', version)
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    submitting.value = false
  }
}

watch(selectedDatasetId, () => {
  void loadVersions()
})
watch(
  () => form.value.datasetVersionId,
  () => {
    void loadMetadata()
  },
)
onMounted(loadDatasets)
</script>

<template>
  <section class="form">
    <h3>建立研究版本（語意確認）</h3>
    <p class="muted">
      前台只讀結構預覽（欄名與列數），不讀取樣本值；來源欄位角色、單位、值域與切分一律由你指定。
    </p>

    <div class="fields">
      <label>
        資料集
        <select v-model="selectedDatasetId" :disabled="loading">
          <option value="">請選擇</option>
          <option v-for="row in datasets" :key="row.id" :value="row.id">{{ row.name }}</option>
        </select>
      </label>

      <label>
        資料集版本
        <select v-model="form.datasetVersionId" :disabled="loading || availableVersions.length === 0">
          <option value="">請選擇</option>
          <option v-for="row in availableVersions" :key="row.id" :value="row.id">
            {{ row.format }}／{{ row.row_count }} 列／{{ row.created_at }}
          </option>
        </select>
      </label>
    </div>

    <p v-if="metadata !== null" class="muted">
      來源欄位：<span class="mono">{{ metadata.columns.map((column) => column.name).join('、') }}</span>
    </p>
    <p v-else-if="selectedDatasetId !== '' && availableVersions.length === 0" class="muted">
      此資料集尚無可用版本（需已完成匯入且具結構預覽）。
    </p>

    <h4>語意映射與單位</h4>
    <div class="fields">
      <label>
        輸入名稱
        <input v-model="form.inputName" maxlength="64">
      </label>
      <label>
        輸入來源欄位
        <select v-model="form.inputColumn">
          <option value="">請選擇</option>
          <option v-for="column in metadata?.columns ?? []" :key="column.name" :value="column.name">
            {{ column.name }}
          </option>
        </select>
      </label>
      <label>
        輸入量綱（7 個整數）
        <input v-model="form.inputUnit" class="mono">
      </label>
      <label>
        輸入單位／比例／位移
        <span class="row">
          <input v-model="form.inputSourceUnit" placeholder="來源單位" maxlength="64">
          <input v-model="form.inputScale" class="mono" placeholder="比例">
          <input v-model="form.inputOffset" class="mono" placeholder="位移">
        </span>
      </label>

      <label>
        目標名稱
        <input v-model="form.targetName" maxlength="64">
      </label>
      <label>
        目標來源欄位
        <select v-model="form.targetColumn">
          <option value="">請選擇</option>
          <option v-for="column in metadata?.columns ?? []" :key="column.name" :value="column.name">
            {{ column.name }}
          </option>
        </select>
      </label>
      <label>
        目標量綱（7 個整數）
        <input v-model="form.targetUnit" class="mono">
      </label>
      <label>
        目標單位／比例／位移
        <span class="row">
          <input v-model="form.targetSourceUnit" placeholder="來源單位" maxlength="64">
          <input v-model="form.targetScale" class="mono" placeholder="比例">
          <input v-model="form.targetOffset" class="mono" placeholder="位移">
        </span>
      </label>

      <label>
        量測解析度（可留白）
        <input v-model="form.measurementResolution" class="mono" placeholder="例 0.001">
      </label>
      <label>
        解析度理由
        <input v-model="form.resolutionReason" maxlength="256" placeholder="為何採用這個解析度">
      </label>
    </div>

    <h4>觀測值域與切分</h4>
    <div class="fields">
      <label>
        下界分子／分母
        <span class="row">
          <input v-model="form.domainLowerNumerator" class="mono">
          <input v-model="form.domainLowerDenominator" class="mono">
        </span>
      </label>
      <label>
        上界分子／分母
        <span class="row">
          <input v-model="form.domainUpperNumerator" class="mono">
          <input v-model="form.domainUpperDenominator" class="mono">
        </span>
      </label>
      <label>
        種子
        <input v-model="form.seed" class="mono">
      </label>
      <label>
        研究目的
        <select v-model="form.purpose">
          <option value="DESCRIPTION">DESCRIPTION</option>
          <option value="PREDICTION">PREDICTION</option>
          <option value="MECHANISM">MECHANISM</option>
        </select>
      </label>
      <label>
        基準線
        <select v-model="form.baseline">
          <option value="FIT_MEAN">FIT_MEAN</option>
          <option value="ZERO">ZERO</option>
        </select>
      </label>
      <label>
        實務邊界比例
        <input v-model="form.practicalMarginRatio" class="mono">
      </label>
    </div>
    <p class="muted">
      切分固定為依列序 EXPLICIT（splitter {{ 'axiom-ui-sequential-v1' }}），時間序與群組依賴後端尚未開放，因此一律不宣告。
      <template v-if="partitions !== null">
        fit {{ partitions.fit.length }} 列／development {{ partitions.development.length }} 列／final_test
        {{ partitions.final_test.length }} 列。
      </template>
    </p>

    <h4>研究帳本限額</h4>
    <div class="fields">
      <label>
        CPU 秒
        <input v-model="form.cpuSeconds" class="mono">
      </label>
      <label>
        GPU 秒
        <input v-model="form.gpuSeconds" class="mono">
      </label>
      <label>
        牆鐘秒
        <input v-model="form.wallSeconds" class="mono">
      </label>
      <label>
        Token 上限
        <input v-model="form.tokens" class="mono">
      </label>
      <label>
        候選上限
        <input v-model="form.candidateLimit" class="mono">
      </label>
      <label>
        記憶體位元組
        <input v-model="form.memoryBytes" class="mono">
      </label>
    </div>
    <p class="muted">
      此限額即研究帳本上限，不能被後續任務重置。後端要求記憶體至少 2 GiB、CPU 與牆鐘秒數不超過 300；不符時建立
      PROFILE 任務會回 429。
    </p>

    <ul v-if="draft.problems.length > 0" class="problems" role="alert">
      <li v-for="item in draft.problems" :key="item">{{ item }}</li>
    </ul>

    <details class="payload">
      <summary>將送出的請求內容</summary>
      <pre class="mono">{{ draft.request === null ? '（檢查未通過，尚未產生請求）' : JSON.stringify(draft.request, null, 2) }}</pre>
    </details>

    <button type="submit" :disabled="draft.request === null || submitting" @click="submit">
      {{ submitting ? '建立中…' : '建立研究版本' }}
    </button>

    <p v-if="error" class="alert" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.form {
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  padding: 1rem 1.25rem;
  background: var(--surface);
}
h3 {
  margin: 0 0 0.5rem;
  font-size: 1rem;
}
h4 {
  margin: 1rem 0 0.35rem;
  font-size: 0.95rem;
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 0.6rem 0.9rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.9rem;
}
.row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.35rem;
}
input,
select {
  width: 100%;
}
.problems {
  margin: 0.75rem 0;
  padding: 0.6rem 0.75rem 0.6rem 1.75rem;
  border-radius: 0.4rem;
  background: var(--danger-surface);
  color: var(--danger);
  font-size: 0.9rem;
}
.payload {
  margin: 0.75rem 0;
  font-size: 0.9rem;
}
.payload pre {
  max-height: 18rem;
  overflow: auto;
  background: var(--surface-muted);
  border-radius: 0.4rem;
  padding: 0.6rem;
}
.muted {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.alert {
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--danger-surface);
  color: var(--danger);
}
.notice {
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--surface-muted);
}
</style>
