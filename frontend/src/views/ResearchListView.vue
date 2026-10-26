<script setup lang="ts">
/**
 * 研究清單（SSOT SCREEN 05）：查找、篩選、排序與批次管理研究入口。
 *
 * 任務統計只涵蓋本頁實際讀取的版本，並在畫面上以版本 ID 與提示說明範圍；
 * 後端沒有批次刪除或批次任務端點，因此批次動作只做「彙總檢視」與「匯出目前視圖」，不假裝能改寫研究事實。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  buildCatalogCsv,
  buildCatalogRows,
  describeStatus,
  filterCatalogRows,
  SORT_OPTIONS,
  sortCatalogRows,
  STATUS_OPTIONS,
  summarizeSelection,
  type CatalogRow,
  type CatalogSort,
  type CatalogStatus,
} from '../lib/researchCatalog'
import { useResearchCatalog } from '../lib/useResearchCatalog'

const { snapshot, loading, error, load } = useResearchCatalog()

const keyword = ref('')
const statusFilter = ref<'ALL' | CatalogStatus>('ALL')
const sort = ref<CatalogSort>('CREATED_DESC')
const selectedIds = ref<string[]>([])
const notice = ref('')

const rows = computed<CatalogRow[]>(() => buildCatalogRows(snapshot.value))
const visibleRows = computed<CatalogRow[]>(() =>
  sortCatalogRows(filterCatalogRows(rows.value, keyword.value, statusFilter.value), sort.value),
)
const summary = computed(() => summarizeSelection(rows.value, selectedIds.value))
const selectedVisibleCount = computed(
  () => visibleRows.value.filter((row) => selectedIds.value.includes(row.id)).length,
)
const allVisibleSelected = computed(
  () => visibleRows.value.length > 0 && selectedVisibleCount.value === visibleRows.value.length,
)

function statusTone(status: CatalogStatus): string {
  if (status === 'FAILED') return 'bad'
  if (status === 'NONE' || status === 'DRAFT') return 'warn'
  if (status === 'RUNNING' || status === 'QUEUED' || status === 'VALIDATING') return ''
  if (status === 'READY') return 'good'
  return ''
}

function toggleRow(id: string): void {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((entry) => entry !== id)
    : [...selectedIds.value, id]
}

function toggleVisible(): void {
  const visibleIds = visibleRows.value.map((row) => row.id)
  if (allVisibleSelected.value) {
    selectedIds.value = selectedIds.value.filter((id) => !visibleIds.includes(id))
    return
  }
  const merged = new Set([...selectedIds.value, ...visibleIds])
  selectedIds.value = [...merged]
}

function clearSelection(): void {
  selectedIds.value = []
}

function resetFilters(): void {
  keyword.value = ''
  statusFilter.value = 'ALL'
  sort.value = 'CREATED_DESC'
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

function exportSelection(): void {
  const selected = rows.value.filter((row) => selectedIds.value.includes(row.id))
  if (selected.length === 0) return
  notice.value = `已匯出 ${String(selected.length)} 筆已選研究（僅含本頁已讀取欄位）。`
  download('axiom-research-selection.csv', buildCatalogCsv(selected))
}

function exportVisible(): void {
  if (visibleRows.value.length === 0) return
  notice.value = `已匯出 ${String(visibleRows.value.length)} 筆目前視圖（僅含本頁已讀取欄位）。`
  download('axiom-research-catalog.csv', buildCatalogCsv(visibleRows.value))
}

function formatStamp(value: string | null): string {
  if (value === null) return '未取得'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-TW', { hour12: false })
}

onMounted(async () => {
  await load()
})
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">研究 / 第 5 頁</div>
        <h1>研究清單</h1>
        <p class="muted">查找、篩選、排序與批次管理研究入口 · 候選假設與已驗證證據不混用</p>
      </div>
      <div class="actions">
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'research-create' }">
          <button type="button" class="primary">新建研究</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && snapshot.researches.length === 0" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else>
      <div class="layout">
        <section class="card">
          <h3>搜尋與篩選</h3>
          <div class="formgrid">
            <div class="field">
              <label for="catalog-keyword">搜尋名稱 / ID</label>
              <input id="catalog-keyword" v-model="keyword" placeholder="輸入研究名稱或識別碼">
            </div>
            <div class="field">
              <label for="catalog-status">最新版本狀態</label>
              <select id="catalog-status" v-model="statusFilter">
                <option value="ALL">全部</option>
                <option v-for="option in STATUS_OPTIONS" :key="option" :value="option">
                  {{ describeStatus(option) }}
                </option>
              </select>
            </div>
            <div class="field">
              <label for="catalog-sort">排序</label>
              <select id="catalog-sort" v-model="sort">
                <option v-for="option in SORT_OPTIONS" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
          </div>
          <div class="actions">
            <button type="button" @click="resetFilters">清空篩選</button>
            <button type="button" :disabled="visibleRows.length === 0" @click="exportVisible">
              匯出目前視圖
            </button>
          </div>
          <p class="muted">
            顯示 {{ visibleRows.length }} / {{ rows.length }} 筆研究；任務統計只涵蓋本頁已讀取的版本，
            未讀取的版本不列入，也不以 0 筆代替。
          </p>
        </section>

        <section v-if="summary.selected > 0" class="card">
          <h3>批次工作區（已選 {{ summary.selected }} 筆）</h3>
          <div class="batch-grid">
            <div class="batch-cell">
              <div class="eyebrow">已讀取版本數</div>
              <div class="batch-value">{{ summary.versionCount }}</div>
            </div>
            <div class="batch-cell">
              <div class="eyebrow">已讀取任務數</div>
              <div class="batch-value">{{ summary.runCount }}</div>
            </div>
            <div class="batch-cell">
              <div class="eyebrow">進行中任務</div>
              <div class="batch-value">{{ summary.activeRunCount }}</div>
            </div>
            <div class="batch-cell">
              <div class="eyebrow">失敗任務</div>
              <div class="batch-value" :class="summary.failedRunCount > 0 ? 'bad' : ''">
                {{ summary.failedRunCount }}
              </div>
            </div>
          </div>
          <p v-if="summary.missing > 0" class="warn">
            有 {{ summary.missing }} 筆已選項目不在目前視圖內，彙總不包含它們。
          </p>
          <div class="actions">
            <button type="button" @click="exportSelection">匯出已選</button>
            <RouterLink v-if="summary.failedRunCount > 0" :to="{ name: 'pending' }">
              <button type="button">前往待處理事件</button>
            </RouterLink>
            <button type="button" @click="clearSelection">清除選取</button>
          </div>
          <div class="note">
            後端沒有批次刪除或批次派送端點，因此批次動作只做彙總檢視與匯出；要在單一研究上動作請進入工作台。
          </div>
        </section>

        <section class="card">
          <h3>研究清單</h3>
          <p v-if="rows.length === 0" class="muted">
            目前沒有可讀取的研究。可以先
            <RouterLink :to="{ name: 'research-create' }">新建研究</RouterLink>
            ，或從資料集頁面以「分析」建立研究版本。
          </p>
          <p v-else-if="visibleRows.length === 0" class="muted">沒有符合目前篩選條件的研究。</p>
          <table v-else>
            <thead>
              <tr>
                <th>
                  <label class="check">
                    <input
                      type="checkbox"
                      :checked="allVisibleSelected"
                      :aria-label="allVisibleSelected ? '取消全選' : '全選目前視圖'"
                      @change="toggleVisible"
                    >
                  </label>
                </th>
                <th>研究</th>
                <th>最新版本</th>
                <th>版本數</th>
                <th>任務（已讀取範圍）</th>
                <th>最近任務時間</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visibleRows" :key="row.id">
                <td>
                  <label class="check">
                    <input
                      type="checkbox"
                      :checked="selectedIds.includes(row.id)"
                      :aria-label="`選取 ${row.name}`"
                      @change="toggleRow(row.id)"
                    >
                  </label>
                </td>
                <td>
                  <b>{{ row.name }}</b>
                  <div class="mono">{{ row.id }}</div>
                  <div class="muted">建立 {{ formatStamp(row.createdAt) }}</div>
                </td>
                <td>
                  <span class="tag" :class="statusTone(row.latestStatus)">
                    {{ describeStatus(row.latestStatus) }}
                  </span>
                  <div class="mono">{{ row.latestVersionId ?? '未取得' }}</div>
                  <div class="muted">{{ row.latestPurpose ?? '未取得' }}</div>
                </td>
                <td>
                  {{ row.versionCount }}<span v-if="row.hasMoreVersions">+</span>
                  <div v-if="row.hasMoreVersions" class="muted">後端仍有未讀取頁面</div>
                </td>
                <td>
                  <template v-if="row.runScopedVersionIds.length === 0">
                    <span class="muted">未取得（未讀取任務）</span>
                  </template>
                  <template v-else>
                    <div>共 {{ row.runCount }} 筆</div>
                    <div class="muted">
                      進行中 {{ row.activeRunCount }} · 失敗 {{ row.failedRunCount }} · SEARCH {{ row.searchRunCount }}
                    </div>
                    <div class="muted mono">範圍 {{ row.runScopedVersionIds.join('、') }}</div>
                  </template>
                </td>
                <td>{{ formatStamp(row.lastActivityAt) }}</td>
                <td>
                  <RouterLink
                    :to="{
                      name: 'research-workbench',
                      params: { id: row.id },
                      query:
                        row.latestVersionId === null
                          ? { ref: '/researches' }
                          : { ref: '/researches', version: row.latestVersionId },
                    }"
                  >
                    <button type="button" class="primary">進入工作台</button>
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="notice !== ''" class="note">{{ notice }}</p>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.batch-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.batch-cell {
  border: 1px solid #24384f;
  border-radius: 10px;
  padding: 12px 14px;
  background: #0e1c2f;
}

.batch-value {
  font-size: 22px;
  font-weight: 700;
  margin-top: 6px;
}

.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.check input {
  width: auto;
}

@media (max-width: 1200px) {
  .batch-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
