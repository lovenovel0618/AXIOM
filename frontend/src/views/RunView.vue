<script setup lang="ts">
/**
 * 任務詳情：顯示後端 Run 投影，並訂閱契約的事件串流直到終態。
 * 事件與狀態一律重新向後端查詢；連線中斷時顯示實際重連狀態而非凍結畫面。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { listRunCandidates, type Candidate, type ValidationStatus } from '../api/candidates'
import { getResearchVersion, type ResearchVersion } from '../api/research'
import { cancelRun, fetchRunEventBatch, getRun, isTerminal, type Run, type RunStatus } from '../api/runs'
import { readBackRef, withBackRef } from '../lib/navigationState'
import {
  EventFollower,
  FOLLOW_STATUS_LABELS,
  INITIAL_FOLLOW_STATE,
  type FollowState,
} from '../lib/stream'
import { describeError } from '../lib/messages'
import { client } from '../lib/session'

const route = useRoute()
const runId = String(route.params.id ?? '')
const backRef = readBackRef(route.query)

const run = ref<Run | null>(null)
const researchVersion = ref<ResearchVersion | null>(null)
const follow = ref<FollowState>(INITIAL_FOLLOW_STATE)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const cancelling = ref(false)

let follower: EventFollower | null = null

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
    ...(current.evidence_bundle_ids ?? []).map((id) => ({ id, label: '證據 Bundle' })),
  ]
})

const childRuns = computed(() => run.value?.child_run_ids ?? [])

/** SEARCH／FIT 任務才會產生候選分支，其餘型別不查詢候選分頁。 */
const CANDIDATE_PAGE_SIZE = 20
const candidates = ref<Candidate[]>([])
const candidateCursor = ref<string | null>(null)
const candidatesLoading = ref(false)
const candidatesError = ref('')

const statusLabels: Record<ValidationStatus, string> = {
  NOT_RUN: '尚未執行',
  PENDING: '進行中',
  FINISHED: '已完成',
  INVALID: '無效',
}

const showsCandidates = computed(() => {
  const current = run.value
  return current !== null && (current.type === 'SEARCH' || current.type === 'FIT')
})

const hasMoreCandidates = computed(() => candidateCursor.value !== null)

async function loadCandidates(reset: boolean): Promise<void> {
  const current = run.value
  if (current === null || candidatesLoading.value) return
  candidatesLoading.value = true
  candidatesError.value = ''
  try {
    const page = await listRunCandidates(client, current.id, {
      limit: CANDIDATE_PAGE_SIZE,
      cursor: reset ? null : candidateCursor.value,
    })
    candidates.value = reset ? page.items : [...candidates.value, ...page.items]
    candidateCursor.value = page.next_cursor
  } catch (cause) {
    candidatesError.value = describeError(cause)
  } finally {
    candidatesLoading.value = false
  }
}

const backQuery = computed<Record<string, string>>(() => withBackRef(route.fullPath))

const canCancel = computed<boolean>(() => {
  const current = run.value
  return current !== null && current.is_root !== false && ['PROFILE', 'SEARCH'].includes(current.type) && !isTerminal(current.status)
})

const events = computed(() => follow.value.events)

const followLabel = computed<string>(() => {
  const current = follow.value
  if (current.status === 'RECONNECTING') {
    return `${FOLLOW_STATUS_LABELS.RECONNECTING}（第 ${String(current.attempts)} 次，最後同步內容保留顯示）`
  }
  return FOLLOW_STATUS_LABELS[current.status]
})

function summarize(payload: Record<string, unknown>): string {
  const text = JSON.stringify(payload)
  return text.length > 200 ? `${text.slice(0, 200)}…` : text
}

async function syncRun(): Promise<void> {
  run.value = await getRun(client, runId)
  if (run.value.research_version_id === null) {
    researchVersion.value = null
    return
  }
  try {
    researchVersion.value = await getResearchVersion(client, run.value.research_version_id)
  } catch {
    researchVersion.value = null
  }
}

/** AX-21：游標過期時重新讀取權威 run 投影，取得目前序號後再續接。 */
async function snapshotCursor(): Promise<string | null> {
  const fresh = await getRun(client, runId)
  run.value = fresh
  return fresh.current_event_cursor
}

function stopFollowing(): void {
  follower?.stop()
  follower = null
}

