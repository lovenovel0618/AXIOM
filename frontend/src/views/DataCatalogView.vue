<script setup lang="ts">
/**
 * 資料集清單（SSOT SCREEN 11，catalog）：資料來源、版本、權限與品質的入口。
 *
 * 只呈現後端已揭露的資料集與資料集版本欄位；權限來源、品質評分與資料來源型別沒有對應端點，
 * 一律固定顯示「未取得」，不以推測補值。`分析` 以最新可用且具結構預覽的版本建立研究並啟動分析。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DataTabs from '../components/DataTabs.vue'
import { createDataset, type UploadFormat } from '../api/datasets'
import { runQuickAnalysis } from '../lib/dataAnalyze'
import {
  DATA_UNKNOWN,
  FORMAT_LABELS,
  buildCatalogRows,
  filterCatalogRows,
  summarizeCatalog,
  type CatalogRow,
} from '../lib/dataCenter'
import { describeError } from '../lib/messages'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'
import { fetchStructureMetadata, useDataCenter } from '../lib/useDataCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useDataCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const name = ref('')
const busy = ref(false)
const analyzingId = ref('')
const notice = ref('')

const rows = computed<CatalogRow[]>(() => (center.value === null ? [] : buildCatalogRows(center.value)))
const visible = computed(() => filterCatalogRows(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeCatalog(rows.value))

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

/** 版本格式標籤；沒有任何版本時回報未取得，不由前端推測來源格式。 */
function formatLabels(formats: UploadFormat[]): string {
  if (formats.length === 0) return DATA_UNKNOWN
  return formats.map((item) => FORMAT_LABELS[item]).join('、')
}

async function submitDataset(): Promise<void> {
  if (busy.value || name.value.trim() === '') return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const created = await createDataset(client, name.value.trim())
    name.value = ''
    notice.value = `已建立資料集「${created.name}」，請接續上傳資料檔。`
    await load()
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    busy.value = false
  }
}

