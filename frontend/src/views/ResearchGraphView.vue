<script setup lang="ts">
/**
 * 研究分支圖（SSOT SCREEN 09）：研究依賴圖、分支與重試標記。
 *
 * 圖只由已讀取到的研究、研究版本與任務，以及契約明載的歸屬關係（研究 → 研究版本 → 任務）建立；
 * 沒有讀到的節點不會被補上，語意依賴不推測。同一版本同型任務依建立時間標示重試序號。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ResearchTabs from '../components/ResearchTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useResearchPanel } from '../lib/useResearchPanel'
import {
  RESEARCH_UNKNOWN,
  buildResearchGraph,
  summarizeResearchGraph,
  type ResearchGraph,
  type ResearchNode,
} from '../lib/researchPanels'

const route = useRoute()
const router = useRouter()
const { panel, loading, error, load } = useResearchPanel()

const researchId = computed<string>(() => {
  const raw = route.params.id
  return typeof raw === 'string' ? raw : (raw?.[0] ?? '')
})

const nodeId = ref(readQueryString(route.query, 'node'))

const graph = computed<ResearchGraph | null>(() => (panel.value === null ? null : buildResearchGraph(panel.value)))
const nodes = computed<ResearchNode[]>(() => graph.value?.nodes ?? [])
const summary = computed(() =>
  panel.value === null
    ? { versions: 0, runs: 0, branches: 0, retries: 0, failed: 0 }
    : summarizeResearchGraph(panel.value),
)
const selectedNode = computed<ResearchNode | null>(() => nodes.value.find((node) => node.id === nodeId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))
const workbenchQuery = computed<Record<string, string>>(() =>
  withBackRef(route.fullPath, {
    version: selectedNode.value?.versionId ?? undefined,
    node: selectedNode.value?.id,
  }),
)

const COLUMNS: Array<{ column: number; label: string; hint: string }> = [
  { column: 0, label: '研究', hint: '研究容器本身' },
  { column: 1, label: '研究版本', hint: '不可變的版本宣告' },
  { column: 2, label: '任務', hint: '在版本上執行的任務' },
]

const columnNodes = computed<ResearchNode[][]>(() => COLUMNS.map((item) => nodes.value.filter((node) => node.column === item.column)))

function nodeLabel(id: string): string {
  const node = nodes.value.find((item) => item.id === id)
  if (node === undefined) return id
  return node.kind === 'RUN' ? `任務：${node.title}` : node.kind === 'VERSION' ? `研究版本：${id}` : '研究'
}

function selectNode(node: ResearchNode): void {
  nodeId.value = node.id
}

async function reload(): Promise<void> {
  await load(researchId.value)
}

onMounted(async () => {
  await reload()
  if (nodeId.value === '' && nodes.value.length > 0) nodeId.value = nodes.value[0]?.id ?? ''
})

watch(nodeId, async (value) => {
  await replaceQueryState(router, route, { node: value === '' ? undefined : value })
})

watch(
  () => route.query.node,
  () => {
    nodeId.value = readQueryString(route.query, 'node')
  },
)

watch(
  () => route.params.id,
  async () => {
    await reload()
  },
)

watch(nodes, (value) => {
  if (value.length === 0) return
  if (value.some((node) => node.id === nodeId.value)) return
  nodeId.value = value[0]?.id ?? ''
})
</script>

<template>
  <section>
    <ResearchTabs :research-id="researchId" />

    <div class="head">
      <div>
        <div class="eyebrow">研究 / 第 9 頁</div>
        <h1>研究分支圖</h1>
        <p class="muted">
          專屬任務畫面設計｜研究依賴圖、分支與重試標記：只畫出契約明載的歸屬關係，不推測語意依賴；未讀取的節點不會被補造。
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
    <template v-else-if="panel !== null && graph !== null">
      <p v-if="panel.research === null" class="note">
        查無此研究，或目前身分沒有讀取權限；本頁不顯示任何推測內容。
        <RouterLink :to="{ name: 'research-list' }">返回研究清單</RouterLink>
      </p>

      <template v-else>
        <div class="layout metric-grid">
          <section class="card metric-card">
            <div class="eyebrow">研究版本</div>
            <div class="metric-value">{{ summary.versions }}</div>
            <p>已讀取到的版本節點數。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">任務節點</div>
            <div class="metric-value">{{ summary.runs }}</div>
            <p>已讀取到的任務節點數。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">多任務分支</div>
            <div class="metric-value" :class="summary.branches > 0 ? 'warn' : ''">{{ summary.branches }}</div>
            <p>擁有兩個以上任務節點的版本數，代表一次分出多條執行分支。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">重試任務</div>
            <div class="metric-value" :class="summary.retries > 0 ? 'warn' : 'good'">{{ summary.retries }}</div>
            <p>同版本同型任務中出現序號大於 1 的任務數。</p>
          </section>
          <section class="card metric-card">
            <div class="eyebrow">失敗或取消</div>
            <div class="metric-value" :class="summary.failed > 0 ? 'bad' : 'good'">{{ summary.failed }}</div>
            <p>狀態為「失敗」或「已取消」的任務節點數。</p>
          </section>
        </div>

        <section class="card" style="margin-bottom: 16px;">
          <h3>研究依賴圖</h3>
          <p class="muted">
            由左至右為研究 → 研究版本 → 任務；同一欄的多個節點代表並行產物或分支。邊只表達契約明載的歸屬，不代表語意上的因果依賴。
          </p>
          <div class="graph-columns">
            <div v-for="(column, index) in COLUMNS" :key="column.column" class="graph-column">
              <div class="column-head">
                <strong>{{ column.label }}</strong>
                <span class="muted">{{ column.hint }}</span>
              </div>
              <p v-if="(columnNodes[index] ?? []).length === 0" class="muted">此欄沒有可讀取的節點。</p>
              <button
                v-for="node in columnNodes[index] ?? []"
                :key="node.id"
                type="button"
                class="module-link selectable"
                :class="[`tone-${node.tone}`, { active: node.id === nodeId }]"
                @click="selectNode(node)"
              >
                <div>
                  <strong>{{ node.title }}</strong>
                  <div class="muted">{{ node.subtitle }}</div>
                  <div class="muted mono">{{ node.id }}</div>
                </div>
                <div class="node-side">
                  <span class="tag">{{ node.badge }}</span>
                  <span v-if="node.retryIndex > 1" class="tag warn">重試 {{ node.retryIndex }}</span>
                </div>
              </button>
            </div>
          </div>
        </section>

        <div class="layout graph-grid">
          <section class="card">
            <h3>依賴關係邊</h3>
            <p v-if="graph.edges.length === 0" class="muted">目前沒有已揭露的依賴關係。</p>
            <table v-else>
              <thead>
                <tr>
                  <th>來源節點</th>
                  <th>關係</th>
                  <th>目標節點</th>
                  <th>分支</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="edge in graph.edges" :key="`${edge.from}->${edge.to}`">
                  <td>{{ nodeLabel(edge.from) }}</td>
                  <td class="muted">歸屬</td>
                  <td>{{ nodeLabel(edge.to) }}</td>
                  <td>
                    <span class="tag" :class="edge.branch ? 'warn' : ''">{{ edge.branch ? '分支' : '單一' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </section>

          <section class="card">
            <h3>選定節點紀錄</h3>
            <p v-if="selectedNode === null" class="muted">請從上方依賴圖選擇一個節點。</p>
            <template v-else>
              <div class="row compact">
                <span>節點</span>
                <span>{{ selectedNode.title }}</span>
              </div>
              <div class="row compact">
                <span>節點識別碼</span>
                <span class="mono record-value">{{ selectedNode.id }}</span>
              </div>
              <div class="row compact">
                <span>狀態</span>
                <span class="tag">{{ selectedNode.badge }}</span>
              </div>
              <div v-for="record in selectedNode.records" :key="record.label" class="row compact">
                <span>{{ record.label }}</span>
                <span class="mono record-value">{{ record.value }}</span>
              </div>

              <div class="actions" style="margin-top: 14px;">
                <RouterLink v-if="selectedNode.runId !== null" :to="{ name: 'run', params: { id: selectedNode.runId } }">
                  <button type="button">開啟任務詳情</button>
                </RouterLink>
                <RouterLink
                  v-if="selectedNode.versionId !== null"
                  :to="{
                    name: 'research-timeline',
                    params: { id: researchId },
                    query: withBackRef(route.fullPath, { run: selectedNode.runId ?? undefined }),
                  }"
                >
                  <button type="button">在研究任務紀錄中檢視</button>
                </RouterLink>
              </div>
            </template>
          </section>
        </div>

        <section class="card note-card">
          <h3>目前邊界</h3>
          <p>
            後端沒有研究分支圖或依賴查詢端點，因此本圖只由研究、研究版本與任務三層實際讀取到的實體推導，邊僅代表契約明載的歸屬（研究 → 版本 → 任務）；分支恢復流程、撤回狀態與依賴影響分析一律「未取得」。讀取範圍以外的節點不補造，重試序號只依「同版本同型任務」的建立時間計算。
          </p>
        </section>
      </template>
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
  font-size: 28px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.graph-columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.graph-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.column-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-left: 3px solid #3673c7;
  padding-left: 10px;
}

.module-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
}

.selectable {
  width: 100%;
  text-align: left;
}

.selectable.active {
  border-color: #3673c7;
  background: #132842;
}

.tone-OK {
  border-color: #2f7d68;
}

.tone-FAILED {
  border-color: #7c3341;
}

.tone-RUNNING,
.tone-PENDING {
  border-color: #7a6330;
}

.node-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  white-space: nowrap;
}

.graph-grid {
  grid-template-columns: 1.1fr 1fr;
  margin-bottom: 16px;
}

.note-card {
  margin-top: 16px;
}

.compact {
  padding: 8px 0;
}

.record-value {
  max-width: 58%;
  text-align: right;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .graph-columns,
  .graph-grid {
    grid-template-columns: 1fr;
  }
}
</style>
