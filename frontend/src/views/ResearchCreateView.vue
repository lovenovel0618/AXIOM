<script setup lang="ts">
/**
 * 新建研究（SSOT SCREEN 06）：以三步精靈建立研究容器、不可變研究版本，再排入 PROFILE 佇列。
 *
 * 精靈只送後端已定義的欄位：研究名稱、研究目的、資料集版本、語意映射、切分、評估政策與研究帳本限額。
 * 自治理策略（AUTO／DEEP）與外部傳輸審核在後端尚無對應欄位或端點，因此不提供、也不以預設值送出；
 * PROFILE 觸發失敗時保留已建立的研究與版本，並顯示後端回覆，不重新建立。
 */
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { createResearch, validateDraft, type Research, type ResearchPurpose, type ResearchVersion } from '../api/research'
import ResearchVersionForm from '../components/ResearchVersionForm.vue'
import { describeError } from '../lib/messages'
import { readQueryString } from '../lib/queryState'
import { client } from '../lib/session'

const route = useRoute()
const router = useRouter()

const PURPOSE_OPTIONS: Array<{ value: ResearchPurpose; label: string; hint: string }> = [
  { value: 'DESCRIPTION', label: 'DESCRIPTION', hint: '描述資料結構與規律，不急著外推。' },
  { value: 'PREDICTION', label: 'PREDICTION', hint: '以觀測切分評估預測表現。' },
  { value: 'MECHANISM', label: 'MECHANISM', hint: '尋找可檢驗的機制假設。' },
]

const step = ref<1 | 2 | 3>(1)
const name = ref('')
const purpose = ref<ResearchPurpose>('DESCRIPTION')
const createdResearch = ref<Research | null>(null)
const createdVersion = ref<ResearchVersion | null>(null)
const submittedName = ref('')
const creating = ref(false)
const queueing = ref(false)
const error = ref('')
const notice = ref('')
const queueRunId = ref('')
const queueStatus = ref('')

const presetDatasetId = readQueryString(route.query, 'dataset')
const presetDatasetVersionId = readQueryString(route.query, 'version')

const canCreateResearch = computed(() => name.value.trim() !== '' && !creating.value)
const purposeHint = computed(
  () => PURPOSE_OPTIONS.find((option) => option.value === purpose.value)?.hint ?? '未取得',
)
const splitSummary = computed(() => {
  const version = createdVersion.value
  if (version === null) return '未取得'
  const split = version.observation_split
  return `fit ${split.fit.length} 列／development ${split.development.length} 列／final_test ${split.final_test.length} 列（${split.kind}，splitter ${split.splitter_version}）`
})

async function createContainer(): Promise<void> {
  if (!canCreateResearch.value) return
  creating.value = true
  error.value = ''
  notice.value = ''
  submittedName.value = name.value.trim()
  try {
    const created = await createResearch(client, submittedName.value)
    createdResearch.value = created
    notice.value = `已建立研究「${created.name}」，識別碼 ${created.id}。`
    step.value = 2
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    creating.value = false
  }
}

function onVersionCreated(version: ResearchVersion): void {
  createdVersion.value = version
  notice.value = `已建立不可變研究版本 ${version.id}，狀態 ${version.status}、revision ${String(version.revision)}。`
  step.value = 3
}

async function queueProfile(): Promise<void> {
  const version = createdVersion.value
  if (version === null || queueing.value) return
  queueing.value = true
  error.value = ''
  notice.value = ''
  try {
    const run = await validateDraft(client, version.id, version.revision)
    queueRunId.value = run.id
    queueStatus.value = run.status
    notice.value = `已排入 PROFILE 任務 ${run.id}，目前狀態 ${run.status}。`
  } catch (cause) {
    error.value = `${describeError(cause)}（版本已建立，可稍後在工作台重試排入。）`
  } finally {
    queueing.value = false
  }
}

function goToWorkbench(): void {
  const research = createdResearch.value
  if (research === null) return
  const version = createdVersion.value
  void router.push({
    name: 'research-workbench',
    params: { id: research.id },
    query: version === null ? {} : { version: version.id },
  })
}

