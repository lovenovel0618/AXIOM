<script setup lang="ts">
/**
 * 研究活動中心（SSOT SCREEN 02）：以實際讀到的任務投影排出跨專案事件時間軸。
 *
 * 後端沒有全域事件端點，因此時間軸來自「研究版本任務 + 資料集匯入任務」的實際讀取結果；
 * 事件分析只統計這批任務，不推估未讀取頁面的數量。
 */
import { computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import {
  buildActivityAnalysis,
  buildActivityTimeline,
  UNKNOWN,
  type ActivityBucket,
} from '../lib/consoleCenter'
import { useConsoleCenter } from '../lib/useConsoleCenter'

const { snapshot, loading, error, load } = useConsoleCenter()

const timeline = computed(() => (snapshot.value === null ? [] : buildActivityTimeline(snapshot.value, 20)))
const analysis = computed(() =>
  snapshot.value === null
    ? { total: 0, byType: [] as ActivityBucket[], byStatus: [] as ActivityBucket[], active: 0 }
    : buildActivityAnalysis(snapshot.value),
)

function barWidth(count: number, buckets: ActivityBucket[]): string {
  const max = buckets.reduce((peak, bucket) => Math.max(peak, bucket.count), 0)
  if (max === 0) return '0%'
  return `${String(Math.round((count / max) * 100))}%`
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
        <div class="eyebrow">總覽 / 第 2 頁</div>
        <h1>研究活動中心</h1>
        <p class="muted">跨專案研究事件與決策追蹤 · 僅呈現前台已授權讀取的任務投影</p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'overview' }"><button type="button">返回總覽</button></RouterLink>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && snapshot === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="snapshot !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">已讀取任務</div>
          <div class="metric-value">{{ analysis.total }}</div>
          <p>研究版本任務與資料集匯入任務的實際讀取筆數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">進行中</div>
          <div class="metric-value" :class="analysis.active > 0 ? 'good' : 'neutral'">
            {{ analysis.active }}
          </div>
          <p>狀態為 queued／running／cancel_requested 的任務數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">服務狀態</div>
          <div class="metric-value" :class="snapshot.readiness === 'ready' ? 'good' : 'bad'">
            {{ snapshot.readiness === 'ready' ? '已就緒' : '異常' }}
          </div>
          <p>依 `/health/ready/` 即時回報。</p>
        </section>
      </div>

      <div class="layout cols2">
        <section class="card">
          <h3>活動時間軸</h3>
          <p v-if="timeline.length === 0" class="muted">目前沒有可顯示的任務事件。</p>
          <div v-else class="timeline">
            <div v-for="entry in timeline" :key="entry.badge" class="timeline-row">
              <div class="timeline-main">
                <b>{{ formatStamp(entry.at) }} · {{ entry.title }}</b>
                <div class="muted">{{ entry.detail }}</div>
                <div class="mono">{{ entry.badge }}</div>
              </div>
              <div class="timeline-side">
                <span class="tag">{{ entry.status }}</span>
                <RouterLink :to="entry.to"><button type="button">查看任務</button></RouterLink>
              </div>
            </div>
          </div>
        </section>

        <section class="card">
          <h3>事件分析</h3>
          <p v-if="analysis.total === 0" class="muted">目前沒有可統計的任務。</p>
          <template v-else>
            <div class="group-label">依任務型別</div>
            <div v-for="bucket in analysis.byType" :key="`type:${bucket.key}`" class="bar-row">
              <b>{{ bucket.key }}</b>
              <span class="bar-track"><i :style="{ width: barWidth(bucket.count, analysis.byType) }" /></span>
              <em>{{ bucket.count }}</em>
            </div>

            <div class="group-label">依狀態</div>
            <div v-for="bucket in analysis.byStatus" :key="`status:${bucket.key}`" class="bar-row">
              <b>{{ bucket.key }}</b>
              <span class="bar-track"><i :style="{ width: barWidth(bucket.count, analysis.byStatus) }" /></span>
              <em>{{ bucket.count }}</em>
            </div>

            <div class="note">
              上方長條為圖表的文字替代，數值直接取自下方資料表；後端沒有全域事件端點，
              未讀取的頁面不會被計入統計。
            </div>

            <table>
              <thead>
                <tr><th>分類</th><th>鍵</th><th>任務數</th></tr>
              </thead>
              <tbody>
                <tr v-for="bucket in analysis.byType" :key="`tbl-type:${bucket.key}`">
                  <td>型別</td>
                  <td class="mono">{{ bucket.key }}</td>
                  <td>{{ bucket.count }}</td>
                </tr>
                <tr v-for="bucket in analysis.byStatus" :key="`tbl-status:${bucket.key}`">
                  <td>狀態</td>
                  <td class="mono">{{ bucket.key }}</td>
                  <td>{{ bucket.count }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </section>
      </div>

      <section class="card note-card">
        <h3>讀取邊界</h3>
        <p>
          本頁只彙整最近 {{ snapshot.researches.length }} 個研究容器與 {{ snapshot.datasets.length }} 個資料集所讀到的任務；
          後端沒有全域任務清單端點，未讀取的頁面不會被補值或推估。
        </p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
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

.timeline {
  display: flex;
  flex-direction: column;
}

.timeline-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 2px;
  border-bottom: 1px solid #25374e;
}

.timeline-row:last-child {
  border-bottom: 0;
}

.timeline-main {
  min-width: 0;
}

.timeline-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.group-label {
  font-size: 11px;
  letter-spacing: 2px;
  color: #54aaff;
  margin: 14px 0 6px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 7px 0;
}

.bar-row b {
  width: 96px;
  font-size: 12px;
  font-weight: 400;
}

.bar-track {
  flex: 1;
  height: 13px;
  background: #20354f;
  border-radius: 8px;
  overflow: hidden;
}

.bar-track i {
  display: block;
  height: 100%;
  background: #3389ef;
}

.bar-row em {
  font-style: normal;
  color: #8ba7ca;
  width: 34px;
  text-align: right;
}

.note-card {
  margin-top: 16px;
}

@media (max-width: 1200px) {
  .metric-grid,
  .cols2 {
    grid-template-columns: 1fr;
  }
}
</style>
