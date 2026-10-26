<script setup lang="ts">
/**
 * 研究策略設定（SSOT SCREEN 40）：評估政策、切分、預算與研究域。
 *
 * 後端沒有治理政策或策略範本端點，本頁只投影研究版本已固定的評估政策（誤差模型、
 * 比較方法、基準、重抽樣次數與實務邊界）、觀測切分宣告、預算上限與研究域端點；
 * 策略名稱與治理規則後端未揭露，一律標示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import SettingsTabs from '../components/SettingsTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useSettingsCenter } from '../lib/useSettingsCenter'
import {
  SETTINGS_UNKNOWN,
  VERSION_STATUS_LABELS,
  buildStrategyRows,
  filterStrategyRows,
  summarizeStrategy,
  type StrategyRow,
} from '../lib/settingsCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useSettingsCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const selectedId = ref(readQueryString(route.query, 'version'))

const rows = computed<StrategyRow[]>(() => (center.value === null ? [] : buildStrategyRows(center.value)))
const visible = computed(() => filterStrategyRows(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeStrategy(rows.value))
const selectedRow = computed<StrategyRow | null>(() => rows.value.find((row) => row.versionId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => center.value?.scope.truncated ?? false)
const workbenchQuery = computed<Record<string, string>>(() =>
  withBackRef(route.fullPath, { version: selectedRow.value?.versionId }),
)

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

function selectRow(row: StrategyRow): void {
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

watch(visible, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.versionId === selectedId.value)) return
  selectedId.value = value[0]?.versionId ?? ''
})
</script>

<template>
  <section>
    <SettingsTabs />

    <div class="head">
      <div>
        <div class="eyebrow">設定 / SCREEN 40</div>
        <h1>研究策略設定</h1>
        <p class="muted">
          專屬任務畫面設計｜評估政策、切分、預算與研究域：只投影研究版本已固定的策略欄位；策略名稱、預設範本與治理規則後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <label class="field">
          <span class="field-label">搜尋研究版本</span>
          <input v-model="keyword" placeholder="研究名稱、版本 ID、政策版本或指紋" @keyup.enter="applySearch" />
        </label>
        <button type="button" @click="applySearch">搜尋</button>
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">策略版本</div>
          <div class="metric-value">{{ summary.versions }}</div>
          <p>本頁實際讀取到的研究版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已就緒</div>
          <div class="metric-value" :class="summary.ready > 0 ? 'good' : ''">{{ summary.ready }}</div>
          <p>版本狀態為「就緒」的策略數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">封存最終測試</div>
          <div class="metric-value" :class="summary.sealed > 0 ? 'good' : 'warn'">{{ summary.sealed }}</div>
          <p>宣告 <span class="mono">sealed_final_test</span> 的版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">研究域端點</div>
          <div class="metric-value">{{ summary.domainIntervals }}</div>
          <p>所有版本研究域端點區間合計。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">策略名稱與預設範本</div>
          <p class="unknown-value">{{ SETTINGS_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">治理規則與審批流程</div>
          <p class="unknown-value">{{ SETTINGS_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">策略套用範圍與生效時間</div>
          <p class="unknown-value">{{ SETTINGS_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout strategy-grid">
        <section class="card">
          <h3>策略清單</h3>
          <p class="muted">
            只涵蓋已讀取到的研究版本。
            <template v-if="truncated">後端仍有未讀取頁面，統計範圍以此為限。</template>
          </p>
          <p v-if="visible.length === 0" class="muted">目前沒有符合條件的策略版本。</p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 版本</th>
                <th>狀態</th>
                <th>切分</th>
                <th>研究域</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visible"
                :key="row.versionId"
                :class="{ active: row.versionId === selectedId }"
                @click="selectRow(row)"
              >
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId }}</div>
                </td>
                <td>
                  <span class="tag" :class="row.versionStatus === 'FAILED' ? 'bad' : row.versionStatus === 'READY' ? 'good' : ''">
                    {{ VERSION_STATUS_LABELS[row.versionStatus] }}
                  </span>
                </td>
                <td>{{ row.splitKindLabel }}</td>
                <td>{{ row.domainCount }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>策略詳情</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一筆策略版本。</p>
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
              <span>研究目的</span>
              <span>{{ selectedRow.purposeLabel }}</span>
            </div>

            <h3 style="margin-top: 18px;">評估政策</h3>
            <div class="row compact">
              <span>政策版本</span>
              <span class="mono record-value">{{ selectedRow.policyVersion }}</span>
            </div>
            <div class="row compact">
              <span>政策指紋</span>
              <span class="mono record-value">{{ selectedRow.policyHash }}</span>
            </div>
            <div class="row compact">
              <span>計量版本</span>
              <span>{{ selectedRow.metricVersion }}</span>
            </div>
            <div class="row compact">
              <span>誤差模型</span>
              <span>{{ selectedRow.errorModelLabel }}</span>
            </div>
            <div class="row compact">
              <span>比較方法</span>
              <span>{{ selectedRow.comparisonMethodLabel }}</span>
            </div>
            <div class="row compact">
              <span>基準線</span>
              <span>{{ selectedRow.baselineLabel }}</span>
            </div>
            <div class="row compact">
              <span>重抽樣次數 / 種子</span>
              <span>{{ selectedRow.bootstrapReplicates }} / {{ selectedRow.bootstrapSeed }}</span>
            </div>
            <div class="row compact">
              <span>實務邊界比例</span>
              <span class="mono record-value">{{ selectedRow.practicalMarginRatio }}</span>
            </div>

            <h3 style="margin-top: 18px;">觀測切分</h3>
            <div class="row compact">
              <span>切分方式</span>
              <span>{{ selectedRow.splitKindLabel }}</span>
            </div>
            <div class="row compact">
              <span>擬合 / 開發 / 最終測試列數</span>
              <span>{{ selectedRow.fitRows }} / {{ selectedRow.developmentRows }} / {{ selectedRow.finalTestRows }}</span>
            </div>
            <div class="row compact">
              <span>封存最終測試</span>
              <span class="tag" :class="selectedRow.sealedFinalTest ? 'good' : ''">
                {{ selectedRow.sealedFinalTest ? '已封存' : '未封存' }}
              </span>
            </div>

            <h3 style="margin-top: 18px;">預算與研究域</h3>
            <div class="row compact">
              <span>預算上限（CPU 秒 / GPU 秒）</span>
              <span>{{ selectedRow.budgetCpuSeconds }} / {{ selectedRow.budgetGpuSeconds }}</span>
            </div>
            <div class="row compact">
              <span>預算上限（Token）</span>
              <span>{{ selectedRow.budgetTokens }}</span>
            </div>
            <div class="row compact">
              <span>研究域端點</span>
              <span>{{ selectedRow.domainCount }}</span>
            </div>
            <div class="row compact">
              <span>建立時間</span>
              <span class="mono record-value">{{ selectedRow.createdAt }}</span>
            </div>

            <h3 style="margin-top: 18px;">治理</h3>
            <div class="row compact">
              <span>策略名稱</span>
              <span class="muted">{{ selectedRow.strategyName }}</span>
            </div>
            <div class="row compact">
              <span>治理規則</span>
              <span class="muted">{{ selectedRow.governanceRules }}</span>
            </div>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                v-if="selectedRow.researchId !== null"
                :to="{ name: 'research-workbench', params: { id: selectedRow.researchId }, query: workbenchQuery }"
              >
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
          </template>
        </section>
      </div>

      <section class="card note-card">
        <h3>目前邊界</h3>
        <p>
          後端沒有治理政策、策略範本、審批流程或策略生效端點，因此本頁只投影研究版本已固定的評估政策、觀測切分宣告、預算上限與研究域端點；策略名稱、預設範本、治理規則與套用範圍一律「未取得」。
        </p>
      </section>
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
  font-size: 28px;
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

.strategy-grid {
  grid-template-columns: 1.35fr 1fr;
}

.detail-card {
  margin-top: 0;
}

.note-card {
  margin-top: 16px;
}

.compact {
  padding: 8px 0;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label {
  font-size: 11px;
  color: #7fa1ce;
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

  .strategy-grid {
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
