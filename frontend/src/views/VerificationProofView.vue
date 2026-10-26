<script setup lang="ts">
/**
 * 形式化證明（SSOT SCREEN 25）：命題、前提、Lean 目標及證明狀態。
 *
 * 證明產物只來自證據包的 proof_artifact_ids，並投影已讀取到的產物 metadata 與 validation run 的
 * 證明等級（P0／P1／P2）。後端沒有命題、前提與 Lean 目標端點，這些欄位一律固定顯示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import VerificationTabs from '../components/VerificationTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useVerificationCenter } from '../lib/useVerificationCenter'
import { VERIFICATION_UNKNOWN } from '../lib/verificationCenter'
import {
  ARTIFACT_ACCESS_LABELS,
  ARTIFACT_STATUS_LABELS,
  PROOF_PREMISE_UNKNOWN,
  PROOF_STATEMENT_UNKNOWN,
  buildProofRows,
  describeEmpiricalLevels,
  describeProofLevels,
  summarizeProof,
  type ProofArtifactRow,
} from '../lib/verificationProof'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useVerificationCenter()

const selectedId = ref(readQueryString(route.query, 'artifact'))

const rows = computed<ProofArtifactRow[]>(() => (center.value === null ? [] : buildProofRows(center.value)))
const summary = computed(() => summarizeProof(rows.value))
const selectedRow = computed<ProofArtifactRow | null>(
  () => rows.value.find((row) => row.artifactId === selectedId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))

function statusTone(row: ProofArtifactRow): string {
  if (row.artifact === null) return 'warn'
  if (row.artifact.status === 'AVAILABLE') return 'good'
  if (row.artifact.status === 'QUARANTINED') return 'warn'
  return 'bad'
}

function statusLabel(row: ProofArtifactRow): string {
  return row.artifact === null ? VERIFICATION_UNKNOWN : ARTIFACT_STATUS_LABELS[row.artifact.status]
}

function selectRow(row: ProofArtifactRow): void {
  selectedId.value = row.artifactId
}

onMounted(async () => {
  await load()
  if (selectedId.value === '' && rows.value.length > 0) selectedId.value = rows.value[0]?.artifactId ?? ''
})

watch(selectedId, async (value) => {
  await replaceQueryState(router, route, { artifact: value === '' ? undefined : value })
})

watch(
  () => route.query.artifact,
  () => {
    selectedId.value = readQueryString(route.query, 'artifact')
  },
)

watch(rows, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.artifactId === selectedId.value)) return
  selectedId.value = value[0]?.artifactId ?? ''
})
</script>

<template>
  <section>
    <VerificationTabs />

    <div class="head">
      <div>
        <div class="eyebrow">驗證 / SCREEN 25</div>
        <h1>形式化證明</h1>
        <p class="muted">專屬任務畫面設計｜命題、前提、Lean 目標及證明狀態：只呈現證據包引用的證明產物與後端已回報的 P0／P1／P2 等級，不推測證明語意。</p>
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
          <div class="eyebrow">證明產物</div>
          <div class="metric-value" :class="summary.total > 0 ? 'good' : 'warn'">{{ summary.total }}</div>
          <p>證據包 proof_artifact_ids 實際引用到的產物數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">可用</div>
          <div class="metric-value" :class="summary.available > 0 ? 'good' : 'warn'">{{ summary.available }}</div>
          <p>產物狀態為 AVAILABLE 的數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已隔離</div>
          <div class="metric-value" :class="summary.quarantined > 0 ? 'warn' : 'good'">{{ summary.quarantined }}</div>
          <p>產物狀態為 QUARANTINED 的數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">未取得 metadata</div>
          <div class="metric-value" :class="summary.unreadable > 0 ? 'warn' : 'good'">{{ summary.unreadable }}</div>
          <p>被引用但無法讀取 metadata 的產物數。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">命題與 Lean 目標</div>
          <p class="unknown-value">{{ PROOF_STATEMENT_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">證明前提與定義</div>
          <p class="unknown-value">{{ PROOF_PREMISE_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout proof-grid">
        <section class="card">
          <h3>證明產物清單</h3>
          <p class="muted">只涵蓋已讀取到的研究版本與其證據包；未被任何證據包引用的產物不會出現在此。</p>
          <p v-if="rows.length === 0" class="muted">
            目前沒有可讀取的證明產物。證據包的 proof_artifact_ids 為空，或最近版本尚未產生證據包。
          </p>
          <table v-else>
            <thead>
              <tr>
                <th>產物</th>
                <th>研究</th>
                <th>狀態</th>
                <th>證明等級</th>
                <th>實證等級</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="`${row.versionId}-${row.artifactId}`"
                :class="{ active: row.artifactId === selectedId }"
                @click="selectRow(row)"
              >
                <td class="mono">{{ row.artifactId }}</td>
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId }}</div>
                </td>
                <td>
                  <span class="tag" :class="statusTone(row)">{{ statusLabel(row) }}</span>
                </td>
                <td>{{ describeProofLevels(row.proofLevels) }}</td>
                <td>{{ describeEmpiricalLevels(row.empiricalLevels) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>選定證明產物</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一個證明產物。</p>
          <template v-else>
            <div class="row compact">
              <span>產物識別碼</span>
              <span class="mono record-value">{{ selectedRow.artifactId }}</span>
            </div>
            <div class="row compact">
              <span>所屬研究</span>
              <span>{{ selectedRow.researchName }}</span>
            </div>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono record-value">{{ selectedRow.versionId }}</span>
            </div>
            <div class="row compact">
              <span>證明等級</span>
              <span class="tag">{{ describeProofLevels(selectedRow.proofLevels) }}</span>
            </div>
            <div class="row compact">
              <span>實證等級</span>
              <span class="tag">{{ describeEmpiricalLevels(selectedRow.empiricalLevels) }}</span>
            </div>

            <h3 style="margin-top: 18px;">產物 metadata</h3>
            <template v-if="selectedRow.artifact === null">
              <p class="muted">此產物被證據包引用，但目前無法讀取 metadata（{{ VERIFICATION_UNKNOWN }}）。</p>
            </template>
            <template v-else>
              <div class="row compact">
                <span>狀態</span>
                <span class="tag" :class="statusTone(selectedRow)">{{ ARTIFACT_STATUS_LABELS[selectedRow.artifact.status] }}</span>
              </div>
              <div class="row compact">
                <span>存取等級</span>
                <span class="tag">{{ ARTIFACT_ACCESS_LABELS[selectedRow.artifact.access_class] }}</span>
              </div>
              <div class="row compact">
                <span>媒體型別</span>
                <span>{{ selectedRow.artifact.media_type }}</span>
              </div>
              <div class="row compact">
                <span>大小（位元組）</span>
                <span class="tag">{{ selectedRow.artifact.size_bytes }}</span>
              </div>
              <div class="row compact">
                <span>sha256</span>
                <span class="mono record-value">{{ selectedRow.artifact.sha256 }}</span>
              </div>
              <div class="row compact">
                <span>建立時間</span>
                <span class="mono record-value">{{ selectedRow.artifact.created_at }}</span>
              </div>
              <div class="actions" style="margin-top: 14px;">
                <RouterLink
                  :to="{ name: 'artifact', params: { id: selectedRow.artifactId }, query: withBackRef(route.fullPath) }"
                >
                  <button type="button">查看產物詳情</button>
                </RouterLink>
              </div>
            </template>

            <div class="note" style="margin-top: 12px;">
              命題、前提與 Lean 目標需後端端點；P0／P1／P2 為後端已回報的證明等級，本頁不推測證明的語意內容。
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
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 16px;
}

.unknown-card {
  border-style: dashed;
}

.unknown-value {
  margin: 8px 0 0;
  color: #9fb3c8;
}

.proof-grid {
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

  .proof-grid {
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
