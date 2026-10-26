<script setup lang="ts">
/**
 * 系統與安全設定（SSOT SCREEN 39）：角色與權限、金鑰與 Token、稽核與留存。
 *
 * 後端沒有角色權限、金鑰、稽核留存或加密政策端點，因此本頁每一列都必須指出可追溯
 * 來源：只有服務就緒、工作階段機制、租戶識別與讀取範圍是可讀的，其餘一律標示
 * 「未取得」，不以推測值補上任何設定內容。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SettingsTabs from '../components/SettingsTabs.vue'
import { readBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useSettingsCenter } from '../lib/useSettingsCenter'
import { SETTINGS_UNKNOWN, buildSecurityRows, filterSecurityRows, summarizeSecurity, type SecurityRow } from '../lib/settingsCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useSettingsCenter()

const keyword = ref(readQueryString(route.query, 'q'))
const appliedKeyword = ref(readQueryString(route.query, 'q'))
const selectedKey = ref(readQueryString(route.query, 'key'))

const rows = computed<SecurityRow[]>(() => (center.value === null ? [] : buildSecurityRows(center.value)))
const visible = computed(() => filterSecurityRows(rows.value, appliedKeyword.value))
const summary = computed(() => summarizeSecurity(rows.value))
const selectedRow = computed<SecurityRow | null>(() => rows.value.find((row) => row.key === selectedKey.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => center.value?.scope.truncated ?? false)

async function applySearch(): Promise<void> {
  appliedKeyword.value = keyword.value
  await replaceQueryState(router, route, { q: keyword.value })
}

function selectRow(row: SecurityRow): void {
  selectedKey.value = row.key
}

onMounted(async () => {
  await load()
  if (selectedKey.value === '' && rows.value.length > 0) selectedKey.value = rows.value[0]?.key ?? ''
})

watch(selectedKey, async (value) => {
  await replaceQueryState(router, route, { key: value === '' ? undefined : value })
})

watch(
  () => route.query.key,
  () => {
    selectedKey.value = readQueryString(route.query, 'key')
  },
)

watch(visible, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.key === selectedKey.value)) return
  selectedKey.value = value[0]?.key ?? ''
})
</script>

<template>
  <section>
    <SettingsTabs />

    <div class="head">
      <div>
        <div class="eyebrow">設定 / SCREEN 39</div>
        <h1>系統與安全設定</h1>
        <p class="muted">
          專屬任務畫面設計｜角色與權限、金鑰與 Token、稽核與留存：每一列都附可追溯來源；後端沒有對應端點的設定項一律「未取得」，不代填任何政策內容。
        </p>
      </div>
      <div class="actions">
        <label class="field">
          <span class="field-label">搜尋設定項</span>
          <input v-model="keyword" placeholder="設定名稱、值或來源端點" @keyup.enter="applySearch" />
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
          <div class="eyebrow">設定項</div>
          <div class="metric-value">{{ summary.total }}</div>
          <p>本頁列出的設定項總數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已揭露</div>
          <div class="metric-value" :class="summary.disclosed > 0 ? 'good' : 'warn'">{{ summary.disclosed }}</div>
          <p>有後端契約或前端已知機制可支撐的設定項。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">未取得</div>
          <div class="metric-value" :class="summary.unknown > 0 ? 'warn' : ''">{{ summary.unknown }}</div>
          <p>後端沒有對應端點的設定項；不以 0 或預設值代替。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">服務就緒狀態</div>
          <div class="metric-value" :class="center.readiness === 'ready' ? 'good' : 'bad'">
            {{ center.readiness === 'ready' ? '已就緒' : '異常' }}
          </div>
          <p>來自 <span class="mono">GET /health/ready/</span> 的權威狀態。</p>
        </section>
      </div>

      <div class="layout security-grid">
        <section class="card">
          <h3>設定項與來源</h3>
          <p class="muted">
            只涵蓋本頁可追溯的來源。
            <template v-if="truncated">後端仍有未讀取頁面，讀取範圍以此為限。</template>
          </p>
          <p v-if="visible.length === 0" class="muted">目前沒有符合條件的設定項。</p>
          <table v-else>
            <thead>
              <tr>
                <th>設定項</th>
                <th>值</th>
                <th>來源</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visible"
                :key="row.key"
                :class="{ active: row.key === selectedKey }"
                @click="selectRow(row)"
              >
                <td>{{ row.label }}</td>
                <td :class="row.value === SETTINGS_UNKNOWN ? 'muted' : ''">{{ row.value }}</td>
                <td class="mono cell-source">{{ row.source }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>設定項詳情</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一項設定。</p>
          <template v-else>
            <div class="row compact">
              <span>設定項</span>
              <span>{{ selectedRow.label }}</span>
            </div>
            <div class="row compact">
              <span>目前值</span>
              <span :class="selectedRow.value === SETTINGS_UNKNOWN ? 'muted' : ''">{{ selectedRow.value }}</span>
            </div>
            <div class="row compact">
              <span>可追溯來源</span>
              <span class="mono record-value">{{ selectedRow.source }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag" :class="selectedRow.tone === 'good' ? 'good' : selectedRow.tone === 'bad' ? 'bad' : ''">
                {{ selectedRow.value === SETTINGS_UNKNOWN ? '未取得' : '可讀' }}
              </span>
            </div>
            <p v-if="selectedRow.value === SETTINGS_UNKNOWN" class="muted" style="margin-top: 10px;">
              此設定項後端尚未提供端點，因此顯示「未取得」；本頁不代填任何預設政策。
            </p>
          </template>
        </section>
      </div>

      <section class="card note-card">
        <h3>目前邊界</h3>
        <p>
          後端沒有角色權限矩陣、存取金鑰、多因素驗證、密碼政策、稽核留存或資料加密端點；本頁只呈現服務就緒狀態、工作階段機制、已讀取租戶識別與讀取範圍，其餘設定項一律「未取得」。
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

.security-grid {
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

.cell-source {
  max-width: 240px;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .security-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
