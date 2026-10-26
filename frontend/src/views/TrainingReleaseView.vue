<script setup lang="ts">
/**
 * 模型版本發布（SSOT SCREEN 38）：版本、發布渠道與回滾。
 *
 * 後端沒有模型發布、渠道或回滾端點，本頁只呈現研究版本本身的就緒度（版本狀態、
 * 評估政策指紋、凍結提交與已評估數）；模型名稱、模型版本、發布渠道、發布時間與
 * 回滾目標一律標示「未取得」。
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
  buildReleaseRows,
  filterReleaseRows,
  summarizeReleases,
  type ReleaseRow,
} from '../lib/trainingCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useTrainingCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const selectedId = ref(readQueryString(route.query, 'version'))

const rows = computed<ReleaseRow[]>(() => (center.value === null ? [] : buildReleaseRows(center.value)))
const visible = computed(() => filterReleaseRows(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeReleases(rows.value))
const selectedRow = computed<ReleaseRow | null>(() => rows.value.find((row) => row.versionId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => center.value?.scope.truncated ?? false)
const workbenchQuery = computed<Record<string, string>>(() =>
  withBackRef(route.fullPath, { version: selectedRow.value?.versionId }),
)

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

function selectRow(row: ReleaseRow): void {
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
        <div class="eyebrow">訓練 / 第 38 頁</div>
        <h1>模型版本發布</h1>
        <p class="muted">
          專屬任務畫面設計｜版本、發布渠道與回滾：只呈現研究版本本身的就緒度；發布渠道、發布時間與回滾目標後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <label class="field">
          <span class="field-label">搜尋發布候選</span>
          <input v-model="keyword" placeholder="研究名稱、版本 ID 或政策指紋" @keyup.enter="applySearch" />
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
          <div class="eyebrow">發布候選版本</div>
          <div class="metric-value">{{ summary.versions }}</div>
          <p>已就緒或已宣告凍結提交的研究版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已就緒</div>
          <div class="metric-value" :class="summary.ready > 0 ? 'good' : ''">{{ summary.ready }}</div>
          <p>版本狀態為「就緒」的候選數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">凍結提交</div>
          <div class="metric-value">{{ summary.submissions }}</div>
          <p>候選版本宣告的凍結提交總數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已評估提交</div>
          <div class="metric-value" :class="summary.evaluated > 0 ? 'good' : 'warn'">{{ summary.evaluated }}</div>
          <p>最終評估狀態為「已評估」的提交數；讀不到的提交不計入。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">模型名稱與版本</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">發布渠道與時間</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">回滾目標版本</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout release-grid">
        <section class="card">
          <h3>發布候選清單</h3>
          <p class="muted">
            只涵蓋已讀取到的研究版本。
            <template v-if="truncated">後端仍有未讀取頁面，統計範圍以此為限。</template>
          </p>
          <p v-if="visible.length === 0" class="muted">目前沒有符合條件的發布候選。</p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 版本</th>
                <th>狀態</th>
                <th>修訂</th>
                <th>提交（宣告 / 已評估）</th>
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
                <td>{{ row.revision }}</td>
                <td>{{ row.declaredSubmissions }} / {{ row.evaluatedSubmissions }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>候選詳情</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆發布候選。</p>
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
              <span>修訂</span>
              <span>{{ selectedRow.revision }}</span>
            </div>
            <div class="row compact">
              <span>評估政策指紋</span>
              <span class="mono record-value">{{ selectedRow.policyHash }}</span>
            </div>
            <div class="row compact">
              <span>凍結提交 / 已評估</span>
              <span>{{ selectedRow.declaredSubmissions }} / {{ selectedRow.evaluatedSubmissions }}</span>
            </div>

            <h3 style="margin-top: 18px;">發布資訊</h3>
            <div class="row compact">
              <span>模型名稱</span>
              <span class="muted">{{ selectedRow.modelName }}</span>
            </div>
            <div class="row compact">
              <span>模型版本</span>
              <span class="muted">{{ selectedRow.modelVersion }}</span>
            </div>
            <div class="row compact">
              <span>發布渠道</span>
              <span class="muted">{{ selectedRow.releaseChannel }}</span>
            </div>
            <div class="row compact">
              <span>發布時間</span>
              <span class="muted">{{ selectedRow.releasedAt }}</span>
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
          後端沒有模型發布、發布渠道或回滾端點，因此本頁只呈現研究版本本身可推導的就緒度（版本狀態、評估政策指紋、凍結提交與已評估數）；模型名稱、模型版本、發布渠道、發布時間與回滾目標一律「未取得」。
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

.release-grid {
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

@media (max-width: 1200px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .release-grid {
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
