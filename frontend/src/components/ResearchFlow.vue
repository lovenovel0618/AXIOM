<script setup lang="ts">
/**
 * 研究流程圖：把 buildFlow 推導出的節點與邊畫成可點選的方塊圖。
 * 只呈現資料本身；節點紀錄由呼叫端在選取後顯示，這裡不含任何推測內容。
 */
import { computed, ref } from 'vue'
import { FLOW_KIND_LABELS, type FlowGraph, type FlowNode, type FlowNodeKind } from '../lib/flow'

const props = defineProps<{
  graph: FlowGraph
  selectedId: string | null
  highlightIds?: string[]
}>()

const emit = defineEmits<{ select: [id: string] }>()

const NODE_W = 232
const NODE_H = 84
const COL_GAP = 104
const ROW_GAP = 56
const PAD = 28
const MIN_SCALE = 0.5
const MAX_SCALE = 1.6
const SCALE_STEP = 0.2

const scale = ref(1)

interface Placed {
  node: FlowNode
  x: number
  y: number
}

const placed = computed<Placed[]>(() =>
  props.graph.nodes.map((node) => ({
    node,
    x: PAD + node.column * (NODE_W + COL_GAP),
    y: PAD + node.row * (NODE_H + ROW_GAP),
  })),
)

const positions = computed<Map<string, Placed>>(() => new Map(placed.value.map((entry) => [entry.node.id, entry])))

const maxColumn = computed<number>(() => props.graph.nodes.reduce((best, node) => Math.max(best, node.column), 0))
const maxRow = computed<number>(() => props.graph.nodes.reduce((best, node) => Math.max(best, node.row), 0))
const width = computed<number>(() => PAD * 2 + (maxColumn.value + 1) * NODE_W + maxColumn.value * COL_GAP)
const height = computed<number>(() => PAD * 2 + (maxRow.value + 1) * NODE_H + maxRow.value * ROW_GAP)

/** 依實際出現的節點種類列出圖例，不出現沒有節點的空欄位。 */
const legend = computed<FlowNodeKind[]>(() => {
  const seen = new Set<FlowNodeKind>()
  for (const node of props.graph.nodes) seen.add(node.kind)
  return [...seen]
})

interface DrawnEdge {
  key: string
  path: string
  branch: boolean
  active: boolean
}

function curve(from: Placed, to: Placed): string {
  const x1 = from.x + NODE_W
  const y1 = from.y + NODE_H / 2
  const x2 = to.x
  const y2 = to.y + NODE_H / 2
  const bend = Math.max(24, (x2 - x1) / 2)
  return `M ${String(x1)} ${String(y1)} C ${String(x1 + bend)} ${String(y1)}, ${String(x2 - bend)} ${String(y2)}, ${String(x2)} ${String(y2)}`
}

const drawn = computed<DrawnEdge[]>(() => {
  const map = positions.value
  const highlights = new Set(props.highlightIds ?? [])
  const rows: DrawnEdge[] = []
  for (const [index, edge] of props.graph.edges.entries()) {
    const from = map.get(edge.from)
    const to = map.get(edge.to)
    if (from === undefined || to === undefined) continue
    rows.push({
      key: `${edge.from}->${edge.to}:${String(index)}`,
      path: curve(from, to),
      branch: edge.branch,
      active:
        props.selectedId === edge.from ||
        props.selectedId === edge.to ||
        (highlights.has(edge.from) && highlights.has(edge.to)),
    })
  }
  return rows
})

function clip(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

function zoom(delta: number): void {
  const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round((scale.value + delta) * 10) / 10))
  scale.value = next
}

function reset(): void {
  scale.value = 1
}

function choose(id: string): void {
  emit('select', id)
}

function onKey(event: KeyboardEvent, id: string): void {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  choose(id)
}
</script>

