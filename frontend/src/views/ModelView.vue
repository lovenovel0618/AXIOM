<script setup lang="ts">
/**
 * Ollama 模型管理（SSOT SCREEN 32）：模型載入、上下文、版本與資源。
 *
 * 後端沒有模型 registry 端點，模型名稱、上下文長度與模型版本一律標示「未取得」；本頁唯一能由
 * 契約推導的是任務與版本的預算用量（CPU／GPU 秒數、Token、尖峰記憶體、耗時），因此把「資源」
 * 當成主要工作區，不以推測值補上模型身分。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ModelTabs from '../components/ModelTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useModelCenter } from '../lib/useModelCenter'
import {
  MODEL_UNKNOWN,
  RUN_STATUS_LABELS,
  buildModelLoads,
  filterModelLoads,
  summarizeModelResources,
  type ModelLoadRow,
} from '../lib/modelCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useModelCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const selectedId = ref(readQueryString(route.query, 'run'))

const rows = computed<ModelLoadRow[]>(() => (center.value === null ? [] : buildModelLoads(center.value)))
const visible = computed(() => filterModelLoads(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeModelResources(rows.value))
const selectedRow = computed<ModelLoadRow | null>(() => rows.value.find((row) => row.runId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => center.value?.scope.truncated ?? false)
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedRow.value
  if (row === null || row.researchId === null) return null
  return withBackRef(route.fullPath, row.versionId === null ? {} : { version: row.versionId })
})

function numberText(value: number | null): string {
  return value === null ? MODEL_UNKNOWN : String(value)
}

function secondsText(value: number | null): string {
  return value === null ? MODEL_UNKNOWN : `${String(value)} s`
}

function bytesText(value: number | null): string {
  if (value === null) return MODEL_UNKNOWN
  if (value < 1024) return `${String(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MiB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

function selectRow(row: ModelLoadRow): void {
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
    <ModelTabs />

    <div class="head">
      <div>
        <div class="eyebrow">模型 / 第 32 頁</div>
        <h1>模型管理</h1>
        <p class="muted">
          專屬任務畫面設計｜模型載入、上下文、版本與資源：資源用量取自已揭露的任務與版本預算；模型名稱、上下文長度與模型版本後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <label class="field">
          <span class="field-label">搜尋模型工作負載</span>
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
          <div class="eyebrow">模型載入對象（任務）</div>
          <div class="metric-value">{{ summary.total }}</div>
          <p>本頁實際讀取到的任務數；後端沒有模型 registry，這一欄以任務代表載入對象。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已揭露資源用量</div>
          <div class="metric-value" :class="summary.disclosed > 0 ? 'good' : 'warn'">{{ summary.disclosed }}</div>
          <p>任務帶有預算用量的筆數；未揭露的任務不計入任何加總，也不以 0 代替。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">GPU 秒數合計</div>
          <div class="metric-value">{{ secondsText(summary.gpuSeconds) }}</div>
          <p>只加總已揭露的 GPU 秒數；全部未揭露時顯示「未取得」。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">Token 合計</div>
          <div class="metric-value">{{ numberText(summary.tokens) }}</div>
          <p>模型呼叫的 Token 用量；後端未揭露時顯示「未取得」，不以 0 補值。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">模型名稱與標籤</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">上下文長度</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">模型版本與量化</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout load-grid">
        <section class="card">
          <h3>模型載入對象</h3>
          <p class="muted">
            只涵蓋已讀取到的研究版本任務。
            <template v-if="truncated">後端仍有未讀取頁面，統計範圍以此為限。</template>
          </p>
          <p v-if="visible.length === 0" class="muted">目前沒有符合條件的模型工作負載。</p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 任務</th>
                <th>任務類別</th>
                <th>狀態</th>
                <th>CPU</th>
                <th>GPU</th>
                <th>Token</th>
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
                <td>{{ secondsText(row.resource.cpuSeconds) }}</td>
                <td>{{ secondsText(row.resource.gpuSeconds) }}</td>
                <td>{{ numberText(row.resource.tokens) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>載入對象詳情</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆模型載入對象。</p>
          <template v-else>
            <div class="row compact">
              <span>研究</span>
              <span>{{ selectedRow.researchName }}</span>
            </div>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono record-value">{{ selectedRow.versionId ?? MODEL_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>任務類別</span>
              <span class="tag">{{ selectedRow.taskLabel }}</span>
            </div>
            <div class="row compact">
              <span>任務狀態</span>
              <span class="tag">{{ RUN_STATUS_LABELS[selectedRow.status] }}</span>
            </div>
            <div class="row compact">
              <span>模型名稱</span>
              <span class="muted">{{ selectedRow.modelName }}</span>
            </div>
            <div class="row compact">
              <span>上下文長度</span>
              <span class="muted">{{ selectedRow.contextWindow }}</span>
            </div>
            <div class="row compact">
              <span>模型版本</span>
              <span class="muted">{{ selectedRow.modelVersion }}</span>
            </div>

            <h3 style="margin-top: 18px;">資源用量</h3>
            <div class="row compact">
              <span>CPU / GPU 秒數</span>
              <span>{{ secondsText(selectedRow.resource.cpuSeconds) }} / {{ secondsText(selectedRow.resource.gpuSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>Token</span>
              <span>{{ numberText(selectedRow.resource.tokens) }}</span>
            </div>
            <div class="row compact">
              <span>尖峰記憶體</span>
              <span>{{ bytesText(selectedRow.resource.peakMemoryBytes) }}</span>
            </div>
            <div class="row compact">
              <span>實際耗時</span>
              <span>{{ secondsText(selectedRow.resource.elapsedWallSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>生成 / 接受候選</span>
              <span>{{ numberText(selectedRow.resource.candidatesGenerated) }} / {{ numberText(selectedRow.resource.candidatesAccepted) }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink :to="{ name: 'run', params: { id: selectedRow.runId } }">
                <button type="button">開啟任務詳情</button>
              </RouterLink>
              <RouterLink v-if="workbenchQuery !== null && selectedRow.researchId !== null" :to="{ name: 'research-workbench', params: { id: selectedRow.researchId }, query: workbenchQuery }">
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
          </template>
        </section>
      </div>

      <section class="card note-card">
        <h3>目前邊界</h3>
        <p>
          後端沒有 Ollama 模型清單、模型註冊、上下文長度或模型版本端點，因此模型身分一律「未取得」；本頁只呈現任務與版本預算用量可推導的資源面。
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

.load-grid {
  grid-template-columns: 1.3fr 1fr;
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

  .load-grid {
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