async function start(): Promise<void> {
  stopFollowing()
  loading.value = true
  error.value = ''
  notice.value = ''
  follow.value = INITIAL_FOLLOW_STATE
  try {
    await syncRun()
  } catch (cause) {
    error.value = describeError(cause)
    loading.value = false
    return
  }
  loading.value = false
  if (showsCandidates.value) {
    candidates.value = []
    candidateCursor.value = null
    await loadCandidates(true)
  }
  follower = new EventFollower({
    scope: 'RUN',
    streamId: runId,
    fetchBatch: (cursor) => fetchRunEventBatch(client, runId, cursor),
    sync: syncRun,
    isTerminal: () => run.value !== null && isTerminal(run.value.status),
    snapshotCursor,
    onUpdate: (next) => {
      follow.value = next
    },
  })
  follower.start()
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
      <div class="actions">
        <RouterLink v-if="backRef !== ''" :to="backRef">
          <button type="button">返回來源頁</button>
        </RouterLink>
        <button type="button" :disabled="loading" @click="start">重新載入</button>
      </div>
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

      <h3>關聯上下文</h3>
      <dl class="facts">
        <dt>研究版本</dt>
        <dd>
          <RouterLink
            v-if="researchVersion !== null"
            :to="{
              name: 'research-workbench',
              params: { id: researchVersion.research_id },
              query: withBackRef(route.fullPath, { version: researchVersion.id }),
            }"
          >
            {{ researchVersion.id }}
          </RouterLink>
          <span v-else class="mono">{{ run.research_version_id ?? '不適用' }}</span>
        </dd>
        <dt>研究容器</dt>
        <dd>
          <RouterLink
            v-if="researchVersion !== null"
            :to="{ name: 'research-workbench', params: { id: researchVersion.research_id }, query: backQuery }"
          >
            {{ researchVersion.research_id }}
          </RouterLink>
          <span v-else class="muted">未取得</span>
        </dd>
        <dt>子任務數</dt>
        <dd class="mono">{{ childRuns.length }}</dd>
        <dt>略過階段</dt>
        <dd class="mono">{{ run.skipped_phases?.length ?? 0 }}</dd>
      </dl>

      <div v-if="childRuns.length !== 0" class="link-stack">
        <RouterLink
          v-for="id in childRuns"
          :key="id"
          :to="{ name: 'run', params: { id }, query: backQuery }"
          class="resource-link"
        >
          <span>子任務</span>
          <span class="mono">{{ id }}</span>
        </RouterLink>
      </div>

      <table v-if="(run.skipped_phases?.length ?? 0) !== 0" class="compact-table">
        <thead>
          <tr>
            <th>略過階段</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in run.skipped_phases" :key="`${row.phase}:${row.reason}`">
            <td>{{ row.phase }}</td>
            <td>{{ row.reason }}</td>
          </tr>
        </tbody>
      </table>

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
          <RouterLink :to="{ name: 'artifact', params: { id: row.id }, query: backQuery }">
            {{ row.label }}
          </RouterLink>
          <span class="mono id">{{ row.id }}</span>
        </li>
      </ul>

      <template v-if="showsCandidates">
        <h3>候選分支</h3>
        <p class="muted" aria-live="polite">
          已載入 {{ candidates.length }} 筆{{ hasMoreCandidates ? '（後端仍有下一頁）' : '（已到最後一頁）' }}。
        </p>
        <output v-if="candidatesError !== ''" class="alert-inline">{{ candidatesError }}</output>
        <p v-if="candidates.length === 0 && !candidatesLoading" class="muted">此任務尚未回報候選。</p>
        <table v-else class="compact-table">
          <thead>
            <tr>
              <th>名次</th>
              <th>來源</th>
              <th>驗證狀態</th>
              <th>候選識別碼</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in candidates" :key="row.id">
              <td class="mono">#{{ row.development_rank ?? '—' }}</td>
              <td>{{ row.source }}</td>
              <td>{{ statusLabels[row.validation_status] }}</td>
              <td class="mono">{{ row.id }}</td>
              <td>
                <RouterLink :to="{ name: 'candidate', params: { id: row.id }, query: withBackRef(route.fullPath, { run: runId }) }">
                  檢視公式
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
        <button
          v-if="hasMoreCandidates"
          type="button"
          :disabled="candidatesLoading"
          style="margin-top: 10px;"
          @click="loadCandidates(false)"
        >
          {{ candidatesLoading ? '載入中…' : '載入更多候選' }}
        </button>
      </template>

      <h3>事件</h3>
      <p class="muted" aria-live="polite">
        {{ followLabel }}
        <template v-if="follow.lastSyncedAt !== null">最後同步 {{ follow.lastSyncedAt }}。</template>
        <template v-if="events.length > 0">已收到 {{ events.length }} 筆。</template>
      </p>
      <output v-if="follow.error !== ''" class="alert-inline">{{ follow.error }}</output>
      <output v-if="follow.gapDetected" class="alert-inline">
        游標已過期，已依伺服器 snapshot 重新同步；期間的事件可能不完整，畫面不補猜。
      </output>
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
.actions {
  display: flex;
  gap: 0.75rem;
  align-items: center;
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
.alert-inline {
  color: var(--danger);
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
.link-stack {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.resource-link {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 0.65rem 0.8rem;
  background: var(--surface-2);
}
.compact-table {
  width: 100%;
  margin-top: 0.75rem;
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
