<script setup lang="ts">
/**
 * 資料品質（SSOT SCREEN 14，quality）：缺失、異常、偏移、洩漏風險。
 *
 * 後端只有資料集版本欄位與結構預覽可供判定：可判定檢核（狀態、指紋、列數、欄位）逐項列出，
 * 缺失值、異常值、分布偏移與洩漏風險沒有統計端點，一律標示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DataTabs from '../components/DataTabs.vue'
import { buildQualityChecks } from '../lib/datasetWorkbench'
import {
  DATA_UNKNOWN,
  DATASET_VERSION_STATUS_LABELS,
  FORMAT_LABELS,
  buildQualityDimensions,
  metadataForVersion,
  resolveVersionId,
  stepStatusLabel,
  summarizeQuality,
} from '../lib/dataCenter'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useDatasetWorkspace } from '../lib/useDataCenter'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const { workspace, loading, error, load } = useDatasetWorkspace(() => datasetId.value)

const selectedVersionId = ref(readQueryString(route.query, 'version'))

const versions = computed(() => workspace.value?.versions ?? [])
const selectedVersion = computed(() => versions.value.find((row) => row.id === selectedVersionId.value) ?? null)
const selectedMetadata = computed(() =>
  metadataForVersion(workspace.value?.metadataByArtifact ?? {}, selectedVersion.value),
)
const dimensions = computed(() => buildQualityDimensions(selectedVersion.value, selectedMetadata.value))
const checks = computed(() =>
  selectedVersion.value === null ? [] : buildQualityChecks(selectedVersion.value, selectedMetadata.value),
)
const summary = computed(() => summarizeQuality(checks.value))
const backRef = readQueryString(route.query, 'ref')

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
    if (route.name !== 'data-quality') return
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
        <div class="eyebrow">數據 / 第 14 頁</div>
        <h1>資料品質</h1>
        <p class="muted">
          缺失、異常、偏移、洩漏風險｜可判定檢核依後端已揭露欄位逐項列出；統計類品質面向沒有端點時一律標示「未取得」。
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
          <div class="eyebrow">通過</div>
          <div class="metric-value" :class="summary.pass > 0 ? 'good' : ''">{{ summary.pass }}</div>
          <p class="muted">可判定檢核中通過的項目數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">未通過</div>
          <div class="metric-value" :class="summary.fail > 0 ? 'bad' : 'good'">{{ summary.fail }}</div>
          <p class="muted">版本狀態、指紋、列數或欄位層級檢核未通過的項目數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">未取得</div>
          <div class="metric-value" :class="summary.unknown > 0 ? 'warn' : ''">{{ summary.unknown }}</div>
          <p class="muted">因缺少結構預覽而無法判定的項目數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">統計類品質面向</div>
          <div class="metric-value warn">{{ dimensions.length }}</div>
          <p class="muted">缺失、異常、偏移與洩漏風險皆需後端統計產物，目前一律「未取得」。</p>
        </section>
      </div>

      <div class="layout cols2">
        <section class="card">
          <h3>可判定檢核</h3>
          <div class="field">
            <label for="data-quality-version">資料版本</label>
            <select id="data-quality-version" v-model="selectedVersionId">
              <option v-if="versions.length === 0" value="">尚無版本</option>
              <option v-for="row in versions" :key="row.id" :value="row.id">
                {{ row.created_at }} · {{ FORMAT_LABELS[row.format] }} · {{ row.row_count }} 列
              </option>
            </select>
          </div>
          <p v-if="selectedVersion === null" class="muted">請先選擇一個資料版本。</p>
          <template v-else>
            <div class="row compact">
              <span>版本狀態</span>
              <span class="tag">{{ DATASET_VERSION_STATUS_LABELS[selectedVersion.status] }}</span>
            </div>
            <div class="check-list">
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
          </template>
        </section>

        <section class="card">
          <h3>品質面向</h3>
          <p class="muted">四類面向需要缺失值計數、離群規則、分布摘要與切分相關性；後端未揭露時一律標示未取得。</p>
          <div class="check-list">
            <div v-for="dimension in dimensions" :key="dimension.key" class="check-row">
              <span class="tag" :class="dimension.status === 'PASS' ? 'good' : dimension.status === 'FAIL' ? 'bad' : 'muted'">
                {{ stepStatusLabel(dimension.status) }}
              </span>
              <div>
                <strong>{{ dimension.label }}</strong>
                <div class="muted">{{ dimension.detail }}</div>
              </div>
            </div>
          </div>
          <div class="note" style="margin-top: 14px;">
            這一頁不推測品質分數：沒有統計產物就顯示「{{ DATA_UNKNOWN }}」，避免以 0 或估算值誤導。
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

.check-list {
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
  padding: 9px 0;
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
