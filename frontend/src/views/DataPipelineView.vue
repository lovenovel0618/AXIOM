<script setup lang="ts">
/**
 * 前處理管線（SSOT SCREEN 15，pipeline）：轉換 DAG、參數、前後差異。
 *
 * 後端沒有前處理管線端點，因此節點鏈只由不可變版本快照推導；轉換節點、參數與適用欄位一律
 * 標示「未取得」，前後差異在兩版以上結構預覽可解析時才提供欄位層級比較入口。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DataTabs from '../components/DataTabs.vue'
import {
  DATASET_VERSION_STATUS_LABELS,
  FORMAT_LABELS,
  buildPipelineNodes,
  buildPipelineStages,
  resolveVersionId,
  stepStatusLabel,
} from '../lib/dataCenter'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useDatasetWorkspace } from '../lib/useDataCenter'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const { workspace, loading, error, load } = useDatasetWorkspace(() => datasetId.value)

const selectedNodeId = ref(readQueryString(route.query, 'node'))

const versions = computed(() => workspace.value?.versions ?? [])
const metadataByArtifact = computed(() => workspace.value?.metadataByArtifact ?? {})
const nodes = computed(() => buildPipelineNodes(versions.value))
const stages = computed(() => buildPipelineStages(nodes.value, versions.value, metadataByArtifact.value))
const selectedNode = computed(() => nodes.value.find((row) => row.versionId === selectedNodeId.value) ?? null)
const selectedVersion = computed(() => versions.value.find((row) => row.id === selectedNodeId.value) ?? null)
const backRef = readQueryString(route.query, 'ref')

function selectNode(versionId: string): void {
  selectedNodeId.value = versionId
}

onMounted(async () => {
  await load()
  selectedNodeId.value = resolveVersionId(versions.value, readQueryString(route.query, 'node'))
})

watch(
  () => route.params.id,
  async () => {
    if (route.name !== 'data-pipeline') return
    await load()
    selectedNodeId.value = resolveVersionId(versions.value, readQueryString(route.query, 'node'))
  },
)

watch(selectedNodeId, async (value) => {
  await replaceQueryState(router, route, { node: value })
})
</script>

<template>
  <section>
    <DataTabs :dataset-id="datasetId" />

    <div class="head">
      <div>
        <div class="eyebrow">數據 / SCREEN 15</div>
        <h1>前處理管線</h1>
        <p class="muted">
          轉換 DAG、參數、前後差異｜節點鏈只由不可變版本快照推導；轉換節點與參數沒有後端端點，一律標示「未取得」。
        </p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'datasets' }"><button type="button">返回資料集清單</button></RouterLink>
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && workspace === null" class="muted">載入中…</p>
    <p v-else-if="workspace === null" class="bad">{{ error === '' ? '未取得此資料集。' : error }}</p>
    <template v-else>
      <div class="layout cols2">
        <section class="card">
          <h3>快照節點鏈</h3>
          <p v-if="nodes.length === 0" class="muted">此資料集尚無版本，管線沒有可推導的節點。</p>
          <ol v-else class="node-chain">
            <li v-for="node in nodes" :key="node.versionId" class="node-row">
              <button
                type="button"
                class="node-button"
                :class="{ primary: node.versionId === selectedNodeId }"
                @click="selectNode(node.versionId)"
              >
                <span class="node-label">{{ node.label }}</span>
                <span class="muted">{{ node.detail }}</span>
              </button>
              <span class="tag" :class="node.status === 'PASS' ? 'good' : node.status === 'FAIL' ? 'bad' : 'muted'">
                {{ stepStatusLabel(node.status) }}
              </span>
            </li>
          </ol>

          <h3 style="margin-top: 22px;">選定快照</h3>
          <p v-if="selectedNode === null || selectedVersion === null" class="muted">請從上方節點鏈選擇一個快照。</p>
          <template v-else>
            <div class="row compact">
              <span>版本</span>
              <span class="mono record-value">{{ selectedVersion.id }}</span>
            </div>
            <div class="row compact">
              <span>格式 / 列數</span>
              <span>{{ FORMAT_LABELS[selectedVersion.format] }} / {{ selectedVersion.row_count }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag">{{ DATASET_VERSION_STATUS_LABELS[selectedVersion.status] }}</span>
            </div>
            <div class="row compact">
              <span>結構預覽</span>
              <span class="muted">
                {{ selectedVersion.structure_preview_artifact_id === null ? '未取得' : selectedVersion.structure_preview_artifact_id }}
              </span>
            </div>
            <div class="actions" style="margin-top: 12px;">
              <RouterLink :to="{ name: 'data-preview', params: { id: datasetId }, query: { version: selectedVersion.id } }">
                <button type="button">檢視資料預覽</button>
              </RouterLink>
              <RouterLink :to="{ name: 'data-diff', params: { id: datasetId }, query: { target: selectedVersion.id } }">
                <button type="button">與其他版本比較</button>
              </RouterLink>
            </div>
          </template>
        </section>

        <section class="card">
          <h3>程序階段</h3>
          <div class="check-list">
            <div v-for="stage in stages" :key="stage.key" class="check-row">
              <span class="tag" :class="stage.status === 'PASS' ? 'good' : stage.status === 'FAIL' ? 'bad' : 'muted'">
                {{ stepStatusLabel(stage.status) }}
              </span>
              <div>
                <strong>{{ stage.label }}</strong>
                <div class="muted">{{ stage.detail }}</div>
              </div>
            </div>
          </div>
          <div class="note" style="margin-top: 14px;">
            轉換節點 DAG 與參數需後端管線端點；目前只宣告不可變快照與可判定檢核，不以推測補值。
          </div>
        </section>
      </div>

      <p v-if="error !== ''" class="bad" style="margin-top: 16px;">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.node-chain {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.node-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.node-button {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  text-align: left;
}

.node-label {
  font-weight: 650;
}

.check-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 10px 12px;
  background: #0e1e31;
}

.compact {
  padding: 9px 0;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}
</style>
