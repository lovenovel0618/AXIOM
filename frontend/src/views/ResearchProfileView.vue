<script setup lang="ts">
/**
 * 研究詳情（SSOT SCREEN 08）：目標、執行快照、成果與版本。
 *
 * 後端沒有研究層級的目標或成果摘要端點，本頁只投影研究版本已固定的語意概況（目標量、
 * 輸入量、單位確認、時間序列、量測解析度與分組欄位）、預算與用量、封存最終測試設定、
 * 研究域端點、品質報告與證據包，以及宣告與已評估的凍結提交計數；未揭露欄位一律「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ResearchTabs from '../components/ResearchTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useResearchPanel } from '../lib/useResearchPanel'
import {
  RESEARCH_UNKNOWN,
  buildProfileGoals,
  buildResearchProfile,
  summarizeResearchProfile,
  type ProfileSnapshot,
} from '../lib/researchPanels'

const route = useRoute()
const router = useRouter()
const { panel, loading, error, load } = useResearchPanel()

const researchId = computed<string>(() => {
  const raw = route.params.id
  return typeof raw === 'string' ? raw : (raw?.[0] ?? '')
})

const selectedVersionId = ref(readQueryString(route.query, 'version'))

const profile = computed(() => (panel.value === null ? null : buildResearchProfile(panel.value)))
const snapshots = computed<ProfileSnapshot[]>(() => profile.value?.snapshots ?? [])
const summary = computed(() =>
  profile.value === null
    ? { versions: 0, ready: 0, declaredSubmissions: 0, evaluatedSubmissions: 0 }
    : summarizeResearchProfile(profile.value),
)
const selectedVersion = computed(() => panel.value?.versions.find((item) => item.id === selectedVersionId.value) ?? null)
const goals = computed(() => buildProfileGoals(selectedVersion.value))
const selectedSnapshot = computed<ProfileSnapshot | null>(
  () => snapshots.value.find((item) => item.versionId === selectedVersionId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))
const truncated = computed(() => panel.value?.scope.truncated ?? false)
const workbenchQuery = computed<Record<string, string>>(() =>
  withBackRef(route.fullPath, { version: selectedVersion.value?.id }),
)

function selectVersion(snapshot: ProfileSnapshot): void {
  selectedVersionId.value = snapshot.versionId
}

async function reload(): Promise<void> {
  await load(researchId.value)
}

onMounted(async () => {
  await reload()
  if (selectedVersionId.value === '' && snapshots.value.length > 0) {
    selectedVersionId.value = snapshots.value[0]?.versionId ?? ''
  }
})

watch(selectedVersionId, async (value) => {
  await replaceQueryState(router, route, { version: value === '' ? undefined : value })
})

watch(
  () => route.query.version,
  () => {
    selectedVersionId.value = readQueryString(route.query, 'version')
  },
)

watch(
  () => route.params.id,
  async () => {
    await reload()
  },
)

watch(snapshots, (value) => {
  if (value.length === 0) return
  if (value.some((snapshot) => snapshot.versionId === selectedVersionId.value)) return
  selectedVersionId.value = value[0]?.versionId ?? ''
})
</script>

<template>
  <section>
    <ResearchTabs :research-id="researchId" />

    <div class="head">
      <div>
        <div class="eyebrow">研究 / 第 8 頁</div>
        <h1>研究詳情</h1>
        <p class="muted">
          專屬任務畫面設計｜目標、執行快照、成果與版本：只投影研究版本已固定的欄位；研究層級的目標敘述、成果摘要與治理資訊後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="reload">重新載入</button>
        <RouterLink v-if="researchId !== ''" :to="{ name: 'research-workbench', params: { id: researchId }, query: workbenchQuery }">
          <button type="button" class="primary">開啟研究工作台</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && panel === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="panel !== null && profile !== null">
      <p v-if="panel.research === null" class="note">
        查無此研究，或目前身分沒有讀取權限；本頁不顯示任何推測內容。
        <RouterLink :to="{ name: 'research-list' }">返回研究清單</RouterLink>
      </p>

      <template v-else>
        <div class="layout metric-grid">
          <section class="card metric-card">
            <div class="eyebrow">研究版本</div>
            <div class="metric-value">{{ summary.versions }}</div>
            <p>本頁實際讀取到、屬於此研究的版本數。<template v-if="truncated">後端仍有未讀取頁面，統計範圍以此為限。</template></p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">已就緒版本</div>
            <div class="metric-value" :class="summary.ready > 0 ? 'good' : 'warn'">{{ summary.ready }}</div>
            <p>狀態為「就緒」的版本數。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">宣告凍結提交</div>
            <div class="metric-value">{{ summary.declaredSubmissions }}</div>
            <p>所有版本 <span class="mono">frozen_submission_ids</span> 的合計。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">已評估提交</div>
            <div class="metric-value" :class="summary.evaluatedSubmissions > 0 ? 'good' : 'warn'">
              {{ summary.evaluatedSubmissions }}
            </div>
            <p>已讀取到最終評估且狀態為「已評估」的提交數。</p>
          </section>
        </div>

        <div class="layout profile-grid">
          <section class="card">
            <h3>研究目標與語意概況</h3>
            <p class="muted">
              取自選定版本的語意概況；未選定版本時每一項都以「未取得」呈現。
            </p>
            <div v-for="goal in goals" :key="goal.label" class="row compact">
              <span>{{ goal.label }}</span>
              <span class="mono record-value">{{ goal.value }}</span>
            </div>
            <div class="note" style="margin-top: 12px;">
              後端沒有研究層級的研究問題、假說敘述或治理資訊端點，因此本區只呈現版本已固定的語意概況。
            </div>
          </section>

          <section class="card">
            <h3>成果與版本統計</h3>
            <div class="row compact">
              <span>宣告凍結提交</span>
              <span class="tag">{{ profile.outcomes.declaredSubmissions }}</span>
            </div>
            <div class="row compact">
              <span>已評估提交</span>
              <span class="tag" :class="profile.outcomes.evaluatedSubmissions > 0 ? 'good' : ''">
                {{ profile.outcomes.evaluatedSubmissions }}
              </span>
            </div>
            <div class="row compact">
              <span>評估失敗提交</span>
              <span class="tag" :class="profile.outcomes.failedSubmissions > 0 ? 'bad' : ''">
                {{ profile.outcomes.failedSubmissions }}
              </span>
            </div>
            <div class="row compact">
              <span>未取得評估提交</span>
              <span class="tag" :class="profile.outcomes.unknownSubmissions > 0 ? 'warn' : ''">
                {{ profile.outcomes.unknownSubmissions }}
              </span>
            </div>
            <div class="row compact">
              <span>封存最終測試版本</span>
              <span>{{ profile.outcomes.sealedTestCount }}</span>
            </div>
            <div class="row compact">
              <span>已有品質報告的版本</span>
              <span>{{ profile.outcomes.qualityReportCount }}</span>
            </div>
            <div class="row compact">
              <span>證據包合計</span>
              <span>{{ profile.outcomes.evidenceBundleCount }}</span>
            </div>
            <div class="row compact">
              <span>候選產生 / 接受</span>
              <span>{{ profile.outcomes.candidatesGenerated }} / {{ profile.outcomes.candidatesAccepted }}</span>
            </div>
            <p class="muted">
              未取得評估的提交數以「宣告數 − 已評估 − 失敗」計算；讀不到的最終評估不計為 0，而以「未取得」呈現。
            </p>
          </section>
        </div>

        <div class="layout profile-grid">
          <section class="card">
            <h3>執行快照</h3>
            <p class="muted">只涵蓋本頁實際讀取到的版本；每一列都對應一次不可變的版本宣告。</p>
            <p v-if="snapshots.length === 0" class="muted">此研究目前沒有可讀取的版本。</p>
            <table v-else>
              <thead>
                <tr>
                  <th>版本</th>
                  <th>狀態</th>
                  <th>目的</th>
                  <th>控制版本</th>
                  <th>研究域</th>
                  <th>建立時間</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="snapshot in snapshots"
                  :key="snapshot.versionId"
                  :class="{ active: snapshot.versionId === selectedVersionId }"
                  @click="selectVersion(snapshot)"
                >
                  <td class="mono record-value">{{ snapshot.versionId }}</td>
                  <td>
                    <span class="tag" :class="snapshot.tone === 'OK' ? 'good' : snapshot.tone === 'FAILED' ? 'bad' : snapshot.tone === 'RUNNING' || snapshot.tone === 'PENDING' ? 'warn' : ''">
                      {{ snapshot.statusLabel }}
                    </span>
                  </td>
                  <td>{{ snapshot.purposeLabel }}</td>
                  <td>{{ snapshot.revision }}</td>
                  <td>{{ snapshot.domainCount }}</td>
                  <td class="mono">{{ snapshot.createdAt }}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section class="card">
            <h3>選定版本的快照明細</h3>
            <p v-if="selectedSnapshot === null" class="muted">請從左側執行快照選擇一個版本。</p>
            <template v-else>
              <div class="row compact">
                <span>研究版本</span>
                <span class="mono record-value">{{ selectedSnapshot.versionId }}</span>
              </div>
              <div class="row compact">
                <span>狀態</span>
                <span class="tag">{{ selectedSnapshot.statusLabel }}（{{ selectedSnapshot.status }}）</span>
              </div>
              <div class="row compact">
                <span>研究目的</span>
                <span>{{ selectedSnapshot.purposeLabel }}</span>
              </div>
              <div class="row compact">
                <span>控制版本</span>
                <span>{{ selectedSnapshot.revision }}</span>
              </div>

              <h3 style="margin-top: 18px;">預算與用量</h3>
              <div class="row compact">
                <span>CPU 秒（上限 / 已用）</span>
                <span>{{ selectedSnapshot.budgetCpuSeconds }} / {{ selectedSnapshot.usedCpuSeconds }}</span>
              </div>
              <div class="row compact">
                <span>GPU 秒（上限 / 已用）</span>
                <span>{{ selectedSnapshot.budgetGpuSeconds }} / {{ selectedSnapshot.usedGpuSeconds }}</span>
              </div>
              <div class="row compact">
                <span>Token（上限 / 已用）</span>
                <span>{{ selectedSnapshot.budgetTokens }} / {{ selectedSnapshot.usedTokens }}</span>
              </div>
              <div class="row compact">
                <span>候選產生 / 接受</span>
                <span>{{ selectedSnapshot.candidatesGenerated }} / {{ selectedSnapshot.candidatesAccepted }}</span>
              </div>

              <h3 style="margin-top: 18px;">證據與封存</h3>
              <div class="row compact">
                <span>封存最終測試</span>
                <span class="tag" :class="selectedSnapshot.sealedFinalTest ? 'good' : 'warn'">
                  {{ selectedSnapshot.sealedFinalTest ? '已封存' : '未封存' }}
                </span>
              </div>
              <div class="row compact">
                <span>研究域端點</span>
                <span>{{ selectedSnapshot.domainCount }}</span>
              </div>
              <div class="row compact">
                <span>品質報告</span>
                <span class="mono record-value">{{ selectedSnapshot.qualityReportId ?? RESEARCH_UNKNOWN }}</span>
              </div>
              <div class="row compact">
                <span>證據包</span>
                <span>{{ selectedSnapshot.evidenceBundleCount }}</span>
              </div>
              <div class="row compact">
                <span>建立時間</span>
                <span class="mono record-value">{{ selectedSnapshot.createdAt }}</span>
              </div>
            </template>
          </section>
        </div>

        <section class="card note-card">
          <h3>目前邊界</h3>
          <p>
            後端沒有研究層級的研究目標、成果摘要、分支圖、事件重播或治理端點，因此本頁只投影研究、研究版本、任務與最終評估已揭露的欄位：目標區塊取自版本語意概況，成果統計只涵蓋本頁實際讀取到的版本與提交；研究問題敘述、成功判定、評分結論與建議一律「未取得」，不以推測補值。
          </p>
        </section>
      </template>
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

.profile-grid {
  grid-template-columns: 1fr 1fr;
  margin-bottom: 16px;
}

.note-card {
  margin-top: 16px;
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
  .profile-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .metric-grid,
  .profile-grid {
    grid-template-columns: 1fr;
  }
}
</style>
