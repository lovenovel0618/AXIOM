<script setup lang="ts">
/**
 * 研究推演（SSOT SCREEN 21）：假設推導、依賴前提及回溯。
 *
 * 流程圖沿用 `buildFlow` 由研究版本的真實資料推導；依賴前提與後續推演只沿實際存在的邊走訪，
 * 因此「沒有邊」就是「後端沒有揭露依賴」，不以節點順序或命名回推關係。
 * 節點已撤回或依賴版本變動時只標記受影響範圍，不覆寫既有紀錄。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DiscoveryTabs from '../components/DiscoveryTabs.vue'
import ResearchFlow from '../components/ResearchFlow.vue'
import { buildDerivationTrace, findBranchSources, summarizeDerivationKinds } from '../lib/derivationGraph'
import { FLOW_KIND_LABELS } from '../lib/flow'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useDerivationGraph } from '../lib/useDerivationGraph'

const route = useRoute()
const router = useRouter()
const {
  researches,
  versions,
  version,
  graph,
  loading,
  graphLoading,
  error,
  loadIndex,
  selectResearch,
  loadGraph,
} = useDerivationGraph()

const researchId = ref(readQueryString(route.query, 'research'))
const versionId = ref(readQueryString(route.query, 'version'))
const nodeId = ref(readQueryString(route.query, 'node'))

const backRef = computed(() => readBackRef(route.query))
const kindCounts = computed(() => (graph.value === null ? [] : summarizeDerivationKinds(graph.value)))
const branchSources = computed(() => (graph.value === null ? [] : findBranchSources(graph.value)))
const trace = computed(() => (graph.value === null || nodeId.value === '' ? null : buildDerivationTrace(graph.value, nodeId.value)))
const highlightIds = computed(() =>
  trace.value === null ? [] : [...trace.value.upstream, ...trace.value.downstream].map((node) => node.id),
)

function nodeTitle(id: string): string {
  const node = graph.value?.nodes.find((row) => row.id === id)
  return node === undefined ? id : `${FLOW_KIND_LABELS[node.kind]}：${node.title}`
}

function selectNode(id: string): void {
  nodeId.value = id
}

async function onResearchChange(value: string): Promise<void> {
  versionId.value = ''
  nodeId.value = ''
  await selectResearch(value)
}

onMounted(async () => {
  await loadIndex()
  if (researchId.value === '') researchId.value = researches.value[0]?.id ?? ''
  if (researchId.value !== '') {
    await selectResearch(researchId.value)
    if (versionId.value !== '' && !versions.value.some((row) => row.id === versionId.value)) versionId.value = ''
    if (versionId.value === '') versionId.value = versions.value[0]?.id ?? ''
    if (versionId.value !== '') await loadGraph(versionId.value)
  }
})

watch(researchId, async (value) => {
  await replaceQueryState(router, route, {
    research: value === '' ? undefined : value,
    version: undefined,
    node: undefined,
  })
  await onResearchChange(value)
})

watch(versionId, async (value) => {
  await replaceQueryState(router, route, { version: value === '' ? undefined : value, node: undefined })
  nodeId.value = ''
  await loadGraph(value)
})

watch(nodeId, async (value) => {
  await replaceQueryState(router, route, { node: value === '' ? undefined : value })
})

watch(
  graph,
  (value) => {
    if (value === null) return
    if (nodeId.value === '' || !value.nodes.some((node) => node.id === nodeId.value)) {
      nodeId.value = value.nodes[0]?.id ?? ''
    }
  },
  { immediate: false },
)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">發現 / SCREEN 21</div>
        <h1>研究推演</h1>
        <p class="muted">假設推導、依賴前提及回溯 · 專屬任務畫面設計</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" :disabled="researchId === '' || versionId === ''" @click="loadGraph(versionId)">重新載入</button>
        <RouterLink :to="{ name: 'discoveries' }">
          <button type="button" class="primary">前往候選公式庫</button>
        </RouterLink>
      </div>
    </div>

    <DiscoveryTabs />

    <p v-if="loading && researches.length === 0" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else>
      <section class="card selector">
        <div class="formgrid">
          <div class="field">
            <label for="derivation-research">研究</label>
            <select id="derivation-research" :value="researchId" @change="researchId = ($event.target as HTMLSelectElement).value">
              <option value="">請選擇研究</option>
              <option v-for="research in researches" :key="research.id" :value="research.id">{{ research.name }}</option>
            </select>
          </div>
          <div class="field">
            <label for="derivation-version">研究版本</label>
            <select id="derivation-version" v-model="versionId" :disabled="versions.length === 0">
              <option value="">請選擇版本</option>
              <option v-for="row in versions" :key="row.id" :value="row.id">{{ row.purpose }} / {{ row.status }} / {{ row.id }}</option>
            </select>
          </div>
        </div>
        <p v-if="researches.length === 0" class="muted">目前沒有可讀取的研究。請先建立研究並執行資料剖析。</p>
        <p v-else-if="researchId !== '' && versions.length === 0" class="muted">此研究尚無版本；建立研究版本後才會產生推演圖。</p>
      </section>

      <p v-if="graphLoading" class="muted">讀取節點與依賴 DAG 中…</p>
      <template v-else-if="graph !== null">
        <div class="layout deriv-grid">
          <section class="card">
            <h3>節點與依賴 DAG</h3>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono record-value">{{ version?.id ?? '未取得' }}</span>
            </div>
            <div class="row compact">
              <span>節點數 / 邊數</span>
              <span class="tag">{{ graph.nodes.length }} / {{ graph.edges.length }}</span>
            </div>
            <div class="row compact">
              <span>分支來源</span>
              <span class="tag" :class="branchSources.length > 0 ? 'good' : 'warn'">{{ branchSources.length }}</span>
            </div>
            <ResearchFlow :graph="graph" :selected-id="nodeId" :highlight-ids="highlightIds" @select="selectNode" />
          </section>

          <section class="card">
            <h3>節點種類分布</h3>
            <p v-if="kindCounts.length === 0" class="muted">目前沒有節點。</p>
            <div v-else class="row compact wrap" style="flex-wrap: wrap;">
              <span v-for="entry in kindCounts" :key="entry.kind" class="tag">
                {{ FLOW_KIND_LABELS[entry.kind] }} {{ entry.count }}
              </span>
            </div>

            <h3 style="margin-top: 18px;">分支來源</h3>
            <p v-if="branchSources.length === 0" class="muted">後端未揭露並行分支：目前沒有節點分出多條邊。</p>
            <div v-else class="list-rows">
              <button v-for="id in branchSources" :key="id" type="button" class="run-button" @click="selectNode(id)">
                <div>
                  <strong>{{ nodeTitle(id) }}</strong>
                  <div class="muted mono">{{ id }}</div>
                </div>
                <span class="tag">分支</span>
              </button>
            </div>
            <div class="note" style="margin-top: 12px;">
              邊只表達契約明載的歸屬關係（版本→任務、任務→候選、候選→驗證、提交→評估）；沒有邊代表後端尚未揭露依賴。
            </div>
          </section>
        </div>

        <section class="card" style="margin-top: 16px;">
          <h3>依賴前提與後續推演</h3>
          <p v-if="trace === null" class="muted">請在流程圖中選擇一個節點。</p>
          <template v-else>
            <div class="formula-hero">{{ FLOW_KIND_LABELS[trace.node.kind] }}：{{ trace.node.title }}</div>
            <div class="row compact">
              <span>節點識別碼</span>
              <span class="mono record-value">{{ trace.node.id }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag">{{ trace.node.badge }}</span>
            </div>
            <div class="row compact">
              <span>說明</span>
              <span>{{ trace.node.subtitle }}</span>
            </div>

            <div class="layout trace-grid">
              <div>
                <h3>依賴前提（上游）</h3>
                <p v-if="trace.upstream.length === 0" class="muted">沒有可回溯的上游節點。</p>
                <div v-else class="list-rows">
                  <button v-for="node in trace.upstream" :key="node.id" type="button" class="run-button" @click="selectNode(node.id)">
                    <div>
                      <strong>{{ FLOW_KIND_LABELS[node.kind] }}：{{ node.title }}</strong>
                      <div class="muted mono">{{ node.id }}</div>
                    </div>
                    <span class="tag">{{ node.badge }}</span>
                  </button>
                </div>
              </div>
              <div>
                <h3>後續推演（下游）</h3>
                <p v-if="trace.downstream.length === 0" class="muted">沒有已揭露的下游節點。</p>
                <div v-else class="list-rows">
                  <button v-for="node in trace.downstream" :key="node.id" type="button" class="run-button" @click="selectNode(node.id)">
                    <div>
                      <strong>{{ FLOW_KIND_LABELS[node.kind] }}：{{ node.title }}</strong>
                      <div class="muted mono">{{ node.id }}</div>
                    </div>
                    <span class="tag">{{ node.badge }}</span>
                  </button>
                </div>
              </div>
            </div>

            <h3 style="margin-top: 18px;">節點紀錄</h3>
            <div v-for="record in trace.node.records" :key="record.label" class="row compact">
              <span>{{ record.label }}</span>
              <span class="record-value mono">{{ record.value }}</span>
            </div>

            <h3 style="margin-top: 18px;">關聯產物</h3>
            <p v-if="trace.node.artifacts.length === 0" class="muted">此節點沒有已揭露的產物。</p>
            <div v-else class="actions wrap">
              <RouterLink
                v-for="artifact in trace.node.artifacts"
                :key="artifact.id"
                :to="{ name: 'artifact', params: { id: artifact.id }, query: withBackRef(route.fullPath) }"
              >
                <button type="button">{{ artifact.label }}</button>
              </RouterLink>
            </div>

            <h3 style="margin-top: 18px;">事件紀錄</h3>
            <p v-if="trace.node.events.length === 0" class="muted">此節點沒有已揭露的事件。</p>
            <ul v-else class="event-list">
              <li v-for="(event, index) in trace.node.events" :key="`${event.sequence}-${String(index)}`">
                <span class="tag">{{ event.event_type }}</span>
                <span class="muted">{{ event.occurred_at }}</span>
                <span class="mono">{{ event.sequence }}</span>
              </li>
            </ul>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                v-if="trace.node.runId !== null"
                :to="{ name: 'run', params: { id: trace.node.runId }, query: withBackRef(route.fullPath) }"
              >
                <button type="button">查看任務詳情</button>
              </RouterLink>
              <RouterLink
                v-if="version !== null"
                :to="{ name: 'research-workbench', params: { id: version.research_id }, query: withBackRef(route.fullPath, { version: version.id, node: trace.node.id }) }"
              >
                <button type="button">在研究室中開啟</button>
              </RouterLink>
            </div>
          </template>
        </section>
      </template>
      <p v-else-if="researchId !== '' && versionId !== ''" class="muted">此版本沒有可推導的流程節點。</p>
    </template>
  </section>
</template>

<style scoped>
.selector {
  margin-bottom: 16px;
}

.deriv-grid {
  grid-template-columns: 1.5fr 1fr;
}

.trace-grid {
  grid-template-columns: 1fr 1fr;
  margin-top: 14px;
}

.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}

.run-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
  text-align: left;
  width: 100%;
}

.compact {
  padding: 8px 0;
}

.formula-hero {
  font-size: 18px;
  font-weight: 650;
  padding: 12px 0;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}

.event-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.event-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid #25374e;
  padding-bottom: 8px;
}

@media (max-width: 1200px) {
  .deriv-grid,
  .trace-grid {
    grid-template-columns: 1fr;
  }
}
</style>
