<script setup lang="ts">
/**
 * 研究任務紀錄（SSOT SCREEN 10）：執行排程、重試、失敗與事件重播。
 *
 * 時間軸只由已讀取到的任務推導：型別、狀態、階段、停止理由、結果判定、預算用量、
 * 事件游標與子任務。後端沒有研究層級的排程或事件重播端點，因此排程器狀態、重播播放
 * 與事件內容一律「未取得」，本頁只提供進入任務詳情檢視事件的入口。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'
import ResearchTabs from '../components/ResearchTabs.vue'
import type { RunStatus } from '../api/runs'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useResearchPanel } from '../lib/useResearchPanel'
import {
  RESEARCH_UNKNOWN,
  RUN_STATUS_LABELS,
  buildResearchTimeline,
  filterResearchTimeline,
  summarizeResearchTimeline,
  type TimelineEntry,
} from '../lib/researchPanels'

const route = useRoute()
const router = useRouter()
const { panel, loading, error, load } = useResearchPanel()

type StatusFilter = 'ALL' | RunStatus

const STATUS_FILTERS: readonly StatusFilter[] = [
  'ALL',
  'QUEUED',
  'RUNNING',
  'CANCEL_REQUESTED',
  'SUCCEEDED',
  'FAILED',
  'CANCELLED',
]

function readStatusFilter(query: LocationQuery): StatusFilter {
  const raw = readQueryString(query, 'status')
  return raw !== '' && (STATUS_FILTERS as readonly string[]).includes(raw) ? (raw as StatusFilter) : 'ALL'
}

const researchId = computed<string>(() => {
  const raw = route.params.id
  return typeof raw === 'string' ? raw : (raw?.[0] ?? '')
})

const selectedId = ref(readQueryString(route.query, 'run'))
/** 篩選刻意不即時套用：按下「套用」才變更清單並寫入 URL。 */
const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const appliedStatus = ref<StatusFilter>(readStatusFilter(route.query))
const draftStatus = ref<StatusFilter>(appliedStatus.value)

