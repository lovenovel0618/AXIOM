<script setup lang="ts">
/**
 * 資源監控（SSOT SCREEN 04）：只呈現後端已揭露的用量與研究版本帳本。
 *
 * 後端沒有即時 CPU／GPU／RAM 觀測端點，即時區塊固定回報「未取得」，
 * 不以推測數值填補；資料集匯入任務的投影不含預算欄位，因此不列入用量彙總。
 */
import { computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { buildResourceSummary, latestDatasetVersionOf, UNKNOWN, type ResourceSummary } from '../lib/consoleCenter'
import { useConsoleCenter } from '../lib/useConsoleCenter'

const { snapshot, loading, error, load } = useConsoleCenter()

interface StorageRow {
  datasetId: string
  name: string
  versionId: string | null
  rowCount: number | null
  status: string | null
}

const storageRows = computed<StorageRow[]>(() => {
  const current = snapshot.value
  if (current === null) return []
  return current.datasets.map((dataset) => {
    const version = latestDatasetVersionOf(current, dataset.id)
    return {
      datasetId: dataset.id,
      name: dataset.name,
      versionId: version === null ? null : version.id,
      rowCount: version === null ? null : version.row_count,
      status: version === null ? null : version.status,
    }
  })
})

const EMPTY: ResourceSummary = {
  totals: {
    runs: 0,
    disclosing: 0,
    cpuSeconds: null,
    gpuSeconds: null,
    tokens: null,
    wallSeconds: null,
    peakMemoryBytes: null,
    candidatesGenerated: null,
    candidatesAccepted: null,
  },
  rows: [],
  budgets: [],
  instantaneous: [
    { label: 'CPU', value: UNKNOWN },
    { label: 'GPU', value: UNKNOWN },
    { label: 'RAM', value: UNKNOWN },
  ],
  note: '',
}

const summary = computed<ResourceSummary>(() =>
  snapshot.value === null ? EMPTY : buildResourceSummary(snapshot.value),
)

function formatNumber(value: number | null): string {
  if (value === null) return UNKNOWN
  return value.toLocaleString('zh-TW', { maximumFractionDigits: 3 })
}

function formatSeconds(value: number | null): string {
  if (value === null) return UNKNOWN
  if (value < 60) return `${ValueFixed(value)} 秒`
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value - minutes * 60)
  return `${String(minutes)} 分 ${String(seconds)} 秒`
}

function ValueFixed(value: number): string {
  return value.toLocaleString('zh-TW', { maximumFractionDigits: 2 })
}

