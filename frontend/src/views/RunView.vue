<script setup lang="ts">
/**
 * 任務詳情：顯示後端 Run 投影，並以有界批次續接事件直到終態。
 * 事件與狀態一律重新向後端查詢，畫面不自行推測任務結果。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { cancelRun, fetchRunEvents, getRun, isTerminal, type Run, type RunStatus } from '../api/runs'
import { resumeCursor, type RunEventEnvelope } from '../lib/events'
import { describeError } from '../lib/messages'
import { client } from '../lib/session'

const POLL_MS = 2000

const route = useRoute()
const runId = String(route.params.id ?? '')

const run = ref<Run | null>(null)
const events = ref<RunEventEnvelope[]>([])
const cursor = ref<string | null>(null)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const cancelling = ref(false)
const following = ref(false)

let timer: ReturnType<typeof setTimeout> | null = null
let stopped = true

const statusLabel: Record<RunStatus, string> = {
  QUEUED: '排隊中',
  RUNNING: '執行中',
  CANCEL_REQUESTED: '取消處理中',
  SUCCEEDED: '成功',
  FAILED: '失敗',
  CANCELLED: '已取消',
}

const artifacts = computed<{ id: string; label: string }[]>(() => {
  const current = run.value
  if (current === null) return []
  return [
    ...(current.diagnostic_artifact_ids ?? []).map((id) => ({ id, label: '診斷產物' })),
    ...(current.research_trace_artifact_ids ?? []).map((id) => ({ id, label: '研究軌跡產物' })),
  ]
})

const canCancel = computed<boolean>(() => {
  const current = run.value
  return current !== null && current.type === 'PROFILE' && !isTerminal(current.status)
})

function summarize(payload: Record<string, unknown>): string {
  const text = JSON.stringify(payload)
  return text.length > 200 ? `${text.slice(0, 200)}…` : text
}

function stopFollowing(): void {
  stopped = true
  following.value = false
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

async function tick(): Promise<void> {
  if (stopped) return
  try {
    const batch = await fetchRunEvents(client, runId, cursor.value)
    if (batch.length > 0) {
      events.value = [...events.value, ...batch]
      cursor.value = resumeCursor(runId, batch)
    }
    run.value = await getRun(client, runId)
  } catch (cause) {
    error.value = describeError(cause)
    stopFollowing()
    return
  }
  if (run.value !== null && isTerminal(run.value.status)) {
    stopFollowing()
    return
  }
  timer = setTimeout(() => {
    void tick()
  }, POLL_MS)
}

async function start(): Promise<void> {
  loading.value = true
  error.value = ''
  notice.value = ''
  cursor.value = null
  events.value = []
  stopped = false
  following.value = true
  await tick()
  loading.value = false
}

async function requestCancel(): Promise<void> {
  const current = run.value
  if (current === null || cancelling.value) return
  cancelling.value = true
  error.value = ''
  notice.value = ''
  try {
    run.value = await cancelRun(client, current)
    notice.value = '已送出取消請求；任務真正停止後才會轉為「已取消」。'
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    cancelling.value = false
  }
}

onMounted(() => {
  void start()
})
onUnmounted(stopFollowing)
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2>任務</h2>
      <button type="button" :disabled="loading" @click="start">重新載入</button>
    </div>
    <p class="mono id">{{ runId }}</p>

    <p v-if="loading && run === null" class="muted">載入中…</p>
    <template v-else-if="run === null">
      <p class="muted">尚無任務資料。</p>
    </template>
    <template v-else>
      <dl class="facts">
        <dt>類型</dt>
        <dd>{{ run.type }}</dd>
        <dt>狀態</dt>
        <dd>{{ statusLabel[run.status] }}（{{ run.status }}）</dd>
        <dt>控制版本</dt>
        <dd class="mono">{{ run.revision }}</dd>
        <dt>建立時間</dt>
        <dd class="mono">{{ run.created_at }}</dd>
        <dt>階段</dt>
        <dd>{{ run.phase ?? '未回報' }}</dd>
        <dt>停止原因</dt>
        <dd>{{ run.stop_reason ?? '未回報' }}</dd>
        <dt>結果判定</dt>
        <dd>{{ run.outcome_status ?? '未回報' }}</dd>
        <dt>資料集</dt>
        <dd class="mono">{{ run.dataset_id ?? '不適用' }}</dd>
      </dl>

      <h3>預算用量</h3>
      <p v-if="run.budget_usage === undefined" class="muted">後端未提供用量投影。</p>
      <dl v-else class="facts">
        <dt>CPU 秒</dt>
        <dd class="mono">{{ run.budget_usage.cpu_seconds }}</dd>
        <dt>GPU 秒</dt>
        <dd class="mono">{{ run.budget_usage.gpu_seconds }}</dd>
        <dt>Token</dt>
        <dd class="mono">{{ run.budget_usage.tokens }}</dd>
        <dt>候選（產生／接受）</dt>
        <dd class="mono">{{ run.budget_usage.candidates_generated }} ／ {{ run.budget_usage.candidates_accepted }}</dd>
      </dl>

      <h3>操作</h3>
      <p v-if="canCancel" class="muted">取消僅適用 PROFILE 任務；送出後仍需等待後端確認真正停止。</p>
      <button v-if="canCancel" type="button" :disabled="cancelling" @click="requestCancel">
        {{ cancelling ? '送出中…' : '取消任務' }}
      </button>
      <p v-else-if="run.type !== 'PROFILE'" class="muted">
        後端只對 PROFILE 任務提供取消，{{ run.type }} 任務不支援（會回 503）。
      </p>
      <p v-else class="muted">任務已進入終態，無法再取消。</p>

      <h3>產物</h3>
      <p v-if="artifacts.length === 0" class="muted">此任務未回報產物識別碼。</p>
      <ul v-else class="list">
        <li v-for="row in artifacts" :key="row.id">
          <RouterLink :to="{ name: 'artifact', params: { id: row.id } }">
            {{ row.label }}
          </RouterLink>
          <span class="mono id">{{ row.id }}</span>
        </li>
      </ul>

      <h3>事件</h3>
      <p class="muted" aria-live="polite">
        {{ following ? '正在追蹤事件（後端每批最多 100 筆）…' : '事件追蹤已停止。' }}
        <template v-if="events.length > 0">已收到 {{ events.length }} 筆。</template>
      </p>
      <p v-if="events.length === 0" class="muted">尚無事件。</p>
      <ol v-else class="timeline">
        <li v-for="event in events" :key="event.event_id">
          <span class="mono seq">#{{ event.sequence }}</span>
          <span class="type">{{ event.event_type }}</span>
          <span class="mono at">{{ event.occurred_at }}</span>
          <span class="mono detail">{{ summarize(event.payload) }}</span>
        </li>
      </ol>
    </template>
  </section>

  <p v-if="error" class="alert" role="alert">{{ error }}</p>
  <output v-if="notice" class="notice">{{ notice }}</output>
</template>

<style scoped>
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  padding: 1.25rem;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
h2 {
  margin: 0;
  font-size: 1.15rem;
}
h3 {
  margin: 1.25rem 0 0.5rem;
  font-size: 1rem;
}
.id {
  color: var(--text-muted);
  word-break: break-all;
}
.facts {
  display: grid;
  grid-template-columns: minmax(8rem, auto) 1fr;
  gap: 0.35rem 1rem;
  margin: 0.75rem 0 0;
}
.facts dt {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.facts dd {
  margin: 0;
  word-break: break-all;
}
.muted {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.list li {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.timeline li {
  display: grid;
  grid-template-columns: 4rem minmax(10rem, auto) minmax(12rem, auto) 1fr;
  gap: 0.75rem;
  align-items: baseline;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.4rem;
}
.seq {
  color: var(--accent);
}
.type {
  font-weight: 600;
}
.at,
.detail {
  color: var(--text-muted);
  font-size: 0.85rem;
  word-break: break-all;
}
.alert {
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--danger-surface);
  color: var(--danger);
}
.notice {
  display: block;
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--surface-muted);
}
@media (max-width: 48rem) {
  .timeline li {
    grid-template-columns: 1fr;
  }
}
</style>