function restart(): void {
  step.value = 1
  name.value = ''
  purpose.value = 'DESCRIPTION'
  createdResearch.value = null
  createdVersion.value = null
  submittedName.value = ''
  queueRunId.value = ''
  queueStatus.value = ''
  error.value = ''
  notice.value = ''
}
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">研究 / 第 6 頁</div>
        <h1>新建研究</h1>
        <p class="muted">研究目標 → 資料來源與語意 → 不可變版本 → 排入 PROFILE 佇列</p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'research-list' }"><button type="button">返回研究清單</button></RouterLink>
        <button type="button" @click="restart">重新開始</button>
      </div>
    </div>

    <div class="steps">
      <div class="step" :class="{ active: step === 1, done: createdResearch !== null }">
        <span class="step-index">1</span>
        <div>
          <b>研究目標</b>
          <div class="muted">名稱與研究目的</div>
        </div>
      </div>
      <div class="step" :class="{ active: step === 2, done: createdVersion !== null }">
        <span class="step-index">2</span>
        <div>
          <b>資料來源與語意</b>
          <div class="muted">版本、欄位映射、切分與預算</div>
        </div>
      </div>
      <div class="step" :class="{ active: step === 3 }">
        <span class="step-index">3</span>
        <div>
          <b>建立版本並排入佇列</b>
          <div class="muted">不可變快照與 PROFILE 任務</div>
        </div>
      </div>
    </div>

    <p v-if="error !== ''" class="alert" role="alert">{{ error }}</p>
    <output v-if="notice !== ''" class="notice">{{ notice }}</output>

    <section v-if="step === 1" class="card">
      <h3>步驟 1：輸入研究目標</h3>
      <div class="formgrid">
        <div class="field">
          <label for="research-name">研究名稱</label>
          <input id="research-name" v-model="name" placeholder="例如：週期結構研究" maxlength="128">
          <p class="muted">名稱會成為研究容器的唯一標示；建立後不可改名。</p>
        </div>
        <div class="field">
          <label for="research-purpose">研究目的</label>
          <select id="research-purpose" v-model="purpose">
            <option v-for="option in PURPOSE_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <p class="muted">{{ purposeHint }}</p>
        </div>
      </div>
      <div class="actions">
        <button type="button" class="primary" :disabled="!canCreateResearch" @click="createContainer">
          {{ creating ? '建立中…' : '建立研究容器並繼續' }}
        </button>
      </div>
      <div class="note">
        研究容器本身不含資料與公式；資料、切分與預算都在下一步的研究版本中固定。
      </div>
    </section>

    <section v-else-if="step === 2 && createdResearch !== null" class="card">
      <h3>步驟 2：選擇資料來源、語意與預算</h3>
      <div class="row">
        <span>研究容器</span>
        <span>{{ submittedName }} <span class="mono">{{ createdResearch.id }}</span></span>
      </div>
      <div class="note">
        精靈只帶入研究目的；資料集、欄位映射、量綱、值域、切分與研究帳本限額都由下方表單指定，
        未通過檢查時不會送出請求。
      </div>
      <ResearchVersionForm
        :research-id="createdResearch.id"
        :preset-purpose="purpose"
        :preset-dataset-id="presetDatasetId === '' ? undefined : presetDatasetId"
        :preset-dataset-version-id="presetDatasetVersionId === '' ? undefined : presetDatasetVersionId"
        @created="onVersionCreated"
      />
    </section>

    <section v-else-if="step === 3 && createdVersion !== null" class="card">
      <h3>步驟 3：建立不可變快照並排入研究佇列</h3>
      <div class="row">
        <span>研究版本</span>
        <span class="mono">{{ createdVersion.id }}</span>
      </div>
      <div class="row">
        <span>狀態 / revision</span>
        <span><span class="tag">{{ createdVersion.status }}</span> revision {{ createdVersion.revision }}</span>
      </div>
      <div class="row">
        <span>資料集版本</span>
        <span class="mono">{{ createdVersion.dataset_version_id }}</span>
      </div>
      <div class="row">
        <span>固定切分</span>
        <span>{{ splitSummary }}</span>
      </div>
      <div class="row">
        <span>研究帳本上限</span>
        <span>
          CPU {{ createdVersion.budget.cpu_seconds }}s · 牆鐘 {{ createdVersion.budget.wall_seconds }}s ·
          Token {{ createdVersion.budget.tokens }} · 候選 {{ createdVersion.budget.candidate_limit }}
        </span>
      </div>
      <div class="row">
        <span>評估政策雜湊</span>
        <span class="mono">{{ createdVersion.evaluation_policy_hash }}</span>
      </div>

      <p class="muted">
        PROFILE 任務會讀取結構與品質概況；後端若未啟用該能力會回 503，此時版本仍存在，可在工作台重試。
      </p>
      <div class="actions">
        <button type="button" class="primary" :disabled="queueing" @click="queueProfile">
          {{ queueing ? '排入中…' : '排入 PROFILE 佇列' }}
        </button>
        <button type="button" @click="goToWorkbench">前往研究工作台</button>
      </div>
      <div v-if="queueRunId !== ''" class="note">
        任務 <span class="mono">{{ queueRunId }}</span> 狀態 <span class="tag">{{ queueStatus }}</span>；
        後續事件與候選分支會出現在工作台流程圖。
      </div>
    </section>
  </section>
</template>

<style scoped>
.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.step {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid #24384f;
  border-radius: 10px;
  padding: 12px 14px;
  background: #0e1c2f;
}

.step.active {
  border-color: var(--accent);
}

.step.done .step-index {
  background: var(--ok);
  border-color: var(--ok);
  color: #04121f;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid #35506f;
  font-weight: 700;
}

.alert {
  padding: 10px 12px;
  border-radius: 8px;
  background: #3a1a22;
  color: #ffb3c0;
}

.notice {
  display: block;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 12px;
  background: #12283f;
  color: #cfe3ff;
}

.card {
  margin-top: 4px;
}

@media (max-width: 1200px) {
  .steps {
    grid-template-columns: 1fr;
  }
}
</style>
