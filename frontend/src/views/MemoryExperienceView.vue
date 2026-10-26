<script setup lang="ts">
/**
 * 研究經驗（SSOT SCREEN 28）：策略成功與失敗經驗及條件。
 *
 * 經驗時間軸只由已讀取的任務推導：任務型別、狀態、停止理由、階段與所屬版本的評估政策雜湊。
 * 後端沒有經驗庫、策略名稱或經驗摘要端點，這些欄位一律固定顯示「未取得」，不以推測值代替。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'
import MemoryTabs from '../components/MemoryTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useMemoryCenter } from '../lib/useMemoryCenter'
import { OUTCOME_LABELS } from '../lib/evaluation'
import {
  EXPERIENCE_VERDICT_LABELS,
  MEMORY_UNKNOWN,
  PHASE_LABELS,
  RUN_STATUS_LABELS,
  RUN_TYPE_LABELS,
  STOP_REASON_LABELS,
  buildExperienceTimeline,
  summarizeExperience,
  type ExperienceEntry,
  type ExperienceVerdict,
} from '../lib/memoryCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useMemoryCenter()

type VerdictFilter = 'ALL' | ExperienceVerdict

const VERDICT_FILTERS: readonly VerdictFilter[] = ['ALL', 'SUCCESS', 'FAILURE', 'ABORTED', 'ACTIVE']

const selectedId = ref(readQueryString(route.query, 'run'))
/** 篩選刻意不即時套用：使用者按下「套用」才變更清單，避免邊選邊跳動。 */
const appliedVerdict = ref<VerdictFilter>(readVerdictFilter(route.query))
const draftVerdict = ref<VerdictFilter>(appliedVerdict.value)

function readVerdictFilter(query: LocationQuery): VerdictFilter {
  const raw = readQueryString(query, 'verdict')
  return raw !== '' && (VERDICT_FILTERS as readonly string[]).includes(raw) ? (raw as VerdictFilter) : 'ALL'
}

const entries = computed<ExperienceEntry[]>(() => (center.value === null ? [] : buildExperienceTimeline(center.value)))
const summary = computed(() => summarizeExperience(entries.value))
const filtered = computed<ExperienceEntry[]>(() =>
  appliedVerdict.value === 'ALL' ? entries.value : entries.value.filter((entry) => entry.verdict === appliedVerdict.value),
)
const selectedEntry = computed<ExperienceEntry | null>(() => filtered.value.find((entry) => entry.runId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const entry = selectedEntry.value
  if (entry === null) return null
  return withBackRef(route.fullPath, { version: entry.versionId ?? undefined, node: `run:${entry.runId}` })
})

function verdictFilterLabel(filter: VerdictFilter): string {
  return filter === 'ALL' ? '全部' : EXPERIENCE_VERDICT_LABELS[filter]
}

function outcomeText(entry: ExperienceEntry): string {
  return entry.outcome === null ? MEMORY_UNKNOWN : OUTCOME_LABELS[entry.outcome]
}

function stopReasonText(entry: ExperienceEntry): string {
  return entry.stopReason === null ? MEMORY_UNKNOWN : STOP_REASON_LABELS[entry.stopReason]
}

function phaseText(entry: ExperienceEntry): string {
  return entry.phase === null ? MEMORY_UNKNOWN : PHASE_LABELS[entry.phase]
}

async function applyFilter(): Promise<void> {
  appliedVerdict.value = draftVerdict.value
  await replaceQueryState(router, route, { verdict: draftVerdict.value === 'ALL' ? undefined : draftVerdict.value })
}

function selectEntry(entry: ExperienceEntry): void {
  selectedId.value = entry.runId
}

