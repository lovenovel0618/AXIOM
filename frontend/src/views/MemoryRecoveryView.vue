<script setup lang="ts">
/**
 * 假設恢復（SSOT SCREEN 30）：恢復條件、重新評估與候選佇列。
 *
 * 恢復清單只納入「實際出現失敗」的研究版本：任務失敗、提交評估失敗、否證、品質阻擋或證據隔離。
 * 後端沒有恢復條件、恢復預算或優先序端點，這些欄位一律固定顯示「未取得」，不以推測值代替。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import MemoryTabs from '../components/MemoryTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useMemoryCenter } from '../lib/useMemoryCenter'
import {
  FAILURE_CATEGORY_LABELS,
  MEMORY_UNKNOWN,
  VERSION_STATUS_LABELS,
  buildFailureRows,
  buildRecoveryRows,
  type RecoveryRow,
} from '../lib/memoryCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useMemoryCenter()

const selectedId = ref(readQueryString(route.query, 'version'))

const rows = computed<RecoveryRow[]>(() => {
  if (center.value === null) return []
  return buildRecoveryRows(center.value, buildFailureRows(center.value))
})
const selectedRow = computed<RecoveryRow | null>(() => rows.value.find((row) => row.versionId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedRow.value
  if (row === null) return null
  return withBackRef(route.fullPath, { version: row.versionId, node: `version:${row.versionId}` })
})

const summary = computed(() => ({
  versions: rows.value.length,
  withQualityBlocker: rows.value.filter((row) => row.blockers.includes('QUALITY_BLOCKED')).length,
  withQuarantine: rows.value.filter((row) => row.blockers.includes('EVIDENCE_QUARANTINED')).length,
  searchRuns: rows.value.reduce((total, row) => total + row.searchRunCount, 0),
}))

function blockerText(row: RecoveryRow): string {
  return row.blockers.map((category) => FAILURE_CATEGORY_LABELS[category]).join('、')
}

function selectRow(row: RecoveryRow): void {
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

watch(rows, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.versionId === selectedId.value)) return
  selectedId.value = value[0]?.versionId ?? ''
})
</script>

<template>
  <section>
    <MemoryTabs />

    <div class="head">
      <div>
        <div class="eyebrow">記憶 / SCREEN 30</div>
        <h1>假設恢復</h1>
        <p class="muted">專屬任務畫面設計｜恢復條件、重新評估與候選佇列：只納入實際失敗的版本，並以已揭露的證據與評估狀態說明可恢復程度。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'memory-failure' }">
          <button type="button" class="primary">前往失敗案例</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">待恢復版本</div>
          <div class="metric-value" :class="summary.versions > 0 ? 'warn' : 'good'">{{ summary.versions }}</div>
          <p>出現失敗跡象、需要重新評估或修正的研究版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">品質阻擋</div>
          <div class="metric-value" :class="summary.withQualityBlocker > 0 ? 'warn' : 'good'">{{ summary.withQualityBlocker }}</div>
          <p>因品質檢核未通過而進入恢復清單的版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">證據隔離</div>
          <div class="metric-value" :class="summary.withQuarantine > 0 ? 'bad' : 'good'">{{ summary.withQuarantine }}</div>
          <p>證據包被隔離、恢復前必須先重建證據的版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">可用搜尋任務</div>
          <div class="metric-value">{{ summary.searchRuns }}</div>
          <p>待恢復版本上已讀取到的 SEARCH 任務數，代表可重新評估的既有基礎。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">恢復條件</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">恢復預算</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">候選佇列優先序</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout recovery-grid">
        <section class="card">
          <h3>恢復清單</h3>
          <p class="muted">只有實際失敗的版本才進入清單；沒有失敗跡象的版本不會出現在這裡。</p>
          <p v-if="rows.length === 0" class="muted">
            目前沒有需要恢復的版本。若後端所有任務、提交與證據都正常，這一頁會保持空白。
          </p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 版本</th>
                <th>版本狀態</th>
                <th>阻擋類別</th>
                <th>證據就緒</th>
                <th>重新評估</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.versionId"
                :class="{ active: row.versionId === selectedId }"
                @click="selectRow(row)"
              >
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId }}</div>
                </td>
                <td>{{ VERSION_STATUS_LABELS[row.versionStatus] }}</td>
                <td>
                  <span class="tag warn">{{ blockerText(row) }}</span>
                </td>
                <td>{{ row.evidenceReadiness }}</td>
                <td>{{ row.reEvaluation }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>選定恢復項</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一個版本。</p>
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
              <span>阻擋類別</span>
              <span class="tag warn">{{ blockerText(selectedRow) }}</span>
            </div>
            <div class="row compact">
              <span>證據就緒</span>
              <span>{{ selectedRow.evidenceReadiness }}</span>
            </div>
            <div class="row compact">
              <span>重新評估狀態</span>
              <span>{{ selectedRow.reEvaluation }}</span>
            </div>
            <div class="row compact">
              <span>既有 SEARCH 任務</span>
              <span>{{ selectedRow.searchRunCount }}</span>
            </div>
            <div class="row compact">
              <span>恢復條件</span>
              <span class="muted">{{ selectedRow.condition }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                v-if="workbenchQuery !== null && selectedRow.researchId !== null"
                :to="{ name: 'research-workbench', params: { id: selectedRow.researchId }, query: workbenchQuery }"
              >
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
            <div class="note" style="margin-top: 12px;">
              恢復條件、恢復預算與候選優先序需後端端點；本頁只以既有任務與評估狀態說明恢復基礎，不代後端下可恢復結論。
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
  min-height: 150px;
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

.recovery-grid {
  grid-template-columns: 1.3fr 1fr;
}

.compact {
  padding: 8px 0;
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

  .recovery-grid {
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
