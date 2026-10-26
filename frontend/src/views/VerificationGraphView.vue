<script setup lang="ts">
/**
 * 證據關聯圖（SSOT SCREEN 26）：證據共享依賴與獨立性評估。
 *
 * 圖只由已讀取到的研究版本、凍結提交、證據包、validation run 與證明產物，以及契約明載的引用關係建立；
 * 沒有讀到的節點不會被補上，也不推測不存在的依賴。共享依賴與獨立性都由實際邊計算。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import VerificationTabs from '../components/VerificationTabs.vue'
import { readBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useVerificationCenter } from '../lib/useVerificationCenter'
import { VERIFICATION_UNKNOWN } from '../lib/verificationCenter'
import {
  EVIDENCE_NODE_LABELS,
  buildEvidenceGraph,
  findEvidenceTrace,
  summarizeEvidenceNodes,
  type EvidenceGraph,
  type EvidenceGraphNode,
} from '../lib/verificationGraph'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useVerificationCenter()

const nodeId = ref(readQueryString(route.query, 'node'))

const graph = computed<EvidenceGraph | null>(() => (center.value === null ? null : buildEvidenceGraph(center.value)))
const nodes = computed<EvidenceGraphNode[]>(() => graph.value?.nodes ?? [])
const kindCounts = computed(() => (graph.value === null ? [] : summarizeEvidenceNodes(graph.value)))
const trace = computed(() => (graph.value === null || nodeId.value === '' ? null : findEvidenceTrace(graph.value, nodeId.value)))
const selectedNode = computed<EvidenceGraphNode | null>(
  () => nodes.value.find((node) => node.id === nodeId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))
const independence = computed(() => graph.value?.independence ?? null)

function selectNode(id: string): void {
  nodeId.value = id
}

function nodeLabel(id: string): string {
  const node = nodes.value.find((row) => row.id === id)
  return node === undefined ? id : `${EVIDENCE_NODE_LABELS[node.kind]}：${node.sublabel}`
}

onMounted(async () => {
  await load()
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

watch(nodes, (value) => {
  if (value.length === 0) return
  if (value.some((node) => node.id === nodeId.value)) return
  nodeId.value = value[0]?.id ?? ''
})
</script>

<template>
  <section>
    <VerificationTabs />

    <div class="head">
      <div>
        <div class="eyebrow">驗證 / SCREEN 26</div>
        <h1>證據關聯圖</h1>
        <p class="muted">專屬任務畫面設計｜證據共享依賴與獨立性評估：以實際引用關係建立節點與邊，並據此判定證據是否彼此獨立。</p>
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
    <template v-else-if="graph !== null">
      <div class="layout summary-grid">
        <section class="card metric-card">
          <div class="eyebrow">證據包</div>
          <div class="metric-value" :class="independence !== null && independence.bundles > 0 ? 'good' : 'warn'">
            {{ independence?.bundles ?? 0 }}
          </div>
          <p>目前已讀取到、被研究版本引用的證據包數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">共享依賴</div>
          <div class="metric-value" :class="(independence?.sharedDependencies ?? 0) > 0 ? 'warn' : 'good'">
            {{ independence?.sharedDependencies ?? 0 }}
          </div>
          <p>被兩個以上證據包共同引用的 validation 或證明產物數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">獨立性</div>
          <div class="metric-value" :class="independence?.independent === true ? 'good' : 'warn'">
            {{ independence?.independent === true ? '獨立' : '不獨立' }}
          </div>
          <p>{{ independence?.reason ?? VERIFICATION_UNKNOWN }}</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">節點 / 邊</div>
          <div class="metric-value">{{ graph.nodes.length }} / {{ graph.edges.length }}</div>
          <p>節點與引用關係邊的總數，全部來自實際讀取到的實體。</p>
        </section>
      </div>

      <section class="card" style="margin-bottom: 16px;">
        <h3>節點種類分布</h3>
        <p v-if="kindCounts.length === 0" class="muted">目前沒有可建立的節點。</p>
        <div v-else class="tag-row">
          <span v-for="entry in kindCounts" :key="entry.kind" class="tag">
            {{ EVIDENCE_NODE_LABELS[entry.kind] }} {{ entry.count }}
          </span>
        </div>
      </section>

      <div class="layout graph-grid">
        <section class="card">
          <h3>節點</h3>
          <p v-if="nodes.length === 0" class="muted">
            目前沒有可讀取的證據結構。請先產生研究版本、凍結提交與證據包，證據關聯圖才會出現節點。
          </p>
          <div v-else class="list-rows">
            <button
              v-for="node in nodes"
              :key="node.id"
              type="button"
              class="module-link selectable"
              :class="{ active: node.id === nodeId }"
              @click="selectNode(node.id)"
            >
              <div>
                <strong>{{ EVIDENCE_NODE_LABELS[node.kind] }}</strong>
                <div class="muted mono">{{ node.sublabel }}</div>
              </div>
              <span class="tag">{{ node.label }}</span>
            </button>
          </div>
        </section>

        <section class="card">
          <h3>共享依賴</h3>
          <p v-if="independence === null || independence.sharedDependencies === 0" class="muted">
            目前讀到的證據包之間沒有共同的 validation 或證明產物。
          </p>
          <div v-else class="list-rows">
            <article v-for="item in graph.shared" :key="item.id" class="shared-card">
              <div class="row compact">
                <strong>{{ EVIDENCE_NODE_LABELS[item.kind] }}</strong>
                <span class="tag warn">{{ item.referrers.length }} 個證據包引用</span>
              </div>
              <div class="muted mono">{{ item.id }}</div>
              <div class="muted">被引用狀態：{{ item.label }}</div>
              <ul class="reasons">
                <li v-for="referrer in item.referrers" :key="referrer" class="mono">{{ referrer }}</li>
              </ul>
            </article>
          </div>

          <h3 style="margin-top: 18px;">獨立性評估</h3>
          <div class="row compact">
            <span>證據包數</span>
            <span class="tag">{{ independence?.bundles ?? 0 }}</span>
          </div>
          <div class="row compact">
            <span>共享依賴數</span>
            <span class="tag" :class="(independence?.sharedDependencies ?? 0) > 0 ? 'warn' : 'good'">
              {{ independence?.sharedDependencies ?? 0 }}
            </span>
          </div>
          <div class="row compact">
            <span>判定</span>
            <span class="tag" :class="independence?.independent === true ? 'good' : 'warn'">
              {{ independence?.independent === true ? '獨立' : '不獨立' }}
            </span>
          </div>
          <p class="muted">{{ independence?.reason ?? VERIFICATION_UNKNOWN }}</p>
          <div class="note">
            獨立性只依共享依賴判定；少於兩個證據包時，本頁不宣告獨立，也不以單一證據推論整體可信度。
          </div>
        </section>
      </div>

      <section class="card" style="margin-top: 16px;">
        <h3>選定節點的上下游關聯</h3>
        <p v-if="trace === null" class="muted">請從上方節點清單選擇一個節點。</p>
        <template v-else>
          <div class="row compact">
            <span>節點</span>
            <span>
              {{ EVIDENCE_NODE_LABELS[trace.node.kind] }}：{{ trace.node.sublabel }}
            </span>
          </div>
          <div class="row compact">
            <span>節點識別碼</span>
            <span class="mono record-value">{{ trace.node.id }}</span>
          </div>
          <div class="row compact">
            <span>狀態</span>
            <span class="tag">{{ trace.node.label }}</span>
          </div>

          <div class="layout trace-grid">
            <div>
              <h3>上游（來源）</h3>
              <p v-if="trace.upstream.length === 0" class="muted">沒有可回溯的上游節點。</p>
              <div v-else class="list-rows">
                <button v-for="node in trace.upstream" :key="node.id" type="button" class="module-link selectable" @click="selectNode(node.id)">
                  <div>
                    <strong>{{ EVIDENCE_NODE_LABELS[node.kind] }}</strong>
                    <div class="muted mono">{{ node.sublabel }}</div>
                  </div>
                  <span class="tag">{{ node.label }}</span>
                </button>
              </div>
            </div>
            <div>
              <h3>下游（引用）</h3>
              <p v-if="trace.downstream.length === 0" class="muted">沒有已揭露的下游節點。</p>
              <div v-else class="list-rows">
                <button v-for="node in trace.downstream" :key="node.id" type="button" class="module-link selectable" @click="selectNode(node.id)">
                  <div>
                    <strong>{{ EVIDENCE_NODE_LABELS[node.kind] }}</strong>
                    <div class="muted mono">{{ node.sublabel }}</div>
                  </div>
                  <span class="tag">{{ node.label }}</span>
                </button>
              </div>
            </div>
          </div>
        </template>

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
.summary-grid {
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

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.graph-grid {
  grid-template-columns: 1.2fr 1fr;
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

.shared-card {
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
}

.trace-grid {
  grid-template-columns: 1fr 1fr;
  margin-top: 14px;
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
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .graph-grid,
  .trace-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