onMounted(async () => {
  await load()
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
  () => route.query.verdict,
  () => {
    const next = readVerdictFilter(route.query)
    appliedVerdict.value = next
    draftVerdict.value = next
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
    <MemoryTabs />

    <div class="head">
      <div>
        <div class="eyebrow">記憶 / 第 28 頁</div>
        <h1>研究經驗</h1>
        <p class="muted">專屬任務畫面設計｜策略成功與失敗經驗及條件：以任務時間軸呈現已揭露的執行條件與結果，不推測後端未提供的策略與教訓。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'memory' }">
          <button type="button" class="primary">前往知識庫</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">成功經驗</div>
          <div class="metric-value" :class="summary.SUCCESS > 0 ? 'good' : 'warn'">{{ summary.SUCCESS }}</div>
          <p>狀態為 SUCCEEDED 的任務數，可作為後續策略的正面對照。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">失敗經驗</div>
          <div class="metric-value" :class="summary.FAILURE > 0 ? 'bad' : 'good'">{{ summary.FAILURE }}</div>
          <p>狀態為 FAILED 的任務數，失敗案例頁會逐筆展開原因。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">中止經驗</div>
          <div class="metric-value" :class="summary.ABORTED > 0 ? 'warn' : 'good'">{{ summary.ABORTED }}</div>
          <p>狀態為 CANCELLED 的任務數，通常在預算耗盡或使用者中止時出現。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">進行中</div>
          <div class="metric-value">{{ summary.ACTIVE }}</div>
          <p>排隊中、執行中或取消中的任務數；這些經驗尚未定案。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">策略名稱</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">經驗摘要</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">建議下一步</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout experience-grid">
        <section class="card">
          <h3>經驗時間軸</h3>
          <p class="muted">只涵蓋已讀取到的任務；後端沒有全域經驗端點，未讀取範圍不在統計內。</p>
          <div class="filter-row">
            <label for="verdict-filter">結果篩選</label>
            <select id="verdict-filter" v-model="draftVerdict">
              <option v-for="filter in VERDICT_FILTERS" :key="filter" :value="filter">
                {{ verdictFilterLabel(filter) }}
              </option>
            </select>
            <button type="button" @click="applyFilter">套用</button>
          </div>

          <p v-if="filtered.length === 0" class="muted">
            目前沒有符合條件的任務經驗。若後端尚未執行任何任務，這一頁會保持空白而不是顯示推測內容。
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
                  <strong>{{ RUN_TYPE_LABELS[entry.runType] }}</strong>
                  <span class="muted">｜{{ entry.researchName }}</span>
                </div>
                <div class="muted mono">{{ entry.runId }}</div>
              </div>
              <div class="timeline-side">
                <span class="tag" :class="entry.verdict === 'SUCCESS' ? 'good' : entry.verdict === 'FAILURE' ? 'bad' : 'warn'">
                  {{ EXPERIENCE_VERDICT_LABELS[entry.verdict] }}
                </span>
                <span class="muted">{{ entry.createdAt }}</span>
              </div>
            </button>
          </div>
        </section>

        <section class="card">
          <h3>選定經驗</h3>
          <p v-if="selectedEntry === null" class="muted">請從左側時間軸選擇一筆經驗。</p>
          <template v-else>
            <div class="row compact">
              <span>任務</span>
              <span class="mono record-value">{{ selectedEntry.runId }}</span>
            </div>
            <div class="row compact">
              <span>任務型別</span>
              <span class="tag">{{ RUN_TYPE_LABELS[selectedEntry.runType] }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag">{{ RUN_STATUS_LABELS[selectedEntry.status] }}</span>
            </div>
            <div class="row compact">
              <span>結果判定</span>
              <span class="tag" :class="selectedEntry.verdict === 'SUCCESS' ? 'good' : selectedEntry.verdict === 'FAILURE' ? 'bad' : 'warn'">
                {{ EXPERIENCE_VERDICT_LABELS[selectedEntry.verdict] }}
              </span>
            </div>
            <div class="row compact">
              <span>結果狀態</span>
              <span>{{ outcomeText(selectedEntry) }}</span>
            </div>
            <div class="row compact">
              <span>停止理由</span>
              <span>{{ stopReasonText(selectedEntry) }}</span>
            </div>
            <div class="row compact">
              <span>階段</span>
              <span>{{ phaseText(selectedEntry) }}</span>
            </div>
            <div class="row compact">
              <span>研究 / 版本</span>
              <span class="mono record-value">
                {{ selectedEntry.researchName }}｜{{ selectedEntry.versionId ?? MEMORY_UNKNOWN }}
              </span>
            </div>
            <div class="row compact">
              <span>執行條件（評估政策雜湊）</span>
              <span class="mono record-value">{{ selectedEntry.condition }}</span>
            </div>
            <div class="row compact">
              <span>經驗摘要</span>
              <span class="muted">{{ selectedEntry.lesson }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedEntry.createdAt }}</span>
            </div>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink :to="{ name: 'run', params: { id: selectedEntry.runId } }">
                <button type="button">開啟任務詳情</button>
              </RouterLink>
              <RouterLink
                v-if="workbenchQuery !== null && selectedEntry.researchId !== null"
                :to="{ name: 'research-workbench', params: { id: selectedEntry.researchId }, query: workbenchQuery }"
              >
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
            <div class="note" style="margin-top: 12px;">
              執行條件以所屬研究版本的評估政策雜湊表示；策略名稱、經驗摘要與建議下一步需後端端點，本頁明示未取得而不補值。
            </div>
          </template>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
}

.metric-card {
  min-height: 140px;
}

.metric-value {
  font-size: 30px;
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

.experience-grid {
  grid-template-columns: 1.3fr 1fr;
}

.filter-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
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
  min-width: 0;
}

.timeline-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  white-space: nowrap;
}

.compact {
  padding: 8px 0;
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

  .experience-grid {
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
