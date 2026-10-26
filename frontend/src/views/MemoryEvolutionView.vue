<script setup lang="ts">
/**
 * 知識演化（SSOT SCREEN 31）：版本、修正、撤回與證據更新。
 *
 * 演化圖與時間軸只由已讀取到的研究、版本、證據包、品質報告與凍結提交，以及契約明載的引用關係建立；
 * 讀不到的節點不會被補上，也不推測不存在的依賴。後端沒有版本差異與撤回流程端點，相關欄位標示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import MemoryTabs from '../components/MemoryTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useMemoryCenter } from '../lib/useMemoryCenter'
import { EVIDENCE_STATUS_LABELS, QUALITY_LABELS, type EvidenceStatus, type QualityOutcome } from '../lib/evidence'
import {
  EVOLUTION_NODE_LABELS,
  MEMORY_UNKNOWN,
  VERSION_STATUS_LABELS,
  buildEvolutionGraph,
  buildEvolutionTimeline,
  summarizeEvolution,
  type EvolutionNode,
  type EvolutionNodeKind,
} from '../lib/memoryCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useMemoryCenter()

const nodeId = ref(readQueryString(route.query, 'node'))

const graph = computed(() => (center.value === null ? null : buildEvolutionGraph(center.value)))
const timeline = computed(() => (center.value === null ? [] : buildEvolutionTimeline(center.value)))
const summary = computed(() =>
  center.value === null
    ? { versions: 0, revisions: 0, quarantinedEvidence: 0, withdrawn: 0 }
    : summarizeEvolution(center.value),
)

const NODE_ORDER: readonly EvolutionNodeKind[] = ['RESEARCH', 'VERSION', 'EVIDENCE', 'QUALITY', 'SUBMISSION']

const nodeCounts = computed<{ kind: EvolutionNodeKind; count: number }[]>(() => {
  const counts = graph.value?.nodes ?? []
  return NODE_ORDER.map((kind) => ({ kind, count: counts.filter((node) => node.kind === kind).length }))
})
const selectedNode = computed<EvolutionNode | null>(
  () => (graph.value?.nodes ?? []).find((node) => node.id === nodeId.value) ?? null,
)
const selectedEdges = computed(() =>
  (graph.value?.edges ?? []).filter((edge) => edge.from === nodeId.value || edge.to === nodeId.value),
)
const backRef = computed(() => readBackRef(route.query))
/** 版本節點的識別碼格式為 `version:<id>`；只有版本節點能開啟研究室。 */
const selectedVersionId = computed<string | null>(() => {
  const node = selectedNode.value
  if (node === null || node.kind !== 'VERSION') return null
  return node.id.startsWith('version:') ? node.id.slice('version:'.length) : null
})
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const versionId = selectedVersionId.value
  if (versionId === null) return null
  return withBackRef(route.fullPath, { version: versionId, node: `version:${versionId}` })
})

function nodeLabel(id: string): string {
  const node = (graph.value?.nodes ?? []).find((row) => row.id === id)
  return node === undefined ? id : `${EVOLUTION_NODE_LABELS[node.kind]}：${node.label}`
}

function evidenceText(status: EvidenceStatus | null): string {
  return status === null ? MEMORY_UNKNOWN : EVIDENCE_STATUS_LABELS[status]
}

function qualityText(status: QualityOutcome | null): string {
  return status === null ? MEMORY_UNKNOWN : QUALITY_LABELS[status]
}

function selectNode(id: string): void {
  nodeId.value = id
}

