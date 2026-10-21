<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { checkReadiness, type HealthStatus } from './health'
import { isAuthenticated, logOut } from './lib/session'

const router = useRouter()
const readiness = ref<HealthStatus | 'loading'>('loading')

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
  <div class="shell">
    <header>
      <div class="brand">AXIOM 研究工作台</div>
      <nav aria-label="主要導覽">
        <RouterLink v-if="isAuthenticated" :to="{ name: 'datasets' }">資料集</RouterLink>
        <RouterLink v-if="isAuthenticated" :to="{ name: 'researches' }">研究</RouterLink>
        <button v-if="isAuthenticated" type="button" @click="handleLogout">登出</button>
      </nav>
    </header>
    <main>
      <RouterView />
    </main>
    <footer aria-live="polite" :aria-busy="readiness === 'loading'">
      <span class="mono">服務狀態：</span>
      <span v-if="readiness === 'loading'">檢查中…</span>
      <span v-else-if="readiness === 'ready'">已就緒</span>
      <span v-else>暫時無法使用</span>
      <button type="button" :disabled="readiness === 'loading'" @click="refreshReadiness">重新檢查</button>
    </footer>
  </div>
</template>

<style scoped>
.shell {
  max-width: 72rem;
  margin: 0 auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.75rem;
}
.brand {
  font-weight: 600;
  letter-spacing: 0.04em;
}
nav {
  display: flex;
  align-items: center;
  gap: 1rem;
}
main {
  flex: 1;
  padding: 1.5rem 0;
}
footer {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border-top: 1px solid var(--border);
  padding-top: 0.75rem;
  color: var(--text-muted);
  font-size: 0.9rem;
}
</style>
