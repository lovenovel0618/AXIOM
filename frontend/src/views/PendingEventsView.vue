<script setup lang="ts">
/**
 * 待處理事件（SSOT SCREEN 03）：只把後端已回報的失敗／停止／歧義／待確認狀態列成佇列。
 *
 * 佇列項目全部由 `buildPendingQueue()` 推導，每條都附可追溯來源與下一步；
 * 人工決策（批准／駁回／要求補充證據）需要不可竄改稽核事件，後端尚未提供該 API，
 * 因此本頁不提供會改寫研究事實的按鈕，只導向可判讀的既有頁面。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { buildPendingQueue, type PendingItem, type PendingPriority } from '../lib/consoleCenter'
import { useConsoleCenter } from '../lib/useConsoleCenter'

const { snapshot, loading, error, load } = useConsoleCenter()

const filter = ref<'全部' | PendingPriority>('全部')
const PRIORITY_OPTIONS: ('全部' | PendingPriority)[] = ['全部', '高', '中', '低']

const queue = computed<PendingItem[]>(() => (snapshot.value === null ? [] : buildPendingQueue(snapshot.value)))
const visible = computed<PendingItem[]>(() =>
  filter.value === '全部' ? queue.value : queue.value.filter((item) => item.priority === filter.value),
)
const counts = computed(() => ({
  高: queue.value.filter((item) => item.priority === '高').length,
  中: queue.value.filter((item) => item.priority === '中').length,
  低: queue.value.filter((item) => item.priority === '低').length,
}))

function priorityClass(priority: PendingPriority): string {
  if (priority === '高') return 'bad'
  if (priority === '中') return 'warn'
  return 'muted'
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
        <div class="eyebrow">總覽 / SCREEN 03</div>
        <h1>待處理事件</h1>
        <p class="muted">審核、衝突、風險與待確認事項 · 只列後端已回報狀態，不代替使用者決策</p>
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
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">待處理總數</div>
          <div class="metric-value">{{ queue.length }}</div>
          <p>由任務狀態、停止理由與資料版本狀態推導而得。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">高優先</div>
          <div class="metric-value" :class="counts.高 > 0 ? 'bad' : 'neutral'">{{ counts.高 }}</div>
          <p>任務失敗或匯入失敗，需要人為判讀後再決定下一步。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">中 / 低優先</div>
          <div class="metric-value neutral">{{ counts.中 }} / {{ counts.低 }}</div>
          <p>停止中、預算耗盡、歧義或拒答、以及尚未建立後續任務的版本。</p>
        </section>
      </div>

      <section class="card">
        <div class="head-inline">
          <h3>待處理佇列</h3>
          <div class="actions">
            <button
              v-for="option in PRIORITY_OPTIONS"
              :key="option"
              type="button"
              :class="{ primary: filter === option }"
              @click="filter = option"
            >
              {{ option === '全部' ? '全部' : `${option}優先` }}
            </button>
          </div>
        </div>

        <p v-if="queue.length === 0" class="muted">目前沒有需要人為判讀的事件。</p>
        <p v-else-if="visible.length === 0" class="muted">此優先級目前沒有項目。</p>

        <table v-else>
          <thead>
            <tr>
              <th>優先級</th>
              <th>事件</th>
              <th>來源</th>
              <th>狀態</th>
              <th>判讀依據</th>
              <th>下一步</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in visible" :key="item.id">
              <td><b :class="priorityClass(item.priority)">{{ item.priority }}</b></td>
              <td>
                <b>{{ item.title }}</b>
                <div class="mono">{{ item.id }}</div>
              </td>
              <td>{{ item.source }}</td>
              <td><span class="tag">{{ item.status }}</span></td>
              <td>{{ item.reason }}</td>
              <td>
                <div>{{ item.action }}</div>
                <RouterLink v-if="item.to !== null" :to="item.to">
                  <button type="button">開啟</button>
                </RouterLink>
                <span v-else class="muted">此項目沒有可開啟的頁面。</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="card note-card">
        <h3>決策邊界</h3>
        <p>
          批准／駁回／要求補充證據需要不可竄改的稽核事件與權限檢查，後端尚未提供該 API；
          因此本頁不提供會改寫研究事實的按鈕，只把可追溯來源與下一步列出。
        </p>
        <div class="note">
          讀取邊界：本頁只彙整最近 {{ snapshot.researches.length }} 個研究容器與
          {{ snapshot.datasets.length }} 個資料集所讀到的任務與版本；未讀取的頁面不會被推估為待辦。
        </div>
        <p class="muted">最後讀取時間：{{ formatStamp(new Date().toISOString()) }}</p>
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

.neutral {
  color: #9fb4d0;
}

.head-inline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.head-inline h3 {
  margin: 0;
}

.note-card {
  margin-top: 16px;
}

.note-card .note {
  margin: 12px 0;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
