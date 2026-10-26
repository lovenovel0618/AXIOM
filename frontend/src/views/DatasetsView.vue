<script setup lang="ts">
/** 資料集清單：只負責建立與導覽，版本、預覽、品質與版本比較都在資料集工作區。 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { createDataset, listDatasets, listVersions, type Dataset, type DatasetVersion } from '../api/datasets'
import { buildDatasetDigest } from '../lib/datasetWorkbench'
import { describeError } from '../lib/messages'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'

const route = useRoute()
const router = useRouter()
const datasets = ref<Dataset[]>([])
const versionIndex = ref<Record<string, DatasetVersion[]>>({})
const name = ref('')
const keyword = ref(readQueryString(route.query, 'q'))
const busy = ref(false)
const error = ref('')
const notice = ref('')

const visible = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  if (needle === '') return datasets.value
  return datasets.value.filter(
    (row) => row.name.toLowerCase().includes(needle) || row.id.toLowerCase().includes(needle),
  )
})

function digestOf(id: string) {
  return buildDatasetDigest(versionIndex.value[id] ?? [])
}

async function loadDatasets(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    datasets.value = (await listDatasets(client)).items
    const index: Record<string, DatasetVersion[]> = {}
    await Promise.all(
      datasets.value.map(async (row) => {
        try {
          index[row.id] = (await listVersions(client, row.id)).items
        } catch {
          index[row.id] = []
        }
      }),
    )
    versionIndex.value = index
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    busy.value = false
  }
}

async function submitDataset(): Promise<void> {
  if (busy.value || name.value === '') return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const created = await createDataset(client, name.value)
    name.value = ''
    datasets.value = [created, ...datasets.value]
    notice.value = `已建立資料集「${created.name}」，可開啟工作區上傳資料檔。`
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    busy.value = false
  }
}

async function applySearch(): Promise<void> {
  await replaceQueryState(router, route, { q: keyword.value })
}

onMounted(loadDatasets)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">數據 / DATASETS</div>
        <h1>資料集清單</h1>
        <p class="muted">資料來源、版本與品質狀態都在資料集工作區管理。</p>
      </div>
      <div class="actions">
        <button type="button" @click="loadDatasets">重新載入</button>
      </div>
    </div>

    <div class="layout cols2">
      <section class="card">
        <h3>搜尋與篩選</h3>
        <div class="formgrid">
          <div class="field">
            <label>關鍵字</label>
            <input v-model="keyword" name="dataset-keyword" maxlength="200" placeholder="名稱或編號">
          </div>
          <div class="field">
            <label>新資料集名稱</label>
            <input v-model="name" name="dataset-name" maxlength="200" placeholder="請輸入資料集名稱">
          </div>
        </div>
        <div class="actions">
          <button type="button" @click="applySearch">🔍 搜尋</button>
          <button type="button" class="primary" :disabled="busy || name === ''" @click="submitDataset">
            建立新資料集
          </button>
        </div>

        <h3 style="margin-top: 24px;">項目清單</h3>
        <p v-if="busy" class="muted">載入中…</p>
        <p v-else-if="visible.length === 0" class="muted">尚無符合條件的資料集。</p>
        <table v-else>
          <thead>
            <tr>
              <th>名稱</th>
              <th>編號</th>
              <th>版本</th>
              <th>總列數</th>
              <th>建立時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in visible" :key="row.id">
              <td>{{ row.name }}</td>
              <td class="mono">{{ row.id }}</td>
              <td>
                <span class="tag">{{ digestOf(row.id).versionCount }}</span>
                <span v-if="digestOf(row.id).unavailableCount !== 0" class="tag bad">
                  不可用 {{ digestOf(row.id).unavailableCount }}
                </span>
              </td>
              <td>{{ digestOf(row.id).totalRows }}</td>
              <td class="muted">{{ row.created_at }}</td>
              <td>
                <RouterLink :to="{ name: 'dataset', params: { id: row.id } }">
                  <button type="button">開啟工作區</button>
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="card">
        <h3>工作區說明</h3>
        <p>資料集工作區提供：</p>
        <div class="row compact"><span>版本清單</span><span class="tag">格式 / 列數 / 指紋</span></div>
        <div class="row compact"><span>資料預覽</span><span class="tag">結構預覽欄位</span></div>
        <div class="row compact"><span>完整性檢核</span><span class="tag">可判定規則</span></div>
        <div class="row compact"><span>版本比較</span><span class="tag">列數 / 欄位差異</span></div>
        <p class="muted" style="margin-top: 12px;">
          檢核與比較只依後端已揭露欄位計算；缺少結構預覽時一律標示「未取得」，不以推測補值。
        </p>
      </section>
    </div>

    <p v-if="error" class="bad" style="margin-top: 16px;">{{ error }}</p>
    <output v-if="notice" class="good" style="display: block; margin-top: 16px;">{{ notice }}</output>
  </section>
</template>

<style scoped>
.compact {
  padding: 10px 0;
}
</style>
