<script setup lang="ts">
/**
 * 資料預覽（SSOT SCREEN 13，grid）：欄位、取樣、搜尋與資料字典。
 *
 * 只呈現結構預覽產物已揭露的欄位與列數；取樣列內容、量測單位與語意定義在後端沒有端點，
 * 一律標示「未取得」，不以推測補值。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DataTabs from '../components/DataTabs.vue'
import {
  DATA_UNKNOWN,
  DATASET_VERSION_STATUS_LABELS,
  FORMAT_LABELS,
  buildPreviewTable,
  filterPreviewFields,
  metadataForVersion,
  resolveVersionId,
} from '../lib/dataCenter'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useDatasetWorkspace } from '../lib/useDataCenter'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const { workspace, loading, error, load } = useDatasetWorkspace(() => datasetId.value)

const selectedVersionId = ref(readQueryString(route.query, 'version'))
const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))

const versions = computed(() => workspace.value?.versions ?? [])
const selectedVersion = computed(() => versions.value.find((row) => row.id === selectedVersionId.value) ?? null)
const selectedMetadata = computed(() =>
  metadataForVersion(workspace.value?.metadataByArtifact ?? {}, selectedVersion.value),
)
const table = computed(() =>
  selectedVersion.value === null ? null : buildPreviewTable(selectedVersion.value, selectedMetadata.value),
)
const fields = computed(() => (table.value === null ? [] : filterPreviewFields(table.value.fields, appliedKeyword.value)))
const backRef = readQueryString(route.query, 'ref')

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
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
    if (route.name !== 'data-preview') return
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
        <div class="eyebrow">數據 / SCREEN 13</div>
        <h1>資料預覽</h1>
        <p class="muted">
          欄位、取樣、搜尋與資料字典｜欄位與列數取自不可變版本的結構預覽產物；取樣列內容與語意定義未揭露時標示「未取得」。
        </p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'datasets' }"><button type="button">返回資料集清單</button></RouterLink>
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && workspace === null" class="muted">載入中…</p>
    <p v-else-if="workspace === null" class="bad">{{ error === '' ? '未取得此資料集。' : error }}</p>
    <template v-else>
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">宣告列數</div>
          <div class="metric-value">{{ table === null ? DATA_UNKNOWN : table.declaredRowCount }}</div>
          <p class="muted">後端回報的不可變版本列數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">結構預覽列數</div>
          <div class="metric-value">{{ table === null || table.previewRowCount === null ? DATA_UNKNOWN : table.previewRowCount }}</div>
          <p class="muted">結構預覽產物內的列數；與宣告列數不一致時檢核會標示未通過。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">欄位數</div>
          <div class="metric-value">{{ table === null ? DATA_UNKNOWN : table.fields.length }}</div>
          <p class="muted">結構預覽產物揭露的欄位數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">資料字典條目</div>
          <div class="metric-value">{{ table === null ? DATA_UNKNOWN : table.dictionaryEntryCount }}</div>
          <p class="muted">以已揭露欄位為條目數；定義文字未揭露時不補值。</p>
        </section>
      </div>

      <div class="layout cols2">
        <section class="card">
          <h3>選定版本與欄位</h3>
          <div class="formgrid">
            <div class="field">
              <label for="data-preview-version">資料版本</label>
              <select id="data-preview-version" v-model="selectedVersionId">
                <option v-if="versions.length === 0" value="">尚無版本</option>
                <option v-for="row in versions" :key="row.id" :value="row.id">
                  {{ row.created_at }} · {{ FORMAT_LABELS[row.format] }} · {{ row.row_count }} 列
                </option>
              </select>
            </div>
            <div class="field">
              <label for="data-preview-keyword">欄位搜尋</label>
              <input
                id="data-preview-keyword"
                v-model="keyword"
                name="data-preview-keyword"
                maxlength="200"
                placeholder="欄位名稱或實體型別"
              >
            </div>
          </div>
          <div class="actions">
            <button type="button" @click="applySearch">🔍 搜尋</button>
          </div>

          <p v-if="selectedVersion === null" class="muted">請先選擇一個資料版本。</p>
          <template v-else>
            <div class="row compact">
              <span>版本狀態</span>
              <span class="tag">{{ DATASET_VERSION_STATUS_LABELS[selectedVersion.status] }}</span>
            </div>
            <p v-if="fields.length === 0" class="muted">未取得此版本的結構預覽欄位，或沒有符合關鍵字的欄位。</p>
            <table v-else>
              <thead>
                <tr><th>欄位</th><th>實體型別</th><th>標記</th></tr>
              </thead>
              <tbody>
                <tr v-for="field in fields" :key="field.name">
                  <td class="mono record-value">{{ field.name }}</td>
                  <td>{{ field.physicalType === '' ? DATA_UNKNOWN : field.physicalType }}</td>
                  <td>
                    <span v-if="field.duplicate" class="tag bad">名稱重複</span>
                    <span v-if="field.missingType" class="tag warn">型別未提供</span>
                    <span v-if="!field.duplicate && !field.missingType" class="muted">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
        </section>

        <section class="card">
          <h3>取樣與資料字典</h3>
          <div class="unknown-list">
            <div class="row compact">
              <span>取樣列（前 N 列內容）</span>
              <span class="muted">{{ DATA_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>量測單位與語意定義</span>
              <span class="muted">{{ DATA_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>欄位值域與分布摘要</span>
              <span class="muted">{{ DATA_UNKNOWN }}</span>
            </div>
          </div>
          <div class="note" style="margin-top: 14px;">
            後端只提供結構預覽（列數與欄位），沒有取樣列與語意定義端點；這一頁明示缺漏，不以推測內容填充。
          </div>
        </section>
      </div>

      <p v-if="error !== ''" class="bad" style="margin-top: 16px;">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
}

.metric-card {
  min-height: 140px;
}

.metric-value {
  font-size: 28px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.compact {
  padding: 9px 0;
}

.record-value {
  max-width: 60%;
  overflow-wrap: anywhere;
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