onMounted(async () => {
  await load()
  const nodes = graph.value?.nodes ?? []
  if (nodeId.value === '' && nodes.length > 0) nodeId.value = nodes[0]?.id ?? ''
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

watch(graph, (value) => {
  const nodes = value?.nodes ?? []
  if (nodes.length === 0) return
  if (nodes.some((node) => node.id === nodeId.value)) return
  nodeId.value = nodes[0]?.id ?? ''
})
</script>

<template>
  <section>
    <MemoryTabs />

    <div class="head">
      <div>
        <div class="eyebrow">記憶 / SCREEN 31</div>
        <h1>知識演化</h1>
        <p class="muted">專屬任務畫面設計｜版本、修正、撤回與證據更新：以實際引用關係建立節點與邊，據此呈現知識如何隨版本演進。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'memory' }">
          <button type="button" class="primary">前往知識庫</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="graph !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">版本數</div>
          <div class="metric-value">{{ summary.versions }}</div>
          <p>已讀取到的研究版本總數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">修訂累計</div>
          <div class="metric-value">{{ summary.revisions }}</div>
          <p>各版本 revision 欄位加總，代表版本演進的修訂次數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">隔離證據</div>
          <div class="metric-value" :class="summary.quarantinedEvidence > 0 ? 'bad' : 'good'">
            {{ summary.quarantinedEvidence }}
          </div>
          <p>狀態為 QUARANTINED 的證據包數量，代表被撤回的證據。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">撤回版本</div>
          <div class="metric-value" :class="summary.withdrawn > 0 ? 'warn' : 'good'">{{ summary.withdrawn }}</div>
          <p>狀態為 FAILED 或 CANCELLED 的版本數，這些版本已不再推進。</p>
        </section>
      </div>

      <section class="card" style="margin-bottom: 16px;">
        <h3>節點種類分布</h3>
        <p v-if="graph.nodes.length === 0" class="muted">目前沒有可建立的節點。</p>
        <div v-else class="tag-row">
          <span v-for="entry in nodeCounts" :key="entry.kind" class="tag">
            {{ EVOLUTION_NODE_LABELS[entry.kind] }} {{ entry.count }}
          </span>
        </div>
      </section>

      <div class="layout evolution-grid">
        <section class="card">
          <h3>演化節點</h3>
          <p v-if="graph.nodes.length === 0" class="muted">
            目前沒有可讀取的演化結構。請先產生研究版本、證據包與凍結提交，演化圖才會出現節點。
          </p>
          <div v-else class="list-rows">
            <button
              v-for="node in graph.nodes"
              :key="node.id"
              type="button"
              class="module-link selectable"
              :class="{ active: node.id === nodeId }"
              @click="selectNode(node.id)"
            >
              <div>
                <strong>{{ EVOLUTION_NODE_LABELS[node.kind] }}</strong>
                <div class="muted mono">{{ node.label }}</div>
              </div>
              <span class="tag">{{ node.status }}</span>
            </button>
          </div>
        </section>

        <section class="card">
          <h3>選定節點</h3>
          <p v-if="selectedNode === null" class="muted">請從左側節點清單選擇一個節點。</p>
          <template v-else>
            <div class="row compact">
              <span>種類</span>
              <span class="tag">{{ EVOLUTION_NODE_LABELS[selectedNode.kind] }}</span>
            </div>
            <div class="row compact">
              <span>識別碼</span>
              <span class="mono record-value">{{ selectedNode.id }}</span>
            </div>
            <div class="row compact">
              <span>標題</span>
              <span class="mono record-value">{{ selectedNode.label }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag">{{ selectedNode.status }}</span>
            </div>

            <h3 style="margin-top: 18px;">關聯邊</h3>
            <p v-if="selectedEdges.length === 0" class="muted">這個節點目前沒有已揭露的引用關係。</p>
            <ul v-else class="reasons">
              <li v-for="edge in selectedEdges" :key="`${edge.from}->${edge.to}`">
                {{ nodeLabel(edge.from) }} → {{ edge.label }} → {{ nodeLabel(edge.to) }}
              </li>
            </ul>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                v-if="workbenchQuery !== null && selectedVersionId !== null"
                :to="{ name: 'research-workbench', params: { id: selectedVersionId }, query: workbenchQuery }"
              >
                <button type="button">在研究室中開啟版本</button>
              </RouterLink>
            </div>
            <div class="note" style="margin-top: 12px;">
              版本差異、撤回流程與證據更新紀錄需後端端點；本頁只呈現實際引用關係，未讀到的節點一律不補造。
            </div>
          </template>
        </section>
      </div>

      <section class="card" style="margin-top: 16px;">
        <h3>演化時間軸</h3>
        <p v-if="timeline.length === 0" class="muted">目前沒有可讀取的版本紀錄。</p>
        <table v-else>
          <thead>
            <tr>
              <th>研究 / 版本</th>
              <th>修訂</th>
              <th>版本狀態</th>
              <th>證據狀態</th>
              <th>品質</th>
              <th>凍結提交</th>
              <th>建立時間</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in timeline" :key="entry.versionId">
              <td>
                <div>{{ entry.researchName }}</div>
                <div class="muted mono">{{ entry.versionId }}</div>
              </td>
              <td>{{ entry.revision }}</td>
              <td>{{ VERSION_STATUS_LABELS[entry.versionStatus] }}</td>
              <td>{{ evidenceText(entry.evidenceStatus) }}</td>
              <td>{{ qualityText(entry.quality) }}</td>
              <td>{{ entry.submissionCount }}｜{{ entry.submissionStatus }}</td>
              <td class="mono">{{ entry.createdAt }}</td>
            </tr>
          </tbody>
        </table>

        <h3 style="margin-top: 18px;">引用關係邊</h3>
        <p v-if="graph.edges.length === 0" class="muted">目前沒有已揭露的引用關係。</p>
        <table v-else>
          <thead>
            <tr>
              <th>來源節點</th>
              <th>關係</th>
              <th>目標節點</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="edge in graph.edges" :key="`${edge.from}->${edge.to}`">
              <td>{{ nodeLabel(edge.from) }}</td>
              <td>{{ edge.label }}</td>
              <td>{{ nodeLabel(edge.to) }}</td>
            </tr>
          </tbody>
        </table>
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
  min-height: 140px;
}

.metric-value {
  font-size: 30px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.evolution-grid {
  grid-template-columns: 1.1fr 1fr;
}

.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
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

.compact {
  padding: 8px 0;
}

.reasons {
  margin: 6px 0 0;
  padding-left: 18px;
  overflow-wrap: anywhere;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evolution-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