async function analyze(row: CatalogRow): Promise<void> {
  const versionId = row.analyzeVersionId
  if (versionId === null || analyzingId.value !== '') return
  const version = (center.value?.versionsByDataset[row.dataset.id] ?? []).find((entry) => entry.id === versionId) ?? null
  if (version === null) return
  analyzingId.value = row.dataset.id
  error.value = ''
  notice.value = ''
  try {
    const previewId = version.structure_preview_artifact_id
    const metadata = previewId === null ? null : await fetchStructureMetadata(previewId)
    const outcome = await runQuickAnalysis(client, row.dataset, version, metadata)
    if (!outcome.ok) {
      error.value = outcome.reason
      return
    }
    notice.value = `已建立研究並啟動分析，任務狀態：${outcome.analysis.runStatus}。`
    await router.push({
      name: 'research-workbench',
      params: { id: outcome.analysis.researchId },
      query: { version: outcome.analysis.researchVersionId },
    })
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    analyzingId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section>
    <DataTabs />

    <div class="head">
      <div>
        <div class="eyebrow">數據 / SCREEN 11</div>
        <h1>資料集清單</h1>
        <p class="muted">
          資料來源、版本、權限與品質｜只列出後端已揭露的資料集與不可變版本；權限、品質評分與來源型別沒有對應端點，一律標示「未取得」。
        </p>
      </div>
      <div class="actions">
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'research-create' }"><button type="button">改由研究精靈建立</button></RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== '' && center === null" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">資料集</div>
          <div class="metric-value">{{ summary.datasets }}</div>
          <p class="muted">
            已讀取 {{ center.scope.datasetsRead }} 筆{{ center.datasetTruncated ? '（後端仍有未讀取頁面）' : '' }}
          </p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">版本</div>
          <div class="metric-value">{{ summary.versions }}</div>
          <p class="muted">
            已讀取 {{ center.scope.versionsRead }} 筆{{ center.versionTruncated.length > 0 ? '，部分資料集仍有未讀取版本' : '' }}
          </p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">總列數</div>
          <div class="metric-value">{{ summary.rows }}</div>
          <p class="muted">所有已讀取版本的列數加總。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">可分析資料集</div>
          <div class="metric-value" :class="summary.analyzable > 0 ? 'good' : 'warn'">{{ summary.analyzable }}</div>
          <p class="muted">具備可用且含結構預覽版本、可直接啟動分析的資料集數。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">資料來源型別</div>
          <p class="unknown-value">{{ DATA_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">存取權限與角色</div>
          <p class="unknown-value">{{ DATA_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">資料集品質評分</div>
          <p class="unknown-value">{{ DATA_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout cols2">
        <section class="card">
          <h3>篩選與建立</h3>
          <div class="formgrid">
            <div class="field">
              <label for="data-catalog-keyword">關鍵字</label>
              <input
                id="data-catalog-keyword"
                v-model="keyword"
                name="data-catalog-keyword"
                maxlength="200"
                placeholder="資料集名稱或編號"
              >
            </div>
            <div class="field">
              <label for="data-catalog-name">新資料集名稱</label>
              <input
                id="data-catalog-name"
                v-model="name"
                name="data-catalog-name"
                maxlength="200"
                placeholder="請輸入資料集名稱"
              >
            </div>
          </div>
          <div class="actions">
            <button type="button" @click="applySearch">🔍 搜尋</button>
            <button type="button" class="primary" :disabled="busy || name.trim() === ''" @click="submitDataset">
              建立資料集
            </button>
          </div>
          <div class="note" style="margin-top: 14px;">
            篩選只在按下「搜尋」後套用，並以 `q` 寫入 URL；重新整理後可還原同一組條件。
          </div>
        </section>

        <section class="card">
          <h3>資料集清單</h3>
          <p v-if="rows.length === 0" class="muted">目前沒有可讀取的資料集。可先建立資料集，再接續上傳資料檔。</p>
          <p v-else-if="visible.length === 0" class="muted">沒有符合「{{ appliedKeyword }}」的資料集，請調整關鍵字後重新搜尋。</p>
          <table v-else>
            <thead>
              <tr>
                <th>名稱 / 編號</th>
                <th>版本</th>
                <th>總列數</th>
                <th>最新可分析版本</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visible" :key="row.dataset.id">
                <td>
                  <div>{{ row.dataset.name }}</div>
                  <div class="mono record-value">{{ row.dataset.id }}</div>
                </td>
                <td>
                  <span class="tag">{{ row.digest.versionCount }}{{ row.versionTruncated ? '+' : '' }}</span>
                  <span v-if="row.digest.unavailableCount !== 0" class="tag bad">不可用 {{ row.digest.unavailableCount }}</span>
                  <div class="muted">
                    {{ formatLabels(row.digest.formats) }}
                  </div>
                </td>
                <td>{{ row.digest.totalRows }}</td>
                <td>
                  <span v-if="row.analyzeVersionId === null" class="muted">{{ DATA_UNKNOWN }}</span>
                  <span v-else class="mono record-value">{{ row.analyzeVersionId }}</span>
                </td>
                <td>
                  <div class="actions">
                    <RouterLink :to="{ name: 'data-upload', params: { id: row.dataset.id } }">
                      <button type="button">上傳精靈</button>
                    </RouterLink>
                    <RouterLink :to="{ name: 'data-preview', params: { id: row.dataset.id } }">
                      <button type="button">資料預覽</button>
                    </RouterLink>
                    <button
                      type="button"
                      class="primary"
                      :disabled="row.analyzeVersionId === null || analyzingId !== ''"
                      :title="row.analyzeVersionId === null ? '沒有可用且具結構預覽的版本，無法分析' : '以最新可用版本建立研究並啟動分析'"
                      @click="analyze(row)"
                    >
                      {{ analyzingId === row.dataset.id ? '分析中…' : '分析' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <p v-if="error !== ''" class="bad" style="margin-top: 16px;">{{ error }}</p>
      <output v-if="notice" class="good" style="display: block; margin-top: 16px;">{{ notice }}</output>
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

.record-value {
  max-width: 100%;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: 1fr;
  }
}
</style>
