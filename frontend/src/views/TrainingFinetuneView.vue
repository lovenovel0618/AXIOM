<script setup lang="ts">
/**
 * 微調任務（SSOT SCREEN 37）：LoRA 任務、資源配額及訓練監控。
 *
 * 後端沒有微調或 LoRA 端點，本頁只把已讀取到的任務與其研究版本預算當成配額與監控
 * 來源；LoRA 目標、基底模型、檢查點與訓練曲線後端未揭露，一律標示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import TrainingTabs from '../components/TrainingTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useTrainingCenter } from '../lib/useTrainingCenter'
import {
  RUN_STATUS_LABELS,
  TRAINING_UNKNOWN,
  buildFinetuneRows,
  filterFinetuneRows,
  summarizeFinetune,
  type FinetuneRow,
} from '../lib/trainingCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useTrainingCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const selectedId = ref(readQueryString(route.query, 'run'))

const rows = computed<FinetuneRow[]>(() => (center.value === null ? [] : buildFinetuneRows(center.value)))
const visible = computed(() => filterFinetuneRows(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeFinetune(rows.value))
const selectedRow = computed<FinetuneRow | null>(() => rows.value.find((row) => row.runId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => center.value?.scope.truncated ?? false)
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedRow.value
  if (row === null || row.researchId === null) return null
  return withBackRef(route.fullPath, row.versionId === null ? {} : { version: row.versionId })
})

function numberText(value: number | null): string {
  return value === null ? TRAINING_UNKNOWN : String(value)
}

function secondsText(value: number | null): string {
  return value === null ? TRAINING_UNKNOWN : `${String(value)} s`
}

function ratioText(used: number | null, quota: number | null): string {
  if (used === null && quota === null) return TRAINING_UNKNOWN
  return `${used === null ? TRAINING_UNKNOWN : String(used)} / ${quota === null ? TRAINING_UNKNOWN : String(quota)}`
}

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

function selectRow(row: FinetuneRow): void {
  selectedId.value = row.runId
}

onMounted(async () => {
  await load()
  if (selectedId.value === '' && rows.value.length > 0) selectedId.value = rows.value[0]?.runId ?? ''
})

watch(selectedId, async (value) => {
  await replaceQueryState(router, route, { run: value === '' ? undefined : value })
})

watch(
  () => route.query.run,
  () => {
    selectedId.value = readQueryString(route.query, 'run')
  },
)

watch(visible, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.runId === selectedId.value)) return
  selectedId.value = value[0]?.runId ?? ''
})
</script>

<template>
  <section>
    <TrainingTabs />

    <div class="head">
      <div>
        <div class="eyebrow">訓練 / 第 37 頁</div>
        <h1>微調任務</h1>
        <p class="muted">
          專屬任務畫面設計｜LoRA 任務、資源配額及訓練監控：配額取研究版本預算、用量取任務預算用量；LoRA 目標、基底模型與檢查點後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <label class="field">
          <span class="field-label">搜尋微調任務</span>
          <input v-model="keyword" placeholder="研究名稱、任務 ID 或任務類別" @keyup.enter="applySearch" />
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
          <div class="eyebrow">任務數</div>
          <div class="metric-value">{{ summary.tasks }}</div>
          <p>本頁實際讀取的任務總數；後端沒有微調端點，這一欄以既有任務代表受監控對象。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">進行中</div>
          <div class="metric-value" :class="summary.active > 0 ? 'good' : ''">{{ summary.active }}</div>
          <p>尚未進入終止狀態的任務數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">失敗</div>
          <div class="metric-value" :class="summary.failed > 0 ? 'bad' : ''">{{ summary.failed }}</div>
          <p>狀態為「失敗」的任務數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">GPU 配額合計</div>
          <div class="metric-value">{{ secondsText(summary.quotaGpuSeconds) }}</div>
          <p>所屬研究版本宣告的 GPU 秒數上限合計；版本未取得時不計入。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">LoRA 目標與秩</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">基底模型與版本</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">檢查點與訓練曲線</div>
          <p class="unknown-value">{{ TRAINING_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout finetune-grid">
        <section class="card">
          <h3>訓練監控對象</h3>
          <p class="muted">
            只涵蓋已讀取到的研究版本任務。
            <template v-if="truncated">後端仍有未讀取頁面，統計範圍以此為限。</template>
          </p>
          <p v-if="visible.length === 0" class="muted">目前沒有符合條件的微調任務。</p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 任務</th>
                <th>任務類別</th>
                <th>狀態</th>
                <th>GPU 配額</th>
                <th>Token 上限</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visible"
                :key="row.runId"
                :class="{ active: row.runId === selectedId }"
                @click="selectRow(row)"
              >
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.runId }}</div>
                </td>
                <td>{{ row.taskLabel }}</td>
                <td>
                  <span class="tag" :class="row.status === 'FAILED' ? 'bad' : row.status === 'SUCCEEDED' ? 'good' : ''">
                    {{ RUN_STATUS_LABELS[row.status] }}
                  </span>
                </td>
                <td>{{ secondsText(row.quotaGpuSeconds) }}</td>
                <td>{{ numberText(row.quotaTokens) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>任務詳情</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆微調任務。</p>
          <template v-else>
            <div class="row compact">
              <span>研究</span>
              <span>{{ selectedRow.researchName }}</span>
            </div>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono record-value">{{ selectedRow.versionId ?? TRAINING_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>任務類別</span>
              <span class="tag">{{ selectedRow.taskLabel }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag">{{ RUN_STATUS_LABELS[selectedRow.status] }}</span>
            </div>

            <h3 style="margin-top: 18px;">資源配額與用量（秒數）</h3>
            <div class="row compact">
              <span>CPU 用量 / 配額</span>
              <span>{{ ratioText(selectedRow.usedCpuSeconds, selectedRow.quotaCpuSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>GPU 用量 / 配額</span>
              <span>{{ ratioText(selectedRow.usedGpuSeconds, selectedRow.quotaGpuSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>Token 用量 / 上限</span>
              <span>{{ ratioText(selectedRow.usedTokens, selectedRow.quotaTokens) }}</span>
            </div>
            <div class="row compact">
              <span>牆鐘配額</span>
              <span>{{ secondsText(selectedRow.quotaWallSeconds) }}</span>
            </div>

            <h3 style="margin-top: 18px;">LoRA 設定</h3>
            <div class="row compact">
              <span>調適目標</span>
              <span class="muted">{{ selectedRow.adapterTarget }}</span>
            </div>
            <div class="row compact">
              <span>基底模型</span>
              <span class="muted">{{ selectedRow.baseModel }}</span>
            </div>
            <div class="row compact">
              <span>檢查點</span>
              <span class="muted">{{ selectedRow.checkpoint }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink :to="{ name: 'run', params: { id: selectedRow.runId } }">
                <button type="button">開啟任務詳情</button>
              </RouterLink>
              <RouterLink
                v-if="workbenchQuery !== null && selectedRow.researchId !== null"
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
          後端沒有微調、LoRA 或訓練監控端點，因此本頁只呈現既有任務與其研究版本預算可推導的配額與用量；LoRA 目標、基底模型、檢查點與訓練曲線一律「未取得」。
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

.finetune-grid {
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

  .finetune-grid {
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
