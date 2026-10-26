<script setup lang="ts">
/**
 * 知識庫（SSOT SCREEN 27）：已驗證結論、來源與檢索。
 *
 * 這一頁只呈現後端契約已揭露的內容：研究版本、證據包、品質報告與 validation run 的結論分布。
 * 後端沒有知識庫、主題標籤或語意檢索端點，這些欄位一律固定顯示「未取得」，不以推測值代替。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import MemoryTabs from '../components/MemoryTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useMemoryCenter } from '../lib/useMemoryCenter'
import { EVIDENCE_STATUS_LABELS, QUALITY_LABELS, READINESS_LABELS } from '../lib/evidence'
import { OUTCOME_LABELS } from '../lib/evaluation'
import {
  MEMORY_UNKNOWN,
  VERSION_STATUS_LABELS,
  buildKnowledgeRows,
  summarizeKnowledgeRows,
  type KnowledgeRow,
} from '../lib/memoryCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useMemoryCenter()

const selectedId = ref(readQueryString(route.query, 'version'))

/** 結論欄序固定，缺值不省略，讓四種 outcome 永遠可比較。 */
const OUTCOME_ORDER = ['SUPPORTED', 'AMBIGUOUS', 'INSUFFICIENT_EVIDENCE', 'FALSIFIED'] as const

const rows = computed<KnowledgeRow[]>(() => (center.value === null ? [] : buildKnowledgeRows(center.value)))
const summary = computed(() => summarizeKnowledgeRows(rows.value))
const selectedRow = computed<KnowledgeRow | null>(() => rows.value.find((row) => row.versionId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedRow.value
  if (row === null) return null
  return withBackRef(route.fullPath, { version: row.versionId, node: `version:${row.versionId}` })
})

function bundleStatusText(row: KnowledgeRow): string {
  return row.bundleStatus === null ? MEMORY_UNKNOWN : EVIDENCE_STATUS_LABELS[row.bundleStatus]
}

function qualityText(row: KnowledgeRow): string {
  return row.quality === null ? MEMORY_UNKNOWN : QUALITY_LABELS[row.quality]
}

function readinessText(row: KnowledgeRow): string {
  return row.readiness === null ? MEMORY_UNKNOWN : READINESS_LABELS[row.readiness]
}

function selectRow(row: KnowledgeRow): void {
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
        <div class="eyebrow">記憶 / SCREEN 27</div>
        <h1>知識庫</h1>
        <p class="muted">專屬任務畫面設計｜已驗證結論、來源與檢索：只列出後端已揭露的證據包、品質報告與驗證結論，不把候選假設當成已驗證知識。</p>
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
          <div class="eyebrow">已驗證結論</div>
          <div class="metric-value" :class="summary.conclusions > 0 ? 'good' : 'warn'">{{ summary.conclusions }}</div>
          <p>已讀取版本中 outcome 為 SUPPORTED 的 validation run 數量，代表配對區間落在實務邊界內。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">有證據底</div>
          <div class="metric-value" :class="summary.evidenceBacked > 0 ? 'good' : 'warn'">{{ summary.evidenceBacked }}</div>
          <p>至少引用一份可解析證據包的研究版本數；沒有證據包的版本不列入。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">證據已隔離</div>
          <div class="metric-value" :class="summary.quarantined > 0 ? 'bad' : 'good'">{{ summary.quarantined }}</div>
          <p>證據包狀態為 QUARANTINED 的版本數，這些證據不得再支撐結論。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">品質未通過</div>
          <div class="metric-value" :class="summary.blockedQuality > 0 ? 'warn' : 'good'">{{ summary.blockedQuality }}</div>
          <p>品質報告 quality 為 BLOCKED 的版本數，後端已判定不得進入提交。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">檢索主題標籤</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">語意檢索</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">跨研究知識連結</div>
          <p class="unknown-value">{{ MEMORY_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout knowledge-grid">
        <section class="card">
          <h3>知識條目</h3>
          <p class="muted">只涵蓋已讀取到的研究版本與其證據；後端沒有全域知識庫端點，未讀取範圍不在統計內。</p>
          <p v-if="rows.length === 0" class="muted">
            目前沒有可讀取的知識條目。研究版本若尚未產生證據包或品質報告，這一頁會保持空白而不是顯示推測內容。
          </p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 版本</th>
                <th>版本狀態</th>
                <th>證據包</th>
                <th>證明產物</th>
                <th>品質</th>
                <th>已驗證結論</th>
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
                  <span class="tag" :class="row.bundleStatus === 'ACTIVE' ? 'good' : row.bundleStatus === 'QUARANTINED' ? 'bad' : ''">
                    {{ row.bundleCount }}｜{{ bundleStatusText(row) }}
                  </span>
                </td>
                <td>{{ row.proofArtifactCount }}</td>
                <td>
                  <span class="tag" :class="row.quality === 'PASS' ? 'good' : row.quality === 'BLOCKED' ? 'warn' : ''">
                    {{ qualityText(row) }}
                  </span>
                </td>
                <td>{{ row.verifiedConclusions }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>選定知識條目</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆知識條目。</p>
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
              <span>證據包</span>
              <span class="tag">{{ selectedRow.bundleCount }}｜{{ bundleStatusText(selectedRow) }}</span>
            </div>
            <div class="row compact">
              <span>宣告驗證數</span>
              <span>{{ selectedRow.declaredValidationCount }}</span>
            </div>
            <div class="row compact">
              <span>證明產物數</span>
              <span>{{ selectedRow.proofArtifactCount }}</span>
            </div>
            <div class="row compact">
              <span>品質 / 就緒</span>
              <span class="tag">{{ qualityText(selectedRow) }}｜{{ readinessText(selectedRow) }}</span>
            </div>
            <div class="row compact">
              <span>檢索主題標籤</span>
              <span class="muted">{{ selectedRow.retrievalTags }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <h3 style="margin-top: 18px;">結論分布</h3>
            <div class="row compact" v-for="outcome in OUTCOME_ORDER" :key="outcome">
              <span>{{ OUTCOME_LABELS[outcome] }}</span>
              <span class="tag">{{ selectedRow.outcomes[outcome] }}</span>
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
              已驗證結論只由 validation run 的 outcome 計數推導；檢索標籤、語意檢索與跨研究連結需後端端點，本頁明示未取得而不補值。
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

.knowledge-grid {
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

  .knowledge-grid {
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
