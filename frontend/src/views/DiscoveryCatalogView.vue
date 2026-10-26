<script setup lang="ts">
/**
 * 候選公式庫（SSOT SCREEN 18）：候選公式排序、適用條件及證據。
 *
 * 所有列都來自實際讀取的 SEARCH 任務與其候選；公式相關欄位要等 AST 載入才顯示，
 * 未載入一律「未取得」。後端沒有全域候選端點，統計範圍會明示在畫面上。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DiscoveryTabs from '../components/DiscoveryTabs.vue'
import { MAX_COMPARISON } from '../api/candidates'
import {
  buildDiscoveryCatalogCsv,
  buildDiscoveryCatalogRows,
  DISCOVERY_SORT_OPTIONS,
  DISCOVERY_UNKNOWN,
  filterDiscoveryCatalogRows,
  sortDiscoveryCatalogRows,
  summarizeDiscoveryStatus,
  VALIDATION_STATUS_LABELS,
  type DiscoveryCatalogRow,
  type DiscoverySort,
} from '../lib/discoveries'
import { useDiscoveryCatalog } from '../lib/useDiscoveryCatalog'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'

const route = useRoute()
const router = useRouter()
const { center, equations, loading, error, load } = useDiscoveryCatalog()

const keyword = ref('')
const statusFilter = ref<'ALL' | DiscoveryCatalogRow['validationStatus']>('ALL')
const sort = ref<DiscoverySort>('RANK_ASC')
const selectedId = ref(readQueryString(route.query, 'candidate'))
const notice = ref('')

const rows = computed<DiscoveryCatalogRow[]>(() => (center.value === null ? [] : buildDiscoveryCatalogRows(center.value, equations.value)))
const visibleRows = computed<DiscoveryCatalogRow[]>(() =>
  sortDiscoveryCatalogRows(filterDiscoveryCatalogRows(rows.value, keyword.value, statusFilter.value), sort.value),
)
const statusCounts = computed(() => summarizeDiscoveryStatus(rows.value))
const selectedRow = computed<DiscoveryCatalogRow | null>(
  () => visibleRows.value.find((row) => row.candidateId === selectedId.value) ?? rows.value.find((row) => row.candidateId === selectedId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))
const scope = computed(() => center.value?.scope ?? null)
const unknown = DISCOVERY_UNKNOWN

function statusTone(status: DiscoveryCatalogRow['validationStatus']): string {
  if (status === 'FINISHED') return 'good'
  if (status === 'INVALID') return 'bad'
  if (status === 'PENDING') return 'warn'
  return ''
}

function text(value: string | number | null): string {
  return value === null ? unknown : String(value)
}

function selectRow(row: DiscoveryCatalogRow): void {
  selectedId.value = row.candidateId
}

function download(name: string, content: string): void {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

function exportVisible(): void {
  if (visibleRows.value.length === 0) return
  notice.value = `已匯出目前視圖 ${String(visibleRows.value.length)} 筆候選（僅含本頁已讀取欄位）。`
  download('axiom-discovery-catalog.csv', buildDiscoveryCatalogCsv(visibleRows.value))
}

function resetFilters(): void {
  keyword.value = ''
  statusFilter.value = 'ALL'
  sort.value = 'RANK_ASC'
}

onMounted(async () => {
  await load()
  if (selectedId.value === '' && rows.value.length > 0) selectedId.value = rows.value[0]?.candidateId ?? ''
})

watch(selectedId, async (value) => {
  await replaceQueryState(router, route, { candidate: value === '' ? undefined : value })
})

watch(
  () => route.query.candidate,
  () => {
    selectedId.value = readQueryString(route.query, 'candidate')
  },
)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">發現 / 第 18 頁</div>
        <h1>候選公式庫</h1>
        <p class="muted">候選公式排序、適用條件及證據 · 專屬任務畫面設計</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'discovery-compare' }">
          <button type="button" class="primary">前往公式比較</button>
        </RouterLink>
      </div>
    </div>

    <DiscoveryTabs />

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else>
      <div class="note scope-note">
        <div class="row compact">
          <span>讀取範圍</span>
          <span class="tag">
            {{ scope?.researchesRead ?? 0 }} 研究 / {{ scope?.versionsRead ?? 0 }} 版本 /
            {{ scope?.searchRunsRead ?? 0 }} SEARCH 任務 / {{ scope?.candidatesRead ?? 0 }} 候選
          </span>
        </div>
        <div class="row compact">
          <span>後端分頁</span>
          <span class="tag" :class="scope?.truncated === true ? 'warn' : 'good'">
            {{ scope?.truncated === true ? '仍有未讀取頁面，統計僅涵蓋已讀取範圍' : '已讀取完畢' }}
          </span>
        </div>
        <div class="row compact">
          <span>狀態分布</span>
          <span class="tag">
            已完成 {{ statusCounts.FINISHED }} / 進行中 {{ statusCounts.PENDING }} /
            尚未執行 {{ statusCounts.NOT_RUN }} / 無效 {{ statusCounts.INVALID }}
          </span>
        </div>
      </div>

      <div class="layout catalog-grid">
        <section class="card">
          <h3>候選公式瀏覽</h3>
          <div class="formgrid">
            <div class="field">
              <label for="discovery-keyword">搜尋公式 / 來源 / 研究</label>
              <input id="discovery-keyword" v-model="keyword" placeholder="輸入關鍵字">
            </div>
            <div class="field">
              <label for="discovery-status">驗證狀態</label>
              <select id="discovery-status" v-model="statusFilter">
                <option value="ALL">全部</option>
                <option v-for="(label, value) in VALIDATION_STATUS_LABELS" :key="value" :value="value">{{ label }}</option>
              </select>
            </div>
            <div class="field">
              <label for="discovery-sort">排序</label>
              <select id="discovery-sort" v-model="sort">
                <option v-for="option in DISCOVERY_SORT_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </div>
          </div>
          <div class="actions">
            <button type="button" @click="resetFilters">清空篩選</button>
            <button type="button" :disabled="visibleRows.length === 0" @click="exportVisible">匯出目前視圖</button>
          </div>
          <p class="muted">顯示 {{ visibleRows.length }} / {{ rows.length }} 筆候選；公式欄位需 AST 載入，未載入一律顯示「{{ unknown }}」。</p>

          <p v-if="rows.length === 0" class="muted">
            目前沒有可讀取的候選。請確認研究版本已啟動 SEARCH 任務，候選會出現在對應的搜尋分支下。
          </p>
          <p v-else-if="visibleRows.length === 0" class="muted">沒有符合目前篩選條件的候選。</p>
          <table v-else>
            <thead>
              <tr>
                <th>ID</th>
                <th>候選公式</th>
                <th>複雜度</th>
                <th>狀態</th>
                <th>研究</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visibleRows"
                :key="row.candidateId"
                :class="{ active: row.candidateId === selectedId }"
                @click="selectRow(row)"
              >
                <td>
                  <div class="mono">{{ row.candidateId }}</div>
                  <div class="muted">#{{ row.developmentRank ?? unknown }}</div>
                </td>
                <td>
                  <div class="formula">{{ row.formula ?? unknown }}</div>
                  <div class="muted">{{ row.source }}</div>
                </td>
                <td>{{ text(row.complexity) }}</td>
                <td>
                  <span class="tag" :class="statusTone(row.validationStatus)">
                    {{ VALIDATION_STATUS_LABELS[row.validationStatus] }}
                  </span>
                </td>
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId ?? unknown }}</div>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="notice !== ''" class="note">{{ notice }}</p>
        </section>

        <section class="card">
          <h3>選定公式與證據</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一條候選公式。</p>
          <template v-else>
            <div class="formula-hero">{{ selectedRow.formula ?? unknown }}</div>
            <div class="row compact">
              <span>候選識別碼</span>
              <span class="mono">{{ selectedRow.candidateId }}</span>
            </div>
            <div class="row compact">
              <span>公式版本</span>
              <span class="mono">{{ selectedRow.equationVersionId }}</span>
            </div>
            <div class="row compact">
              <span>來源</span>
              <span>{{ selectedRow.source }}</span>
            </div>
            <div class="row compact">
              <span>模型複雜度</span>
              <span class="tag">{{ text(selectedRow.complexity) }}</span>
            </div>
            <div class="row compact">
              <span>變數 / 參數數</span>
              <span class="tag">{{ text(selectedRow.variableCount) }} / {{ text(selectedRow.parameterCount) }}</span>
            </div>
            <div class="row compact">
              <span>定義域</span>
              <span class="record-value">{{ selectedRow.domain ?? unknown }}</span>
            </div>

            <h3 style="margin-top: 18px;">證據</h3>
            <div class="row compact">
              <span>驗證狀態</span>
              <span class="tag" :class="statusTone(selectedRow.validationStatus)">
                {{ VALIDATION_STATUS_LABELS[selectedRow.validationStatus] }}
              </span>
            </div>
            <div class="row compact">
              <span>擬合任務</span>
              <span class="tag">{{ selectedRow.fitRunCount }} 筆</span>
            </div>
            <div class="row compact">
              <span>驗證任務</span>
              <span class="tag">{{ selectedRow.validationRunCount }} 筆</span>
            </div>
            <div class="row compact">
              <span>所屬搜尋任務</span>
              <span class="mono">{{ selectedRow.runId }}</span>
            </div>
            <div class="note" style="margin-top: 12px;">
              樣本外預測與反例搜尋的分數在凍結前不揭露；此處只呈現後端已回報的任務計數與狀態。
            </div>

            <div class="actions wrap" style="margin-top: 14px;">
              <RouterLink
                :to="{ name: 'candidate', params: { id: selectedRow.candidateId }, query: withBackRef(route.fullPath) }"
              >
                <button type="button">查看候選詳情</button>
              </RouterLink>
              <RouterLink :to="{ name: 'run', params: { id: selectedRow.runId }, query: withBackRef(route.fullPath) }">
                <button type="button">查看 SEARCH 任務</button>
              </RouterLink>
              <RouterLink
                :to="{ name: 'discovery-compare', query: withBackRef(route.fullPath, { run: selectedRow.runId, pins: selectedRow.candidateId }) }"
              >
                <button type="button" class="primary">加入公式比較</button>
              </RouterLink>
            </div>
            <p class="muted" style="margin-top: 12px;">
              公式比較同屏最多並排 {{ MAX_COMPARISON }} 條候選；加入時會自動帶上該候選所屬的 SEARCH 任務。
            </p>
          </template>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.catalog-grid {
  grid-template-columns: 1.2fr 1fr;
}

.scope-note {
  margin-bottom: 16px;
}

.compact {
  padding: 8px 0;
}

tbody tr.active td {
  background: #132842;
}

.formula {
  font: 14px ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere;
}

.formula-hero {
  font: 20px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #a7e4d6;
  overflow-wrap: anywhere;
  padding: 18px 0;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .catalog-grid {
    grid-template-columns: 1fr;
  }
}
</style>
