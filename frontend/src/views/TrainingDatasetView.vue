<script setup lang="ts">
/**
 * 訓練資料集（SSOT SCREEN 36）：已驗證經驗樣本、標籤與品質門檻。
 *
 * 後端沒有訓練資料集端點，本頁只把研究版本宣告的凍結提交（frozen submission）當成
 * 樣本來源，並以可讀的最終評估推導樣本狀態；標籤政策取版本固定的評估政策指紋，
 * 品質門檻後端未揭露，一律標示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import TrainingTabs from '../components/TrainingTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useTrainingCenter } from '../lib/useTrainingCenter'
import {
  TRAINING_UNKNOWN,
  VERSION_STATUS_LABELS,
  buildTrainingDatasets,
  filterTrainingDatasets,
  summarizeTrainingDatasets,
  type TrainingDatasetRow,
} from '../lib/trainingCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useTrainingCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const selectedId = ref(readQueryString(route.query, 'version'))

const rows = computed<TrainingDatasetRow[]>(() =>
  center.value === null ? [] : buildTrainingDatasets(center.value),
)
const visible = computed(() => filterTrainingDatasets(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeTrainingDatasets(rows.value))
const selectedRow = computed<TrainingDatasetRow | null>(
  () => rows.value.find((row) => row.versionId === selectedId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => center.value?.scope.truncated ?? false)
const workbenchQuery = computed<Record<string, string>>(() =>
  withBackRef(route.fullPath, { version: selectedRow.value?.versionId }),
)

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

function selectRow(row: TrainingDatasetRow): void {
  selectedId.value = row.versionId
}

onMounted(async () => {
  await load()
  if (selectedId.value === '' && rows.value.length > 0) selectedId.value = rows.value[0]?.versionId ?? ''
})

watch(selectedId, async (value) => {
  await replaceQueryState(router, route, { version: value === '' ? undefined : value })
})

watch(
  () => route.query.version,
  () => {
    selectedId.value = readQueryString(route.query, 'version')
  },
)

watch(visible, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.versionId === selectedId.value)) return
  selectedId.value = value[0]?.versionId ?? ''
})
</script>

<template>
  <section>
    <TrainingTabs />

    <div class="head">
      <div>
        <div class="eyebrow">訓練 / SCREEN 36</div>
        <h1>訓練資料集</h1>
        <p class="muted">
          專屬任務畫面設計｜已驗證經驗樣本、標籤與品質門檻：樣本以研究版本宣告的凍結提交為來源，狀態由可讀的最終評估推導；品質門檻後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <label class="field">
          <span class="field-label">搜尋訓練資料集</span>
          <input v-model="keyword" placeholder="研究名稱、版本 ID 或研究目的" @keyup.enter="applySearch" />
        </label>
        <button type="button" @click="applySearch">搜尋</button>
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">訓練資料集</div>
          <div class="metric-value">{{ summary.datasets }}</div>
          <p>已讀取範圍內宣告了凍結提交的研究版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">宣告樣本</div>
          <div class="metric-value">{{ summary.declared }}</div>
          <p>版本宣告的凍結提交總數；超過本頁讀取上限時只計已讀取者並標示截斷。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已評估樣本</div>
          <div class="metric-value" :class="summary.evaluated > 0 ? 'good' : 'warn'">{{ summary.evaluated }}</div>
          <p>最終評估狀態為「已評估」的樣本數；讀不到的樣本不計入，也不以 0 代替。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">失敗樣本</div>
          <div class="metric-value" :class="summary.failed > 0 ? 'bad' : ''">{{ summary.failed }}</div>
          <p>最終評估狀態為「失敗」的樣本數。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">品質門檻</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">標籤治理規則</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">樣本取樣策略</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout dataset-grid">
        <section class="card">
          <h3>訓練樣本來源</h3>
          <p class="muted">
            只涵蓋已讀取到的研究版本。
            <template v-if="truncated">後端仍有未讀取頁面，統計範圍以此為限。</template>
          </p>
          <p v-if="visible.length === 0" class="muted">目前沒有符合條件的訓練資料集。</p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 版本</th>
                <th>狀態</th>
                <th>樣本（宣告 / 已評估）</th>
                <th>標籤政策</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visible"
                :key="row.versionId"
                :class="{ active: row.versionId === selectedId }"
                @click="selectRow(row)"
              >
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId }}</div>
                </td>
                <td>
                  <span class="tag" :class="row.versionStatus === 'FAILED' ? 'bad' : row.versionStatus === 'READY' ? 'good' : ''">
                    {{ VERSION_STATUS_LABELS[row.versionStatus] }}
                  </span>
                </td>
                <td>{{ row.samples.declared }} / {{ row.samples.evaluated }}</td>
                <td class="mono cell-hash">{{ row.labelPolicyHash }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>資料集詳情</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆訓練資料集。</p>
          <template v-else>
            <div class="row compact">
              <span>研究</span>
              <span>{{ selectedRow.researchName }}</span>
            </div>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono record-value">{{ selectedRow.versionId }}</span>
            </div>
            <div class="row compact">
              <span>版本狀態</span>
              <span class="tag">{{ VERSION_STATUS_LABELS[selectedRow.versionStatus] }}</span>
            </div>
            <div class="row compact">
              <span>研究目的</span>
              <span class="tag">{{ selectedRow.purposeLabel }}</span>
            </div>

            <h3 style="margin-top: 18px;">樣本狀態</h3>
            <div class="row compact">
              <span>宣告樣本</span>
              <span>{{ selectedRow.samples.declared }}</span>
            </div>
            <div class="row compact">
              <span>已評估 / 評估中 / 失敗</span>
              <span>
                {{ selectedRow.samples.evaluated }} / {{ selectedRow.samples.running }} / {{ selectedRow.samples.failed }}
              </span>
            </div>
            <div class="row compact">
              <span>未取得評估</span>
              <span :class="selectedRow.samples.unknown > 0 ? 'bad' : ''">{{ selectedRow.samples.unknown }}</span>
            </div>

            <h3 style="margin-top: 18px;">標籤與品質</h3>
            <div class="row compact">
              <span>標籤政策指紋</span>
              <span class="mono record-value">{{ selectedRow.labelPolicyHash }}</span>
            </div>
            <div class="row compact">
              <span>計量版本</span>
              <span class="mono record-value">{{ selectedRow.metricVersion }}</span>
            </div>
            <div class="row compact">
              <span>品質報告產物</span>
              <span class="mono record-value">{{ selectedRow.qualityReportId ?? TRAINING_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>品質門檻</span>
              <span class="muted">{{ TRAINING_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                v-if="selectedRow.researchId !== null"
                :to="{ name: 'research-workbench', params: { id: selectedRow.researchId }, query: workbenchQuery }"
              >
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
          </template>
        </section>
      </div>

      <section class="card note-card">
        <h3>目前邊界</h3>
        <p>
          後端沒有訓練資料集、標籤治理或品質門檻端點，因此本頁只把研究版本宣告的凍結提交當成樣本來源，並以可讀的最終評估推導樣本狀態；品質門檻一律「未取得」，不以推測補值。
        </p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
}

.metric-card {
  min-height: 150px;
}

.metric-value {
  font-size: 28px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.unknown-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 16px;
}

.unknown-card {
  border-style: dashed;
}

.unknown-value {
  margin: 8px 0 0;
  color: #9fb3c8;
}

.dataset-grid {
  grid-template-columns: 1.35fr 1fr;
}

.detail-card {
  margin-top: 0;
}

.note-card {
  margin-top: 16px;
}

.compact {
  padding: 8px 0;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label {
  font-size: 11px;
  color: #7fa1ce;
}

tbody tr {
  cursor: pointer;
}

tbody tr.active td {
  background: #132842;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}

.cell-hash {
  max-width: 220px;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dataset-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: 1fr;
  }
}
</style>
