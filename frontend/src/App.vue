<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { checkReadiness, type HealthStatus } from './health'

const status = ref<HealthStatus | 'loading'>('loading')
async function refresh(): Promise<void> {
  status.value = 'loading'
  status.value = await checkReadiness()
}
onMounted(refresh)
</script>

<template>
  <main>
    <p class="eyebrow">AXIOM · 本機開發環境</p>
    <h1>研究工作台</h1>
    <p>工程基礎已建立，研究功能將依開發流程逐步開放。</p>
    <section aria-label="服務狀態" aria-live="polite" :aria-busy="status === 'loading'">
      <h2>服務狀態</h2>
      <p v-if="status === 'loading'">正在檢查服務…</p>
      <p v-else-if="status === 'ready'">服務已就緒</p>
      <p v-else>服務暫時無法使用，請稍後重試。</p>
      <button :disabled="status === 'loading'" @click="refresh">重新檢查</button>
    </section>
  </main>
</template>

<style scoped>
main { max-width: 44rem; margin: 10vh auto; padding: 2rem; font-family: system-ui, sans-serif; color: #18332e; }
.eyebrow { font-size: 0.85rem; letter-spacing: 0.08em; color: #47685d; }
h1 { font-size: 2.5rem; }
section { margin-top: 3rem; padding: 1.5rem; background: #eef5f1; border-radius: 1rem; }
h2 { font-size: 1.1rem; }
button { padding: 0.65rem 1rem; border: 1px solid #47685d; border-radius: 0.4rem; background: white; cursor: pointer; }
button:disabled { cursor: wait; opacity: 0.6; }
</style>