function formatBytes(value: number | null): string {
  if (value === null) return UNKNOWN
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toLocaleString('zh-TW', { maximumFractionDigits: 2 })} ${units[unit] ?? 'B'}`
}

function ratio(used: number, limit: number): string {
  if (limit <= 0) return '0%'
  return `${String(Math.min(100, Math.round((used / limit) * 100)))}%`
}

function ratioClass(used: number, limit: number): string {
  if (limit <= 0) return ''
  const value = used / limit
  if (value >= 1) return 'bad'
  if (value >= 0.8) return 'warn'
  return ''
}

function formatStamp(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-TW', { hour12: false })
}

onMounted(load)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">總覽 / 第 4 頁</div>
        <h1>資源監控</h1>
        <p class="muted">CPU／GPU、記憶體、儲存與任務容量 · 僅呈現後端已揭露的觀測與帳本</p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'overview' }"><button type="button">返回總覽</button></RouterLink>
        <RouterLink :to="{ name: 'activity' }"><button type="button">活動中心</button></RouterLink>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && snapshot === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="snapshot !== null">
      <div class="layout cols3 instantaneous">
        <section v-for="cell in summary.instantaneous" :key="cell.label" class="card metric-card">
          <div class="eyebrow">{{ cell.label }} 即時使用率</div>
          <div class="metric-value unknown">{{ cell.value }}</div>
          <p>後端沒有即時硬體觀測端點，因此不提供數值推測。</p>
        </section>
      </div>

      <div class="layout cols2">
        <section class="card">
          <h3>用量彙總（已揭露欄位）</h3>
          <div class="totals">
            <div class="total-cell">
              <div class="eyebrow">讀取任務數</div>
              <div class="total-value">{{ summary.totals.runs }}</div>
              <div class="muted">其中 {{ summary.totals.disclosing }} 筆揭露預算用量</div>
            </div>
            <div class="total-cell">
              <div class="eyebrow">CPU 秒數</div>
              <div class="total-value">{{ formatSeconds(summary.totals.cpuSeconds) }}</div>
              <div class="muted">僅加總已揭露值</div>
            </div>
            <div class="total-cell">
              <div class="eyebrow">GPU 秒數</div>
              <div class="total-value">{{ formatSeconds(summary.totals.gpuSeconds) }}</div>
              <div class="muted">僅加總已揭露值</div>
            </div>
            <div class="total-cell">
              <div class="eyebrow">Token</div>
              <div class="total-value">{{ formatNumber(summary.totals.tokens) }}</div>
              <div class="muted">僅加總已揭露值</div>
            </div>
            <div class="total-cell">
              <div class="eyebrow">累計牆鐘時間</div>
              <div class="total-value">{{ formatSeconds(summary.totals.wallSeconds) }}</div>
              <div class="muted">僅加總已揭露值</div>
            </div>
            <div class="total-cell">
              <div class="eyebrow">峰值記憶體合計</div>
              <div class="total-value">{{ formatBytes(summary.totals.peakMemoryBytes) }}</div>
              <div class="muted">各任務峰值相加，非同時佔用</div>
            </div>
            <div class="total-cell">
              <div class="eyebrow">候選產生 / 接受</div>
              <div class="total-value">
                {{ formatNumber(summary.totals.candidatesGenerated) }} /
                {{ formatNumber(summary.totals.candidatesAccepted) }}
              </div>
              <div class="muted">僅加總已揭露值</div>
            </div>
          </div>
          <div class="note">{{ summary.note }}</div>
        </section>

        <section class="card">
          <h3>儲存與容量</h3>
          <p>
            資料集版本由後端回報列數與 SHA-256，本頁不做容量推估。
          </p>
          <table>
            <thead>
              <tr><th>資料集</th><th>最新版本</th><th>列數</th><th>狀態</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in storageRows" :key="row.datasetId">
                <td>
                  <RouterLink :to="{ name: 'data-preview', params: { id: row.datasetId } }">{{ row.name }}</RouterLink>
                  <div class="mono">{{ row.datasetId }}</div>
                </td>
                <td class="mono">{{ row.versionId ?? UNKNOWN }}</td>
                <td>{{ formatNumber(row.rowCount) }}</td>
                <td><span class="tag">{{ row.status ?? UNKNOWN }}</span></td>
              </tr>
              <tr v-if="storageRows.length === 0">
                <td colspan="4" class="muted">目前沒有可讀取的資料集。</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section class="card section-card">
        <h3>任務用量明細</h3>
        <p v-if="summary.rows.length === 0" class="muted">
          目前讀到的任務都沒有揭露預算用量欄位，因此不提供數值。
        </p>
        <table v-else>
          <thead>
            <tr>
              <th>任務</th>
              <th>型別 / 狀態</th>
              <th>建立時間</th>
              <th>CPU</th>
              <th>GPU</th>
              <th>Token</th>
              <th>牆鐘</th>
              <th>峰值記憶體</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in summary.rows" :key="row.runId">
              <td>
                <RouterLink :to="{ name: 'run', params: { id: row.runId } }">
                  <span class="mono">{{ row.runId }}</span>
                </RouterLink>
              </td>
              <td>{{ row.type }} / {{ row.status }}</td>
              <td>{{ formatStamp(row.created_at) }}</td>
              <td>{{ formatSeconds(row.cpuSeconds) }}</td>
              <td>{{ formatSeconds(row.gpuSeconds) }}</td>
              <td>{{ formatNumber(row.tokens) }}</td>
              <td>{{ formatSeconds(row.wallSeconds) }}</td>
              <td>{{ formatBytes(row.peakMemoryBytes) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="card section-card">
        <h3>研究版本預算帳本</h3>
        <p v-if="summary.budgets.length === 0" class="muted">目前沒有可讀取的研究版本。</p>
        <table v-else>
          <thead>
            <tr>
              <th>研究版本</th>
              <th>狀態</th>
              <th>CPU 用量 / 上限</th>
              <th>牆鐘 用量 / 上限</th>
              <th>Token 用量 / 上限</th>
              <th>候選 用量 / 上限</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="budget in summary.budgets" :key="budget.researchVersionId">
              <td>
                <RouterLink :to="{ name: 'research-workbench', params: { id: budget.researchId } }">
                  <span class="mono">{{ budget.researchVersionId }}</span>
                </RouterLink>
                <div class="muted">研究 {{ budget.researchId }}</div>
              </td>
              <td><span class="tag">{{ budget.status }}</span></td>
              <td>
                <div class="budget-line">
                  {{ formatSeconds(budget.cpuUsed) }} / {{ formatSeconds(budget.cpuLimit) }}
                </div>
                <span class="meter">
                  <i :class="ratioClass(budget.cpuUsed, budget.cpuLimit)" :style="{ width: ratio(budget.cpuUsed, budget.cpuLimit) }" />
                </span>
              </td>
              <td>
                <div class="budget-line">
                  {{ formatSeconds(budget.wallUsed) }} / {{ formatSeconds(budget.wallLimit) }}
                </div>
                <span class="meter">
                  <i :class="ratioClass(budget.wallUsed, budget.wallLimit)" :style="{ width: ratio(budget.wallUsed, budget.wallLimit) }" />
                </span>
              </td>
              <td>
                <div class="budget-line">
                  {{ formatNumber(budget.tokensUsed) }} / {{ formatNumber(budget.tokensLimit) }}
                </div>
                <span class="meter">
                  <i :class="ratioClass(budget.tokensUsed, budget.tokensLimit)" :style="{ width: ratio(budget.tokensUsed, budget.tokensLimit) }" />
                </span>
              </td>
              <td>
                <div class="budget-line">
                  {{ formatNumber(budget.candidatesUsed) }} / {{ formatNumber(budget.candidatesLimit) }}
                </div>
                <span class="meter">
                  <i :class="ratioClass(budget.candidatesUsed, budget.candidatesLimit)" :style="{ width: ratio(budget.candidatesUsed, budget.candidatesLimit) }" />
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </section>
</template>

<style scoped>
.instantaneous {
  margin-bottom: 16px;
}

.metric-card {
  min-height: 148px;
}

.metric-value {
  font-size: 30px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.metric-value.unknown {
  color: #8ca2c0;
}

.section-card {
  margin-top: 16px;
}

.totals {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.total-cell {
  border: 1px solid #24384f;
  border-radius: 10px;
  padding: 12px 14px;
  background: #0e1c2f;
}

.total-value {
  font-size: 20px;
  font-weight: 700;
  margin: 6px 0 4px;
}

.budget-line {
  font-size: 12px;
  color: #c0d4ef;
}

.meter {
  display: block;
  height: 6px;
  margin-top: 6px;
  background: #20354f;
  border-radius: 6px;
  overflow: hidden;
}

.meter i {
  display: block;
  height: 100%;
  background: #3389ef;
}

.meter i.warn {
  background: #efbd67;
}

.meter i.bad {
  background: #ff8496;
}

@media (max-width: 1200px) {
  .cols2,
  .cols3 {
    grid-template-columns: 1fr;
  }

  .totals {
    grid-template-columns: 1fr;
  }
}
</style>
