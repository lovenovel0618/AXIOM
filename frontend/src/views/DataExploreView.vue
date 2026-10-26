<script setup lang="ts">
/**
 * 多維探索（SSOT SCREEN 16，explore）：時間、相空間、頻域及高維投影。
 *
 * 座標軸只由結構預覽的欄位與型別推導；四類投影都需要後端統計或降維產物，一律標示「未取得」，
 * 不假造座標或圖形資料。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DataTabs from '../components/DataTabs.vue'
import {
  DATA_UNKNOWN,
  FORMAT_LABELS,
  buildExploreAxes,
  buildExploreProjections,
  metadataForVersion,
  resolveVersionId,
  stepStatusLabel,
  type AxisKind,
} from '../lib/dataCenter'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useDatasetWorkspace } from '../lib/useDataCenter'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const { workspace, loading, error, load } = useDatasetWorkspace(() => datasetId.value)

const selectedVersionId = ref(readQueryString(route.query, 'version'))
const selectedAxisName = ref(readQueryString(route.query, 'dimension'))

const KIND_LABELS: Record<AxisKind, string> = { NUMERIC: '數值', TEXT: '文字／類別', UNKNOWN: '未取得' }

const versions = computed(() => workspace.value?.versions ?? [])
const selectedVersion = computed(() => versions.value.find((row) => row.id === selectedVersionId.value) ?? null)
const selectedMetadata = computed(() =>
  metadataForVersion(workspace.value?.metadataByArtifact ?? {}, selectedVersion.value),
)
const axes = computed(() => buildExploreAxes(selectedMetadata.value))
const projections = computed(() => buildExploreProjections(axes.value))
const numericCount = computed(() => axes.value.filter((axis) => axis.kind === 'NUMERIC').length)
const selectedAxis = computed(() => axes.value.find((axis) => axis.name === selectedAxisName.value) ?? null)
const backRef = readQueryString(route.query, 'ref')

function selectVersion(id: string): void {
  selectedVersionId.value = id
}

function selectAxis(name: string): void {
  selectedAxisName.value = name
}

onMounted(async () => {
  await load()
  selectedVersionId.value = resolveVersionId(versions.value, readQueryString(route.query, 'version'))
})

watch(
  () => route.params.id,
  async () => {
    if (route.name !== 'data-explore') return
    await load()
    selectedVersionId.value = resolveVersionId(versions.value, readQueryString(route.query, 'version'))
  },
)

watch(selectedVersionId, async (value) => {
  await replaceQueryState(router, route, { version: value })
})

watch(selectedAxisName, async (value) => {
  await replaceQueryState(router, route, { dimension: value })
})
</script>

<template>
  <section>
    <DataTabs :dataset-id="datasetId" />

    <div class="head">
      <div>
        <div class="eyebrow">數據 / SCREEN 16</div>
        <h1>多維探索</h1>
        <p class="muted">
          時間、相空間、頻域及高維投影｜候選座標軸取自結構預覽；投影座標與統計摘要沒有後端產物時一律標示「未取得」。
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
          <div class="eyebrow">候選座標軸</div>
          <div class="metric-value">{{ axes.length === 0 ? DATA_UNKNOWN : axes.length }}</div>
          <p class="muted">結構預覽揭露的欄位數，作為可探索座標軸的上限。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">數值軸</div>
          <div class="metric-value">{{ axes.length === 0 ? DATA_UNKNOWN : numericCount }}</div>
          <p class="muted">依實體型別判定為數值的欄位數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">選定軸</div>
          <div class="metric-value">{{ selectedAxis === null ? DATA_UNKNOWN : selectedAxis.name }}</div>
          <p class="muted">以 `dimension` 承接，重新整理後可還原。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">投影種類</div>
          <div class="metric-value">{{ projections.length }}</div>
          <p class="muted">時間／相空間／頻域／高維，四類皆需後端產物。</p>
        </section>
      </div>

      <div class="layout cols2">
        <section class="card">
          <h3>候選座標軸</h3>
          <div class="field">
            <label for="data-explore-version">資料版本</label>
            <select id="data-explore-version" v-model="selectedVersionId">
              <option v-if="versions.length === 0" value="">尚無版本</option>
              <option v-for="row in versions" :key="row.id" :value="row.id">
                {{ row.created_at }} · {{ FORMAT_LABELS[row.format] }} · {{ row.row_count }} 列
              </option>
            </select>
          </div>
          <p v-if="selectedVersion === null" class="muted">請先選擇一個資料版本。</p>
          <p v-else-if="axes.length === 0" class="muted">未取得此版本的結構預覽，沒有可用的候選座標軸。</p>
          <table v-else>
            <thead>
              <tr><th>座標軸</th><th>實體型別</th><th>判定</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="axis in axes" :key="axis.name" :class="{ active: axis.name === selectedAxisName }">
                <td class="mono">{{ axis.name }}</td>
                <td>{{ axis.physicalType === '' ? DATA_UNKNOWN : axis.physicalType }}</td>
                <td><span class="tag" :class="axis.kind === 'NUMERIC' ? 'good' : axis.kind === 'UNKNOWN' ? 'muted' : ''">{{ KIND_LABELS[axis.kind] }}</span></td>
                <td><button type="button" :class="{ primary: axis.name === selectedAxisName }" @click="selectAxis(axis.name)">選定</button></td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>投影與圖形</h3>
          <div class="check-list">
            <div v-for="projection in projections" :key="projection.key" class="check-row">
              <span class="tag" :class="projection.status === 'PASS' ? 'good' : projection.status === 'FAIL' ? 'bad' : 'muted'">
                {{ stepStatusLabel(projection.status) }}
              </span>
              <div>
                <strong>{{ projection.label }}</strong>
                <div class="muted">{{ projection.detail }}</div>
              </div>
            </div>
          </div>
          <div class="note" style="margin-top: 14px;">
            這一頁不繪製推測圖形：沒有投影座標就顯示「{{ DATA_UNKNOWN }}」，避免以示意圖誤導判讀。
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
  font-size: 24px;
  font-weight: 700;
  margin: 10px 0 8px;
  overflow-wrap: anywhere;
}

tbody tr.active td {
  background: #132842;
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
