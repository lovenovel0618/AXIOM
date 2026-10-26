<script setup lang="ts">
/**
 * 失敗案例（SSOT SCREEN 29）：否定證據、數值失敗與修復可能。
 *
 * 失敗案例只由已讀取的任務、凍結提交、validation run、品質報告與證據包推導；
 * 後端沒有根因分析與修復建議端點，這些欄位一律固定顯示「未取得」，不以推測值代替。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'
import MemoryTabs from '../components/MemoryTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useMemoryCenter } from '../lib/useMemoryCenter'
import {
  FAILURE_CATEGORY_LABELS,
  MEMORY_UNKNOWN,
  buildFailureRows,
  summarizeFailures,
  type FailureCategory,
  type FailureRow,
} from '../lib/memoryCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useMemoryCenter()

/** 類別欄序固定，缺類別不省略，讓五類失敗永遠可比較。 */
const CATEGORY_ORDER: readonly FailureCategory[] = [
  'RUN_FAILED',
  'SUBMISSION_FAILED',
  'FALSIFIED',
  'QUALITY_BLOCKED',
  'EVIDENCE_QUARANTINED',
]

type CategoryFilter = 'ALL' | FailureCategory

const CATEGORY_FILTERS: readonly CategoryFilter[] = [
  'ALL',
  'RUN_FAILED',
  'SUBMISSION_FAILED',
  'FALSIFIED',
  'QUALITY_BLOCKED',
  'EVIDENCE_QUARANTINED',
]

const selectedKey = ref(readQueryString(route.query, 'case'))
const appliedCategory = ref<CategoryFilter>(readCategoryFilter(route.query))
const draftCategory = ref<CategoryFilter>(appliedCategory.value)

function readCategoryFilter(query: LocationQuery): CategoryFilter {
  const raw = readQueryString(query, 'category')
  return raw !== '' && (CATEGORY_FILTERS as readonly string[]).includes(raw) ? (raw as CategoryFilter) : 'ALL'
}

const rows = computed<FailureRow[]>(() => (center.value === null ? [] : buildFailureRows(center.value)))
const summary = computed(() => summarizeFailures(rows.value))
const filtered = computed<FailureRow[]>(() =>
  appliedCategory.value === 'ALL' ? rows.value : rows.value.filter((row) => row.category === appliedCategory.value),
)
const selectedRow = computed<FailureRow | null>(() => filtered.value.find((row) => row.key === selectedKey.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedRow.value
  if (row === null || row.versionId === null) return null
  return withBackRef(route.fullPath, { version: row.versionId, node: `version:${row.versionId}` })
})

function categoryFilterLabel(filter: CategoryFilter): string {
  return filter === 'ALL' ? '全部' : FAILURE_CATEGORY_LABELS[filter]
}

async function applyFilter(): Promise<void> {
  appliedCategory.value = draftCategory.value
  await replaceQueryState(router, route, { category: draftCategory.value === 'ALL' ? undefined : draftCategory.value })
}

function selectRow(row: FailureRow): void {
  selectedKey.value = row.key
}

onMounted(async () => {
  await load()
  if (selectedKey.value === '' && filtered.value.length > 0) selectedKey.value = filtered.value[0]?.key ?? ''
})

watch(selectedKey, async (value) => {
  await replaceQueryState(router, route, { case: value === '' ? undefined : value })
})

watch(
  () => route.query.case,
  () => {
    selectedKey.value = readQueryString(route.query, 'case')
  },
)

watch(
  () => route.query.category,
  () => {
    const next = readCategoryFilter(route.query)
    appliedCategory.value = next
    draftCategory.value = next
  },
)

watch(filtered, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.key === selectedKey.value)) return
  selectedKey.value = value[0]?.key ?? ''
})
</script>

