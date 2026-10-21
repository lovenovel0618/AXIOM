<script setup lang="ts">
/**
 * 研究工作台（語意確認）：建立研究容器、固定不可變草稿、觸發 PROFILE。
 * 版本一旦建立即不可變；觸發需帶目前控制 revision，後端仍是唯一權威。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  createResearch,
  getResearchVersion,
  listResearchVersionRuns,
  listResearches,
  listResearchVersions,
  validateDraft,
  type Research,
  type ResearchVersion,
  type ResearchVersionStatus,
} from '../api/research'
import { isTerminal, type Run, type RunStatus } from '../api/runs'
import ResearchVersionForm from '../components/ResearchVersionForm.vue'
import { describeError } from '../lib/messages'
import { client } from '../lib/session'

const route = useRoute()
const router = useRouter()

const researches = ref<Research[]>([])
const versions = ref<ResearchVersion[]>([])
const selected = ref<Research | null>(null)
const selectedVersion = ref<ResearchVersion | null>(null)
const runs = ref<Run[]>([])
const name = ref('')
const loading = ref(false)
const triggering = ref(false)
const error = ref('')
const notice = ref('')

const versionStatusLabel: Record<ResearchVersionStatus, string> = {
  DRAFT: '草稿',
  VALIDATING: '驗證中',
  READY: '就緒',
  QUEUED: '排隊中',
  RUNNING: '執行中',
  REVIEW: '待審核',
  PUBLISHED: '已發布',
  FAILED: '失敗',
  CANCELLED: '已取消',
}

const runStatusLabel: Record<RunStatus, string> = {
  QUEUED: '排隊中',
  RUNNING: '執行中',
  CANCEL_REQUESTED: '取消處理中',
  SUCCEEDED: '成功',
  FAILED: '失敗',
  CANCELLED: '已取消',
}

const canTrigger = computed<boolean>(
  () => selectedVersion.value !== null && selectedVersion.value.status === 'DRAFT' && !triggering.value,
)

async function loadResearches(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    researches.value = (await listResearches(client)).items
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

async function submitResearch(): Promise<void> {
  if (name.value.trim() === '' || loading.value) return
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const created = await createResearch(client, name.value.trim())
    name.value = ''
    researches.value = [created, ...researches.value]
    notice.value = `已建立研究「${created.name}」。`
    await select(created)
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

async function select(research: Research): Promise<void> {
  selected.value = research
  selectedVersion.value = null
  runs.value = []
  versions.value = []
  error.value = ''
  notice.value = ''
  if (route.params.id !== research.id) {
    await router.replace({ name: 'researches', params: { id: research.id } })
  }
  await reloadVersions()
}

async function reloadVersions(): Promise<void> {
  const research = selected.value
  if (research === null) return
  try {
    versions.value = (await listResearchVersions(client, research.id)).items
  } catch (cause) {
    error.value = describeError(cause)
  }
}

async function pickVersion(version: ResearchVersion): Promise<void> {
  selectedVersion.value = version
  runs.value = []
  error.value = ''
  notice.value = ''
  await reloadRuns()
}

async function reloadRuns(): Promise<void> {
  const version = selectedVersion.value
  if (version === null) return
  try {
    runs.value = (await listResearchVersionRuns(client, version.id)).items
  } catch (cause) {
    error.value = describeError(cause)
  }
}

async function refreshVersion(): Promise<void> {
  const version = selectedVersion.value
  if (version === null) return
  try {
    selectedVersion.value = await getResearchVersion(client, version.id)
    await reloadRuns()
  } catch (cause) {
    error.value = describeError(cause)
  }
}

async function trigger(): Promise<void> {
  const version = selectedVersion.value
  if (version === null || triggering.value) return
  triggering.value = true
  error.value = ''
  notice.value = ''
  try {
    const fresh = await getResearchVersion(client, version.id)
    selectedVersion.value = fresh
    const run = await validateDraft(client, fresh.id, fresh.revision)
    notice.value = `已排入 PROFILE 任務（狀態 ${runStatusLabel[run.status]}）。`
    await reloadRuns()
  } catch (cause) {
    error.value = describeError(cause)
    await refreshVersion()
  } finally {
    triggering.value = false
  }
}

async function onVersionCreated(version: ResearchVersion): Promise<void> {
  versions.value = [version, ...versions.value]
  await pickVersion(version)
}

watch(
  () => route.params.id,
  (value) => {
    const id = typeof value === 'string' ? value : ''
    if (id === '') return
    if (selected.value?.id === id) return
    const found = researches.value.find((row) => row.id === id)
    if (found !== undefined) void select(found)
  },
)

onMounted(async () => {
  await loadResearches()
  const id = typeof route.params.id === 'string' ? route.params.id : ''
  if (id === '') return
  const found = researches.value.find((row) => row.id === id)
  if (found !== undefined) await select(found)
})
</script>

<template>
  <div class="grid">
    <section class="panel">
      <div class="panel-head">
        <h2>研究</h2>
        <button type="button" :disabled="loading" @click="loadResearches">重新載入</button>
      </div>

      <form class="create" @submit.prevent="submitResearch">
        <label>
          新研究名稱
          <input v-model="name" name="research-name" maxlength="200" required>
        </label>
        <button type="submit" :disabled="loading || name.trim() === ''">建立研究</button>
      </form>

      <p v-if="loading" class="muted">載入中…</p>
      <p v-else-if="researches.length === 0" class="muted">尚無研究，請先建立一個。</p>
      <ul v-else class="list">
        <li v-for="row in researches" :key="row.id">
          <button
            type="button"
            :aria-pressed="selected?.id === row.id"
            :class="{ active: selected?.id === row.id }"
            @click="select(row)"
          >
            <span class="name">{{ row.name }}</span>
            <span class="mono id">{{ row.id }}</span>
          </button>
        </li>
      </ul>
    </section>

    <section class="panel">
      <h2>研究版本</h2>
      <template v-if="selected === null">
        <p class="muted">請從左側選擇一個研究。</p>
      </template>
      <template v-else>
        <p class="muted">目前研究：<strong>{{ selected.name }}</strong></p>

        <div class="panel-head">
          <h3>版本</h3>
          <button type="button" @click="reloadVersions">重新載入</button>
        </div>
        <p v-if="versions.length === 0" class="muted">此研究尚無版本。</p>
        <ul v-else class="versions">
          <li v-for="row in versions" :key="row.id">
            <button
              type="button"
              :aria-pressed="selectedVersion?.id === row.id"
              :class="{ active: selectedVersion?.id === row.id }"
              @click="pickVersion(row)"
            >
              <span class="mono id">{{ row.id }}</span>
              <span>{{ versionStatusLabel[row.status] }}（{{ row.status }}）</span>
              <span class="muted">控制版本 {{ row.revision }}</span>
            </button>
          </li>
        </ul>

        <ResearchVersionForm :research-id="selected.id" @created="onVersionCreated" />

        <template v-if="selectedVersion !== null">
          <div class="panel-head">
            <h3>版本內容</h3>
            <button type="button" @click="refreshVersion">重新載入</button>
          </div>
          <dl class="facts">
            <dt>狀態</dt>
            <dd>{{ versionStatusLabel[selectedVersion.status] }}（{{ selectedVersion.status }}）</dd>
            <dt>控制版本</dt>
            <dd class="mono">{{ selectedVersion.revision }}</dd>
            <dt>目的</dt>
            <dd>{{ selectedVersion.purpose }}</dd>
            <dt>切分</dt>
            <dd>
              {{ selectedVersion.observation_split.kind }}／fit {{ selectedVersion.observation_split.fit.length }} 列／development
              {{ selectedVersion.observation_split.development.length }} 列／final_test
              {{ selectedVersion.observation_split.final_test.length }} 列／splitter
              <span class="mono">{{ selectedVersion.observation_split.splitter_version }}</span>
            </dd>
            <dt>評估政策雜湊</dt>
            <dd class="mono">{{ selectedVersion.evaluation_policy_hash }}</dd>
          </dl>

          <h3>觸發 PROFILE 驗證</h3>
          <p class="muted">
            版本為草稿時才能觸發；送出會帶目前控制版本 {{ selectedVersion.revision }}。後端未啟用 PROFILE 時回 503，狀態已變更則回 412。
          </p>
          <button type="button" :disabled="!canTrigger" @click="trigger">
            {{ triggering ? '送出中…' : '觸發 PROFILE 驗證' }}
          </button>

          <h3>版本任務</h3>
          <p v-if="runs.length === 0" class="muted">此版本尚無任務。</p>
          <ul v-else class="list">
            <li v-for="row in runs" :key="row.id">
              <RouterLink :to="{ name: 'run', params: { id: row.id } }">
                {{ row.type }}／{{ runStatusLabel[row.status] }}
              </RouterLink>
              <span class="muted mono">{{ row.id }}</span>
            </li>
          </ul>
        </template>
      </template>
    </section>
  </div>

  <p v-if="error" class="alert" role="alert">{{ error }}</p>
  <p v-if="notice" class="notice" role="status">{{ notice }}</p>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: minmax(16rem, 1fr) minmax(20rem, 2fr);
  gap: 1.25rem;
  align-items: start;
}
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  padding: 1.25rem;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
h2 {
  margin: 0 0 0.75rem;
  font-size: 1.15rem;
}
h3 {
  margin: 1.25rem 0 0.5rem;
  font-size: 1rem;
}
.create {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
  font-size: 0.9rem;
}
.create label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.list,
.versions {
  list-style: none;
  margin: 0 0 1rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.list button,
.versions button {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.2rem;
  text-align: left;
}
.list button.active,
.versions button.active {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent);
}
.name {
  font-weight: 600;
}
.id {
  color: var(--text-muted);
}
.facts {
  display: grid;
  grid-template-columns: minmax(8rem, auto) 1fr;
  gap: 0.35rem 1rem;
  margin: 0.75rem 0 0;
}
.facts dt {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.facts dd {
  margin: 0;
  word-break: break-all;
}
.muted {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.alert {
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--danger-surface);
  color: var(--danger);
}
.notice {
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--surface-muted);
}
@media (max-width: 48rem) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