const entries = computed<TimelineEntry[]>(() => (panel.value === null ? [] : buildResearchTimeline(panel.value)))
const summary = computed(() => summarizeResearchTimeline(entries.value))
const filtered = computed<TimelineEntry[]>(() =>
  filterResearchTimeline(entries.value, appliedKeyword.value, appliedStatus.value),
)
const selectedEntry = computed<TimelineEntry | null>(
  () => filtered.value.find((entry) => entry.runId === selectedId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => panel.value?.scope.truncated ?? false)

function statusLabel(filter: StatusFilter): string {
  return filter === 'ALL' ? '全部' : RUN_STATUS_LABELS[filter]
}

function entryTone(entry: TimelineEntry): string {
  if (entry.tone === 'OK') return 'good'
  if (entry.tone === 'FAILED') return 'bad'
  if (entry.tone === 'RUNNING' || entry.tone === 'PENDING') return 'warn'
  return ''
}

function usage(entry: TimelineEntry): string {
  if (entry.cpuSeconds === null && entry.gpuSeconds === null && entry.tokens === null) return RESEARCH_UNKNOWN
  return `CPU ${String(entry.cpuSeconds ?? 0)} 秒／GPU ${String(entry.gpuSeconds ?? 0)} 秒／Token ${String(entry.tokens ?? 0)}`
}

async function applyFilter(): Promise<void> {
  appliedKeyword.value = keyword.value
  appliedStatus.value = draftStatus.value
  await replaceQueryState(router, route, {
    q: keyword.value,
    status: draftStatus.value === 'ALL' ? undefined : draftStatus.value,
  })
}

function selectEntry(entry: TimelineEntry): void {
  selectedId.value = entry.runId
}

async function reload(): Promise<void> {
  await load(researchId.value)
}

onMounted(async () => {
  await reload()
  if (selectedId.value === '' && filtered.value.length > 0) selectedId.value = filtered.value[0]?.runId ?? ''
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

watch(
  [() => route.query.q, () => route.query.status],
  () => {
    appliedKeyword.value = readQueryString(route.query, 'q')
    const next = readStatusFilter(route.query)
    appliedStatus.value = next
    draftStatus.value = next
  },
)

watch(
  () => route.params.id,
  async () => {
    await reload()
  },
)

watch(filtered, (value) => {
  if (value.length === 0) return
  if (value.some((entry) => entry.runId === selectedId.value)) return
  selectedId.value = value[0]?.runId ?? ''
})
</script>

<template>
  <section>
    <ResearchTabs :research-id="researchId" />

    <div class="head">
      <div>
        <div class="eyebrow">研究 / 第 10 頁</div>
        <h1>研究任務紀錄</h1>
        <p class="muted">
          專屬任務畫面設計｜執行排程、重試、失敗與事件重播：時間軸只由已讀取的任務推導；排程器狀態、重播播放與事件內容後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="reload">重新載入</button>
        <RouterLink v-if="researchId !== ''" :to="{ name: 'research-graph', params: { id: researchId } }">
          <button type="button" class="primary">前往研究分支圖</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && panel === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="panel !== null">
      <p v-if="panel.research === null" class="note">
        查無此研究，或目前身分沒有讀取權限；本頁不顯示任何推測內容。
        <RouterLink :to="{ name: 'research-list' }">返回研究清單</RouterLink>
      </p>

      <template v-else>
        <div class="layout metric-grid">
          <section class="card metric-card">
            <div class="eyebrow">任務紀錄</div>
            <div class="metric-value">{{ summary.entries }}</div>
            <p>本頁實際讀取到的任務數。<template v-if="truncated">後端仍有未讀取頁面，統計範圍以此為限。</template></p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">排隊中</div>
            <div class="metric-value">{{ summary.queued }}</div>
            <p>尚未開始執行的任務數。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">執行中</div>
            <div class="metric-value" :class="summary.running > 0 ? 'warn' : ''">{{ summary.running }}</div>
            <p>進行中或等待取消的任務數。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">失敗</div>
            <div class="metric-value" :class="summary.failed > 0 ? 'bad' : 'good'">{{ summary.failed }}</div>
            <p>狀態為「失敗」的任務數。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">重試 / 已結束</div>
            <div class="metric-value">{{ summary.retried }} / {{ summary.terminal }}</div>
            <p>同版本同型任務的後續嘗試數，以及已進入終止狀態的任務數。</p>
          </section>
        </div>

        <div class="layout timeline-grid">
          <section class="card">
            <h3>執行時間軸</h3>
            <p class="muted">依建立時間由新到舊；只涵蓋本頁已讀取到的任務。</p>
            <div class="filter-row">
              <label for="timeline-keyword">關鍵字</label>
              <input
                id="timeline-keyword"
                v-model="keyword"
                placeholder="任務識別碼、型別或狀態"
                @keyup.enter="applyFilter"
              />
              <label for="timeline-status">狀態</label>
              <select id="timeline-status" v-model="draftStatus">
                <option v-for="filter in STATUS_FILTERS" :key="filter" :value="filter">
                  {{ statusLabel(filter) }}
                </option>
              </select>
              <button type="button" @click="applyFilter">套用</button>
            </div>

            <p v-if="filtered.length === 0" class="muted">
              目前沒有符合條件的任務紀錄。若此研究尚未執行任何任務，這一頁會保持空白而不是顯示推測內容。
            </p>
            <div v-else class="timeline">
              <button
                v-for="entry in filtered"
                :key="entry.runId"
                type="button"
                class="module-link selectable"
                :class="{ active: entry.runId === selectedId }"
                @click="selectEntry(entry)"
              >
                <div class="timeline-main">
                  <div>
                    <strong>{{ entry.typeLabel }}</strong>
                    <span v-if="entry.isRetry" class="tag warn">重試 {{ entry.retryIndex }}</span>
                    <span v-if="!entry.terminal" class="tag">未結束</span>
                  </div>
                  <div class="muted mono">{{ entry.runId }}</div>
                </div>
                <div class="timeline-side">
                  <span class="tag" :class="entryTone(entry)">{{ entry.statusLabel }}</span>
                  <span class="muted">{{ entry.createdAt }}</span>
                </div>
              </button>
            </div>
          </section>

          <section class="card">
            <h3>選定任務紀錄</h3>
            <p v-if="selectedEntry === null" class="muted">請從左側時間軸選擇一筆任務紀錄。</p>
            <template v-else>
              <div class="row compact">
                <span>任務</span>
                <span class="mono record-value">{{ selectedEntry.runId }}</span>
              </div>
              <div class="row compact">
                <span>任務型別</span>
                <span class="tag">{{ selectedEntry.typeLabel }}（{{ selectedEntry.type }}）</span>
              </div>
              <div class="row compact">
                <span>狀態</span>
                <span class="tag" :class="entryTone(selectedEntry)">{{ selectedEntry.statusLabel }}</span>
              </div>
              <div class="row compact">
                <span>所屬版本</span>
                <span class="muted record-value">{{ selectedEntry.versionLabel }}</span>
              </div>
              <div class="row compact">
                <span>階段</span>
                <span>{{ selectedEntry.phase }}</span>
              </div>
              <div class="row compact">
                <span>停止理由</span>
                <span>{{ selectedEntry.stopReason }}</span>
              </div>
              <div class="row compact">
                <span>結果判定</span>
                <span>{{ selectedEntry.outcomeStatus }}</span>
              </div>
              <div class="row compact">
                <span>控制版本</span>
                <span>{{ selectedEntry.revision }}</span>
              </div>
              <div class="row compact">
                <span>嘗試序號</span>
                <span>
                  <span class="tag" :class="selectedEntry.isRetry ? 'warn' : ''">
                    {{ selectedEntry.isRetry ? `第 ${selectedEntry.retryIndex} 次（重試）` : '第 1 次' }}
                  </span>
                </span>
              </div>
              <div class="row compact">
                <span>用量</span>
                <span>{{ usage(selectedEntry) }}</span>
              </div>
              <div class="row compact">
                <span>子任務</span>
                <span>{{ selectedEntry.childRuns }}</span>
              </div>
              <div class="row compact">
                <span>診斷與追蹤產物</span>
                <span>{{ selectedEntry.artifacts }}</span>
              </div>
              <div class="row compact">
                <span>事件游標</span>
                <span class="mono record-value">{{ selectedEntry.replayCursor }}</span>
              </div>
              <div class="row compact">
                <span>建立時間</span>
                <span class="mono record-value">{{ selectedEntry.createdAt }}</span>
              </div>

              <div class="actions" style="margin-top: 14px;">
                <RouterLink :to="{ name: 'run', params: { id: selectedEntry.runId }, query: { ref: route.fullPath } }">
                  <button type="button">開啟任務詳情與事件</button>
                </RouterLink>
                <RouterLink
                  :to="{
                    name: 'research-workbench',
                    params: { id: researchId },
                    query: withBackRef(route.fullPath, { version: selectedEntry.versionId, node: `run:${selectedEntry.runId}` }),
                  }"
                >
                  <button type="button">在研究室中開啟</button>
                </RouterLink>
              </div>

              <div class="note" style="margin-top: 12px;">
                事件重播以任務的事件游標為起點，事件內容由任務詳情的事件串流取得；後端沒有研究層級的排程器、重播播放或執行計畫端點，因此排程策略、執行計畫與重播控制一律「未取得」。
              </div>
            </template>
          </section>
        </div>

        <section class="card note-card">
          <h3>目前邊界</h3>
          <p>
            後端沒有研究層級的執行排程、重試政策、事件重播或執行計畫端點，因此本頁只呈現研究、研究版本與任務已揭露的欄位：時間軸、狀態、重試序號與用量皆由實際讀取到的任務推導，重試序號只依「同版本同型任務」的建立時間計算；排程策略、重試上限、失敗根因與事件內容一律「未取得」，不以推測補值。
          </p>
        </section>
      </template>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
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

.timeline-grid {
  grid-template-columns: 1.3fr 1fr;
  margin-bottom: 16px;
}

.filter-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1.4fr) auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.filter-row label {
  color: #b2c5df;
  font-size: 12px;
  white-space: nowrap;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.module-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
}

.selectable {
  width: 100%;
  text-align: left;
}

.selectable.active {
  border-color: #3673c7;
  background: #132842;
}

.timeline-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.timeline-main .tag {
  margin-left: 6px;
}

.timeline-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  white-space: nowrap;
}

.note-card {
  margin-top: 16px;
}

.compact {
  padding: 8px 0;
}

.record-value {
  max-width: 58%;
  text-align: right;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .timeline-grid,
  .filter-row {
    grid-template-columns: 1fr;
  }
}
</style>
