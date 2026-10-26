<script setup lang="ts">
/**
 * Token 與儲存（SSOT SCREEN 35）：事件保存、壓縮、留存及成本。
 *
 * Token 上限與累計用量取自已揭露的研究版本預算欄位；事件保存、壓縮政策與儲存配額沒有後端端點，
 * 一律標示「未取得」。本頁只做監控，不提供配額調整或事件刪除等未支援的寫入動作。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ModelTabs from '../components/ModelTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useModelCenter } from '../lib/useModelCenter'
import {
  MODEL_UNKNOWN,
  VERSION_STATUS_LABELS,
  buildStorageRows,
  filterStorageRows,
  summarizeStorage,
  type StorageRow,
} from '../lib/modelCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useModelCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const selectedId = ref(readQueryString(route.query, 'version'))

const rows = computed<StorageRow[]>(() => (center.value === null ? [] : buildStorageRows(center.value)))
const visible = computed(() => filterStorageRows(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeStorage(rows.value))
const selectedRow = computed<StorageRow | null>(() => rows.value.find((row) => row.versionId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedRow.value
  if (row === null || row.researchId === null) return null
  return withBackRef(route.fullPath, { version: row.versionId })
})

function numberText(value: number | null): string {
  return value === null ? MODEL_UNKNOWN : String(value)
}

function bytesText(value: number | null): string {
  if (value === null) return MODEL_UNKNOWN
  if (value < 1024) return `${String(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MiB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}

function secondsText(value: number): string {
  return `${String(value)} s`
}

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

function selectRow(row: StorageRow): void {
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
    <ModelTabs />

    <div class="head">
      <div>
        <div class="eyebrow">模型 / SCREEN 35</div>
        <h1>Token 與儲存</h1>
        <p class="muted">
          專屬任務畫面設計｜事件保存、壓縮、留存及成本：Token 上限與累計用量取自版本預算；留存、壓縮與儲存配額後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <label class="field">
          <span class="field-label">搜尋研究或版本</span>
          <input v-model="keyword" placeholder="研究名稱或版本識別碼" @keyup.enter="applySearch" />
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
          <div class="eyebrow">已讀取版本</div>
          <div class="metric-value">{{ summary.versions }}</div>
          <p>統計只涵蓋本頁實際讀取到的不變版本。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">Token 上限合計</div>
          <div class="metric-value">{{ summary.tokenLimit }}</div>
          <p>各版本宣告的預算上限加總，為後端已揭露欄位。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">Token 已用合計</div>
          <div class="metric-value">{{ summary.usedTokens }}</div>
          <p>版本研究預算的累計 Token 用量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">超過 Token 上限</div>
          <div class="metric-value" :class="summary.overTokenLimit > 0 ? 'warn' : 'good'">{{ summary.overTokenLimit }}</div>
          <p>累計用量超過宣告上限的版本數；未超過不代表後端已核准更多預算。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">事件保存與留存</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">壓縮政策</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">儲存配額（位元組）</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout storage-grid">
        <section class="card">
          <h3>版本 Token 與成本</h3>
          <p class="muted">只列出已讀取版本的已揭露欄位；未揭露的留存與配額不在此表。</p>
          <p v-if="visible.length === 0" class="muted">目前沒有符合條件的版本。</p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 版本</th>
                <th>狀態</th>
                <th>Token 上限</th>
                <th>已用 Token</th>
                <th>CPU</th>
                <th>GPU</th>
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
                <td>{{ VERSION_STATUS_LABELS[row.versionStatus] }}</td>
                <td>{{ row.tokenLimit }}</td>
                <td>
                  <span class="tag" :class="row.overTokenLimit ? 'warn' : ''">{{ row.usedTokens }}</span>
                </td>
                <td>{{ secondsText(row.usedCpuSeconds) }}</td>
                <td>{{ secondsText(row.usedGpuSeconds) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>選定版本用量</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一個研究版本。</p>
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
              <span>Token 上限 / 已用</span>
              <span>
                {{ selectedRow.tokenLimit }} / {{ selectedRow.usedTokens }}
                <span v-if="selectedRow.overTokenLimit" class="tag warn">已超過上限</span>
              </span>
            </div>
            <div class="row compact">
              <span>CPU / GPU 秒數</span>
              <span>{{ secondsText(selectedRow.usedCpuSeconds) }} / {{ secondsText(selectedRow.usedGpuSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>實際耗時</span>
              <span>{{ secondsText(selectedRow.usedWallSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>尖峰記憶體</span>
              <span>{{ bytesText(selectedRow.peakMemoryBytes) }}</span>
            </div>
            <div class="row compact">
              <span>生成 / 接受候選</span>
              <span>{{ selectedRow.candidatesGenerated }} / {{ selectedRow.candidatesAccepted }}</span>
            </div>
            <div class="row compact">
              <span>事件保存與留存</span>
              <span class="muted">{{ selectedRow.eventRetention }}</span>
            </div>
            <div class="row compact">
              <span>壓縮政策</span>
              <span class="muted">{{ selectedRow.compression }}</span>
            </div>
            <div class="row compact">
              <span>儲存配額</span>
              <span class="muted">{{ selectedRow.storageQuota }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <div class="actions" style="margin-top: 14px;">
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
          後端沒有事件保存、壓縮、留存或儲存配額端點，這三欄一律「未取得」；本頁只加總已揭露的 Token、CPU／GPU 秒數與尖峰記憶體，不以推測值補上儲存量。
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

.storage-grid {
  grid-template-columns: 1.4fr 1fr;
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

  .storage-grid {
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
