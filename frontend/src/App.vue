<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { checkReadiness, type HealthStatus } from './health'
import { isAuthenticated, logOut } from './lib/session'

const router = useRouter()
const route = useRoute()
const readiness = ref<HealthStatus | 'loading'>('loading')
const primaryNav = [
  { label: '總覽', icon: '◫', route: { name: 'overview' as const } },
  { label: '活動中心', icon: '◷', route: { name: 'activity' as const } },
  { label: '待處理事件', icon: '⚑', route: { name: 'pending' as const } },
  { label: '資源監控', icon: '◔', route: { name: 'resources' as const } },
  { label: '研究', icon: '◈', route: { name: 'research-list' as const } },
  { label: '數據', icon: '▦', route: { name: 'datasets' as const } },
  { label: '發現', icon: '◇', route: { name: 'discoveries' as const } },
  { label: '驗證', icon: '✓', route: { name: 'verification' as const } },
  { label: '記憶', icon: '◎', route: { name: 'memory' as const } },
  { label: '模型', icon: '⬡', route: { name: 'model' as const } },
  { label: '訓練', icon: '↗', route: { name: 'training' as const } },
  { label: '設定', icon: '⚙', route: { name: 'settings' as const } },
]

const currentSection = computed<string>(() => {
  if (route.name === 'overview') return '總覽'
  if (route.name === 'activity') return '活動中心'
  if (route.name === 'pending') return '待處理事件'
  if (route.name === 'resources') return '資源監控'
  if (route.name === 'datasets') return '數據'
  if (route.name === 'research-list' || route.name === 'research-create' || route.name === 'research-workbench') {
    return '研究'
  }
  if (
    route.name === 'discoveries' ||
    route.name === 'discovery-compare' ||
    route.name === 'discovery-latent' ||
    route.name === 'discovery-derivation'
  ) {
    return '發現'
  }
  if (
    route.name === 'verification' ||
    route.name === 'verification-falsify' ||
    route.name === 'verification-inverse' ||
    route.name === 'verification-proof' ||
    route.name === 'verification-graph' ||
    route.name === 'run' ||
    route.name === 'artifact'
  ) {
    return '驗證'
  }
  if (
    route.name === 'memory' ||
    route.name === 'memory-experience' ||
    route.name === 'memory-failure' ||
    route.name === 'memory-recovery' ||
    route.name === 'memory-evolution'
  ) {
    return '記憶'
  }
  if (route.name === 'model') return '模型'
  if (route.name === 'training') return '訓練'
  if (route.name === 'settings') return '設定'
  return '總覽'
})

const crumb = computed<string>(() => {
  if (route.name === 'overview') return 'AXIOM / 總覽 / 系統總覽'
  if (route.name === 'activity') return 'AXIOM / 總覽 / 研究活動中心'
  if (route.name === 'pending') return 'AXIOM / 總覽 / 待處理事件'
  if (route.name === 'resources') return 'AXIOM / 總覽 / 資源監控'
  if (route.name === 'datasets') return 'AXIOM / 數據 / 資料集清單'
  if (route.name === 'discoveries') return 'AXIOM / 發現 / 候選公式庫'
  if (route.name === 'discovery-compare') return 'AXIOM / 發現 / 公式比較'
  if (route.name === 'discovery-latent') return 'AXIOM / 發現 / 隱藏變數探索'
  if (route.name === 'discovery-derivation') return 'AXIOM / 發現 / 研究推演'
  if (route.name === 'verification') return 'AXIOM / 驗證 / 驗證中心'
  if (route.name === 'verification-falsify') return 'AXIOM / 驗證 / 反例搜尋'
  if (route.name === 'verification-inverse') return 'AXIOM / 驗證 / 逆向推導'
  if (route.name === 'verification-proof') return 'AXIOM / 驗證 / 形式化證明'
  if (route.name === 'verification-graph') return 'AXIOM / 驗證 / 證據關聯圖'
  if (route.name === 'memory') return 'AXIOM / 記憶 / 知識庫'
  if (route.name === 'memory-experience') return 'AXIOM / 記憶 / 研究經驗'
  if (route.name === 'memory-failure') return 'AXIOM / 記憶 / 失敗案例'
  if (route.name === 'memory-recovery') return 'AXIOM / 記憶 / 假設恢復'
  if (route.name === 'memory-evolution') return 'AXIOM / 記憶 / 知識演化'
  if (route.name === 'model') return 'AXIOM / 模型 / 模型管理'
  if (route.name === 'training') return 'AXIOM / 訓練 / 訓練中心'
  if (route.name === 'settings') return 'AXIOM / 設定 / 系統設定'
  if (route.name === 'run') return 'AXIOM / 驗證 / 任務詳情'
  if (route.name === 'research-list') return 'AXIOM / 研究 / 研究清單'
  if (route.name === 'research-create') return 'AXIOM / 研究 / 新建研究'
  if (route.name === 'research-workbench') return 'AXIOM / 研究 / 研究工作台'
  if (route.name === 'artifact') return 'AXIOM / 驗證 / 產物詳情'
  return 'AXIOM'
})