<template>
  <div class="flow">
    <div class="toolbar">
      <div class="legend">
        <span v-for="kind in legend" :key="kind" class="legend-item">{{ FLOW_KIND_LABELS[kind] }}</span>
      </div>
      <div class="zoom">
        <button type="button" :disabled="scale <= MIN_SCALE" aria-label="縮小" @click="zoom(-SCALE_STEP)">−</button>
        <span class="mono">{{ Math.round(scale * 100) }}%</span>
        <button type="button" :disabled="scale >= MAX_SCALE" aria-label="放大" @click="zoom(SCALE_STEP)">＋</button>
        <button type="button" @click="reset">重設</button>
      </div>
    </div>

    <div class="canvas" role="group" aria-label="研究流程圖">
      <p v-if="placed.length === 0" class="empty">目前篩選條件下沒有節點。</p>
      <svg
        v-else
        :width="width * scale"
        :height="height * scale"
        :viewBox="`0 0 ${width} ${height}`"
        preserveAspectRatio="xMinYMin meet"
      >
        <g class="edges">
          <path
            v-for="edge in drawn"
            :key="edge.key"
            :d="edge.path"
            class="edge"
            :class="{ branch: edge.branch, active: edge.active }"
          />
        </g>
        <g
          v-for="entry in placed"
          :key="entry.node.id"
          class="node"
          :class="[
            `tone-${entry.node.tone}`,
            {
              selected: props.selectedId === entry.node.id,
              related: (props.highlightIds ?? []).includes(entry.node.id) && props.selectedId !== entry.node.id,
            },
          ]"
          role="button"
          tabindex="0"
          :aria-pressed="props.selectedId === entry.node.id"
          :aria-label="`${FLOW_KIND_LABELS[entry.node.kind]}：${entry.node.title}，狀態 ${entry.node.badge}`"
          @click="choose(entry.node.id)"
          @keydown="onKey($event, entry.node.id)"
        >
          <title>{{ `${FLOW_KIND_LABELS[entry.node.kind]}\n${entry.node.title}\n${entry.node.subtitle}\n狀態：${entry.node.badge}` }}</title>
          <rect class="box" :x="entry.x" :y="entry.y" :width="NODE_W" :height="NODE_H" rx="10" />
          <text class="kind" :x="entry.x + 14" :y="entry.y + 24">{{ FLOW_KIND_LABELS[entry.node.kind] }}</text>
          <text class="title" :x="entry.x + 14" :y="entry.y + 46">{{ clip(entry.node.title, 22) }}</text>
          <text class="subtitle" :x="entry.x + 14" :y="entry.y + 66">{{ clip(entry.node.subtitle, 26) }}</text>
          <text class="badge" :x="entry.x + NODE_W - 14" :y="entry.y + 46" text-anchor="end">
            {{ clip(entry.node.badge, 12) }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.flow {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 0.75rem;
}
.legend-item {
  font-size: 0.8rem;
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.1rem 0.6rem;
}
.zoom {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.zoom button {
  padding: 0.2rem 0.6rem;
}
.canvas {
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 0.6rem;
  background: var(--surface-muted);
}
.empty {
  margin: 0;
  padding: 1rem;
  color: var(--text-muted);
}
svg {
  display: block;
}
.edge {
  fill: none;
  stroke: var(--border);
  stroke-width: 1.5;
}
.edge.branch {
  stroke-width: 2.5;
}
.edge.active {
  stroke: var(--accent);
}
.node {
  cursor: pointer;
}
.node .box {
  fill: var(--surface);
  stroke: var(--border);
  stroke-width: 1.5;
}
.node:focus-visible .box {
  outline: none;
  stroke: var(--accent);
  stroke-width: 3;
}
.node.selected .box {
  stroke: var(--accent);
  stroke-width: 3;
}
.node.related .box {
  stroke: #6ea8ff;
  stroke-width: 2.25;
}
.tone-OK .box {
  stroke: var(--ok);
}
.tone-OK .badge {
  fill: var(--ok);
}
.tone-RUNNING .box,
.tone-PENDING .box {
  stroke: var(--warn);
}
.tone-RUNNING .badge,
.tone-PENDING .badge {
  fill: var(--warn);
}
.tone-PENDING .box {
  stroke-dasharray: 4 3;
}
.tone-FAILED .box {
  stroke: var(--danger);
}
.tone-FAILED .badge {
  fill: var(--danger);
}
.tone-NEUTRAL .badge {
  fill: var(--text-muted);
}
.kind {
  font-size: 10px;
  fill: var(--text-muted);
  letter-spacing: 0.04em;
}
.title {
  font-size: 13px;
  font-weight: 600;
  fill: var(--text);
}
.subtitle {
  font-size: 11px;
  fill: var(--text-muted);
}
.badge {
  font-size: 10px;
  font-weight: 600;
  fill: var(--text-muted);
}
</style>
