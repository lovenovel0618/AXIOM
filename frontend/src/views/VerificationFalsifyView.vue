<script setup lang="ts">
/**
 * 反例搜尋（SSOT SCREEN 23）：反例空間、邊界條件與失效案例。
 *
 * 失效案例只由已讀取的 validation run 推導（否證、失敗列數、拒答理由）；後端沒有反例空間、
 * 邊界條件與反例預算端點，這些欄位一律固定顯示「未取得」，不以任何推測值代替。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import VerificationTabs from '../components/VerificationTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useVerificationCenter } from '../lib/useVerificationCenter'
import { SPLIT_ROLE_LABELS, VERIFICATION_UNKNOWN } from '../lib/verificationCenter'
import {
  BOUNDARY_CONDITION_UNKNOWN,
  COUNTEREXAMPLE_BUDGET_UNKNOWN,
  COUNTEREXAMPLE_SPACE_UNKNOWN,
  buildCounterexampleRows,
  summarizeFalsify,
  type CounterexampleRow,
} from '../lib/verificationFalsify'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useVerificationCenter()

const selectedId = ref(readQueryString(route.query, 'validation'))

const rows = computed<CounterexampleRow[]>(() => (center.value === null ? [] : buildCounterexampleRows(center.value)))
const summary = computed(() => summarizeFalsify(rows.value))
const selectedRow = computed<CounterexampleRow | null>(
  () => rows.value.find((row) => row.validationId === selectedId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedRow.value
  if (row === null) return null
  return withBackRef(route.fullPath, {
    version: row.versionId,
    flowkind: 'SUBMISSION',
    focussubmissions: row.submissionId,
    node: `submission:${row.submissionId}`,
  })
})

function selectRow(row: CounterexampleRow): void {
  selectedId.value = row.validationId
}

onMounted(async () => {
  await load()
  if (selectedId.value === '' && rows.value.length > 0) selectedId.value = rows.value[0]?.validationId ?? ''
})

watch(selectedId, async (value) => {
  await replaceQueryState(router, route, { validation: value === '' ? undefined : value })
})

watch(
  () => route.query.validation,
  () => {
    selectedId.value = readQueryString(route.query, 'validation')
  },
)

watch(rows, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.validationId === selectedId.value)) return
  selectedId.value = value[0]?.validationId ?? ''
})
</script>

<template>
  <section>
    <VerificationTabs />

    <div class="head">
      <div>
        <div class="eyebrow">驗證 / 第 23 頁</div>
        <h1>反例搜尋</h1>
        <p class="muted">專屬任務畫面設計｜反例空間、邊界條件與失效案例：只列出後端已揭露的否證、失敗列數與拒答理由，不推測反例空間。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'verification' }">
          <button type="button" class="primary">前往驗證中心</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">失效案例</div>
          <div class="metric-value" :class="summary.total > 0 ? 'warn' : 'good'">{{ summary.total }}</div>
          <p>已讀取 validation run 中被判否證、帶失敗列或有拒答理由的數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">被否證</div>
          <div class="metric-value" :class="summary.falsified > 0 ? 'bad' : 'good'">{{ summary.falsified }}</div>
          <p>outcome 為 FALSIFIED（配對區間落在實務邊界外）的驗證數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">有失敗列</div>
          <div class="metric-value" :class="summary.failed > 0 ? 'warn' : 'good'">{{ summary.failed }}</div>
          <p>後端回報 failed_count 大於 0 的驗證數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">拒答</div>
          <div class="metric-value" :class="summary.insufficient > 0 ? 'warn' : 'good'">{{ summary.insufficient }}</div>
          <p>outcome 為 INSUFFICIENT_EVIDENCE（比較前提未成立）的驗證數。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">反例空間</div>
          <p class="unknown-value">{{ COUNTEREXAMPLE_SPACE_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">邊界條件</div>
          <p class="unknown-value">{{ BOUNDARY_CONDITION_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">反例搜尋預算</div>
          <p class="unknown-value">{{ COUNTEREXAMPLE_BUDGET_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout falsify-grid">
        <section class="card">
          <h3>失效案例清單</h3>
          <p class="muted">只涵蓋已讀取到的研究版本與其 frozen submission；後端沒有全域反例端點，未讀取範圍不在統計內。</p>
          <p v-if="rows.length === 0" class="muted">
            最近沒有可讀取的失效案例。若後端尚未產生 validation run，或所有驗證都支持假設，這裡會保持空白。
          </p>
          <table v-else>
            <thead>
              <tr>
                <th>驗證執行</th>
                <th>研究</th>
                <th>切分</th>
                <th>結果</th>
                <th>失敗 / 有效 / 選取</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.validationId"
                :class="{ active: row.validationId === selectedId }"
                @click="selectRow(row)"
              >
                <td>
                  <div class="mono">{{ row.validationId }}</div>
                  <div class="muted mono">{{ row.submissionId }}</div>
                </td>
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId }}</div>
                </td>
                <td>{{ SPLIT_ROLE_LABELS[row.splitRole] }}</td>
                <td>
                  <span class="tag" :class="row.outcome === 'FALSIFIED' ? 'bad' : 'warn'">{{ row.outcomeLabel }}</span>
                </td>
                <td>{{ row.failedCount }} / {{ row.validCount }} / {{ row.selectedCount }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>選定失效案例</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆失效案例。</p>
          <template v-else>
            <div class="row compact">
              <span>驗證執行</span>
              <span class="mono record-value">{{ selectedRow.validationId }}</span>
            </div>
            <div class="row compact">
              <span>所屬提交</span>
              <span class="mono record-value">{{ selectedRow.submissionId }}</span>
            </div>
            <div class="row compact">
              <span>研究</span>
              <span>{{ selectedRow.researchName }}</span>
            </div>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono record-value">{{ selectedRow.versionId }}</span>
            </div>
            <div class="row compact">
              <span>切分角色</span>
              <span class="tag">{{ SPLIT_ROLE_LABELS[selectedRow.splitRole] }}</span>
            </div>
            <div class="row compact">
              <span>結果</span>
              <span class="tag" :class="selectedRow.outcome === 'FALSIFIED' ? 'bad' : 'warn'">{{ selectedRow.outcomeLabel }}</span>
            </div>
            <div class="row compact">
              <span>失敗 / 有效 / 選取列數</span>
              <span class="tag">{{ selectedRow.failedCount }} / {{ selectedRow.validCount }} / {{ selectedRow.selectedCount }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <h3 style="margin-top: 18px;">失效理由</h3>
            <p v-if="selectedRow.reasons.length === 0" class="muted">後端未揭露具體失效理由（{{ VERIFICATION_UNKNOWN }}）。</p>
            <ul v-else class="reasons">
              <li v-for="(reason, index) in selectedRow.reasons" :key="`${String(index)}-${reason}`">{{ reason }}</li>
            </ul>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                v-if="workbenchQuery !== null"
                :to="{ name: 'research-workbench', params: { id: selectedRow.researchId }, query: workbenchQuery }"
              >
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
            <div class="note" style="margin-top: 12px;">
              反例空間、邊界條件與搜尋預算需後端端點；本頁只呈現 validation run 已回報的失效跡象，並明示未取得的欄位。
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

.falsify-grid {
  grid-template-columns: 1.2fr 1fr;
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

  .falsify-grid {
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