async function refreshReadiness(): Promise<void> {
  readiness.value = 'loading'
  readiness.value = await checkReadiness()
}

async function handleLogout(): Promise<void> {
  await logOut()
  await router.push({ name: 'login' })
}

onMounted(refreshReadiness)
</script>

<template>
  <div class="app-shell" :class="{ guest: !isAuthenticated }">
    <template v-if="!isAuthenticated">
      <RouterView />
    </template>
    <template v-else>
      <aside class="sidebar">
        <div class="logo">
          AXIOM
          <small>RESEARCH OS / WORKBENCH</small>
        </div>
        <div class="group">研究導覽</div>
        <RouterLink
          v-for="item in primaryNav"
          :key="item.label"
          class="nav"
          :class="{ active: currentSection === item.label }"
          :to="item.route"
        >
          <span>{{ item.icon }}</span>{{ item.label }}
        </RouterLink>
      </aside>

      <div class="main">
        <header class="top">
          <div>{{ crumb }}</div>
          <div class="actions">
            <span class="tag">服務 {{ readiness === 'ready' ? '已就緒' : readiness === 'loading' ? '檢查中' : '異常' }}</span>
            <button type="button" @click="refreshReadiness">重新檢查</button>
            <button type="button" @click="handleLogout">登出</button>
          </div>
        </header>

        <main class="content">
          <RouterView />
        </main>
      </div>
    </template>
  </div>
</template>

<style scoped>
.app-shell { display: grid; grid-template-columns: 216px 1fr; min-height: 100vh; }
.app-shell.guest { display: block; }
.sidebar { background: #0b182a; border-right: 1px solid #22324b; padding: 24px 12px; }
.logo { font-size: 25px; font-weight: 850; letter-spacing: 3px; color: #fff; padding: 2px 12px 24px; }
.logo small { display: block; letter-spacing: 1px; font-size: 10px; color: #7fa1ce; font-weight: 400; }
.group { font-size: 10px; color: #607998; letter-spacing: 2px; padding: 16px 14px 7px; }
.nav { display: flex; align-items: center; gap: 10px; padding: 11px 13px; border-radius: 8px; margin: 2px 0; color: #91a9c8; }
.nav.active, .nav.router-link-active { background: #12345b; color: #6fb5ff; }
.nav span { width: 22px; font-size: 18px; }
.main { min-width: 0; }
.top { height: 66px; border-bottom: 1px solid #23364e; display: flex; align-items: center; justify-content: space-between; padding: 0 32px; background: #0d1b2c; }
.content { padding: 28px 32px; max-width: 1660px; margin: auto; }
@media (max-width: 900px) {
  .app-shell { grid-template-columns: 64px 1fr; }
  .sidebar { padding: 12px 4px; }
  .logo { font-size: 10px; letter-spacing: 0; }
  .nav { font-size: 0; }
  .nav span { font-size: 20px; }
  .content { padding: 15px; }
}
</style>