<template>
  <section>
    <MemoryTabs />

    <div class="head">
      <div>
        <div class="eyebrow">記憶 / SCREEN 29</div>
        <h1>失敗案例</h1>
        <p class="muted">專屬任務畫面設計｜否定證據、數值失敗與修復可能：只列出後端已揭露的失敗跡象與理由，不推測根因或修復方案。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'memory-recovery' }">
          <button type="button" class="primary">前往假設恢復</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section v-for="category in CATEGORY_ORDER" :key="category" class="card metric-card">
          <div class="eyebrow">{{ FAILURE_CATEGORY_LABELS[category] }}</div>
          <div
            class="metric-value"
            :class="summary[category] > 0 ? (category === 'FALSIFIED' ? 'bad' : 'warn') : 'good'"
          >
            {{ summary[category] }}
          </div>
          <p>
            <template v-if="category === 'RUN_FAILED'">狀態為 FAILED 的任務數。</template>
            <template v-else-if="category === 'SUBMISSION_FAILED'">最終評估狀態為 FAILED 的凍結提交數。</template>
            <template v-else-if="category === 'FALSIFIED'">outcome 為 FALSIFIED 的 validation run 數。</template>
            <template v-else-if="category === 'QUALITY_BLOCKED'">品質報告 quality 為 BLOCKED 的版本數。</template>
            <template v-else>證據包狀態為 QUARANTINED 的數量。</template>
          </p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">根因分析</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">修復建議</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">影響範圍</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout failure-grid">
        <section class="card">
          <h3>失敗案例清單</h3>
          <p class="muted">只涵蓋已讀取到的研究版本與其凍結提交；後端沒有全域失敗端點，未讀取範圍不在統計內。</p>
          <div class="filter-row">
            <label for="category-filter">類別篩選</label>
            <select id="category-filter" v-model="draftCategory">
              <option v-for="filter in CATEGORY_FILTERS" :key="filter" :value="filter">
                {{ categoryFilterLabel(filter) }}
              </option>
            </select>
            <button type="button" @click="applyFilter">套用</button>
          </div>

          <p v-if="filtered.length === 0" class="muted">
            目前沒有符合條件的失敗案例。若後端沒有失敗任務、被否證的驗證或隔離證據，這一頁會保持空白。
          </p>
          <table v-else>
            <thead>
              <tr>
                <th>類別</th>
                <th>研究 / 版本</th>
                <th>來源</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in filtered"
                :key="row.key"
                :class="{ active: row.key === selectedKey }"
                @click="selectRow(row)"
              >
                <td>
                  <span class="tag" :class="row.category === 'FALSIFIED' ? 'bad' : 'warn'">
                    {{ FAILURE_CATEGORY_LABELS[row.category] }}
                  </span>
                </td>
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId ?? MEMORY_UNKNOWN }}</div>
                </td>
                <td class="mono">{{ row.sourceId }}</td>
                <td>{{ row.reason }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>選定失敗案例</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆失敗案例。</p>
          <template v-else>
            <div class="row compact">
              <span>類別</span>
              <span class="tag" :class="selectedRow.category === 'FALSIFIED' ? 'bad' : 'warn'">
                {{ FAILURE_CATEGORY_LABELS[selectedRow.category] }}
              </span>
            </div>
            <div class="row compact">
              <span>來源</span>
              <span class="mono record-value">{{ selectedRow.sourceId }}</span>
            </div>
            <div class="row compact">
              <span>研究</span>
              <span>{{ selectedRow.researchName }}</span>
            </div>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono record-value">{{ selectedRow.versionId ?? MEMORY_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>理由</span>
              <span>{{ selectedRow.reason }}</span>
            </div>
            <div class="row compact">
              <span>修復建議</span>
              <span class="muted">{{ selectedRow.repair }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <h3 style="margin-top: 18px;">已揭露細節</h3>
            <p v-if="selectedRow.details.length === 0" class="muted">後端未揭露更多細節（{{ MEMORY_UNKNOWN }}）。</p>
            <ul v-else class="reasons">
              <li v-for="(detail, index) in selectedRow.details" :key="`${String(index)}-${detail}`">{{ detail }}</li>
            </ul>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                v-if="workbenchQuery !== null && selectedRow.researchId !== null"
                :to="{ name: 'research-workbench', params: { id: selectedRow.researchId }, query: workbenchQuery }"
              >
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
            <div class="note" style="margin-top: 12px;">
              失敗跡象全部來自契約欄位；根因分析、修復建議與影響範圍需後端端點，本頁明示未取得而不補值。
            </div>
          </template>
        </section>
      </div>
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

.failure-grid {
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

.compact {
  padding: 8px 0;
}

tbody tr {
  cursor: pointer;
}

tbody tr.active td {
  background: #132842;
}

.reasons {
  margin: 6px 0 0;
  padding-left: 18px;
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

  .failure-grid {
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
