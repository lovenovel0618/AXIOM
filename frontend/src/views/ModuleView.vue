<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

interface ModuleCard {
  title: string
  body: string
  bullets: string[]
}

interface ModuleConfig {
  section: string
  title: string
  summary: string
  cards: ModuleCard[]
  actions: Array<{ label: string; to: { name: string; params?: Record<string, string> } }>
}

const route = useRoute()

const configs: Record<string, ModuleConfig> = {
  overview: {
    section: '總覽',
    title: '系統總覽',
    summary: '集中查看研究、數據、驗證與知識模組的當前入口。',
    actions: [
      { label: '前往研究', to: { name: 'researches' } },
      { label: '前往資料', to: { name: 'datasets' } },
    ],
    cards: [
      {
        title: '研究工作流',
        body: '從資料集建立研究容器、接研究版本、再進入工作台分析。',
        bullets: ['建立研究清單', '建立研究容器', '檢視研究工作台'],
      },
      {
        title: '數據管理',
        body: '維護資料集、版本、匯入任務與一鍵分析入口。',
        bullets: ['建立資料集', '上傳版本', '啟動分析'],
      },
      {
        title: '驗證與證據',
        body: '查看任務詳情、事件、產物與證據鏈。',
        bullets: ['任務事件追蹤', '產物 metadata', '後續接證據關聯圖'],
      },
    ],
  },
  discoveries: {
    section: '發現',
    title: '發現中心',
    summary: '承接候選公式、分支假設與可反證工作流。',
    actions: [{ label: '回研究清單', to: { name: 'researches' } }],
    cards: [
      { title: '候選公式', body: '後續會接 SEARCH 候選與公式瀏覽。', bullets: ['排名', '來源', '驗證狀態'] },
      { title: '假設分支', body: '將接研究分支圖與反證要求。', bullets: ['父子分支', '狀態', '決策記錄'] },
      { title: '推導與比較', body: '保留給公式比較與關聯探索。', bullets: ['複雜度', '參數精度', '適用範圍'] },
    ],
  },
  verification: {
    section: '驗證',
    title: '驗證中心',
    summary: '查看驗證結果、證據包與最終評估進度。',
    actions: [{ label: '前往研究', to: { name: 'researches' } }],
    cards: [
      { title: '任務監控', body: '查看 PROFILE / SEARCH / VALIDATE 任務事件與狀態。', bullets: ['SSE 事件', '重連狀態', '取消操作'] },
      { title: '證據產物', body: '維護 evidence bundle、quality report 與 artifact 入口。', bullets: ['metadata', '存取等級', '下載'] },
      { title: '最終評估', body: '保留給 final evaluation 與比對結論。', bullets: ['支持度', 'metric version', '結論狀態'] },
    ],
  },
  memory: {
    section: '記憶',
    title: '知識與記憶',
    summary: '保留給研究經驗、知識庫與跨任務回憶模組。',
    actions: [{ label: '回總覽', to: { name: 'overview' } }],
    cards: [
      { title: '研究經驗', body: '追蹤歷次研究的可重用結論。', bullets: ['版本', '證據', '適用條件'] },
      { title: '知識庫', body: '沉澱規律、推理與驗證紀錄。', bullets: ['來源', '引用', '一致性'] },
      { title: '工作記錄', body: '保留未來串接任務中心與軌跡圖。', bullets: ['時間線', '任務', '產物'] },
    ],
  },
  model: {
    section: '模型',
    title: '模型管理',
    summary: '保留模型版本、能力配置與執行環境檢視。',
    actions: [{ label: '回總覽', to: { name: 'overview' } }],
    cards: [
      { title: '模型清單', body: '後續列出研究、驗證、推理用模型。', bullets: ['版本', '來源', '狀態'] },
      { title: '執行設定', body: '保留 GPU / token / 記憶體限制設定。', bullets: ['預算', '上限', '隔離'] },
      { title: '使用記錄', body: '統計模型在各工作流的使用情況。', bullets: ['次數', '耗時', '成本'] },
    ],
  },
  training: {
    section: '訓練',
    title: '訓練中心',
    summary: '保留資料整理、訓練任務與品質檢查流程。',
    actions: [{ label: '回總覽', to: { name: 'overview' } }],
    cards: [
      { title: '訓練任務', body: '後續列出訓練批次、狀態與輸出。', bullets: ['排程', '進度', '結果'] },
      { title: '資料準備', body: '保留訓練資料集整理與品質檢查。', bullets: ['切分', '來源', '品質'] },
      { title: '評估回圈', body: '回接驗證結果作為訓練迭代依據。', bullets: ['指標', '回饋', '迭代'] },
    ],
  },
  settings: {
    section: '設定',
    title: '系統設定',
    summary: '集中管理服務狀態、帳號與系統參數。',
    actions: [{ label: '回總覽', to: { name: 'overview' } }],
    cards: [
      { title: '服務狀態', body: '查看 API / worker / database 就緒情況。', bullets: ['health', 'reconnect', 'logs'] },
      { title: '帳號與權限', body: '保留管理者與租戶配置入口。', bullets: ['角色', '租戶', '權限'] },
      { title: '系統參數', body: '保留策略與行為設定入口。', bullets: ['預設值', '限制', '安全'] },
    ],
  },
}

const config = computed<ModuleConfig>(() => {
  const name = typeof route.name === 'string' ? route.name : 'overview'
  return configs[name] ?? configs.overview!
})
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">{{ config.section }} / MODULE</div>
        <h1>{{ config.title }}</h1>
        <p class="muted">{{ config.summary }}</p>
      </div>
      <div class="actions">
        <RouterLink v-for="action in config.actions" :key="action.label" :to="action.to">
          <button type="button" class="primary">{{ action.label }}</button>
        </RouterLink>
      </div>
    </div>

    <div class="layout cols3">
      <section v-for="card in config.cards" :key="card.title" class="card">
        <h3>{{ card.title }}</h3>
        <p>{{ card.body }}</p>
        <div class="row" v-for="bullet in card.bullets" :key="bullet">
          <span>{{ bullet }}</span>
          <span class="tag">已規劃</span>
        </div>
      </section>
    </div>
  </section>
</template>
