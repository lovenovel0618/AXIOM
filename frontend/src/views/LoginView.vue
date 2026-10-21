<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { describeError } from '../lib/messages'
import { logIn } from '../lib/session'

const router = useRouter()
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await logIn(username.value, password.value)
    await router.push({ name: 'datasets' })
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="login">
    <h1>登入 AXIOM</h1>
    <p class="hint">使用資料庫中已啟用的帳號登入，登入後即可管理資料集與上傳檔案。</p>
    <form @submit.prevent="submit">
      <label>
        帳號
        <input v-model="username" name="username" autocomplete="username" maxlength="150" required>
      </label>
      <label>
        密碼
        <input v-model="password" type="password" name="password" autocomplete="current-password" required>
      </label>
      <p v-if="error" class="alert" role="alert">{{ error }}</p>
      <button type="submit" :disabled="busy">{{ busy ? '登入中…' : '登入' }}</button>
    </form>
  </section>
</template>

<style scoped>
.login {
  max-width: 26rem;
  margin: 4rem auto;
  padding: 1.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.75rem;
}
h1 {
  margin-top: 0;
  font-size: 1.5rem;
}
.hint {
  color: var(--text-muted);
  font-size: 0.9rem;
}
form {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.9rem;
}
.alert {
  margin: 0;
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--danger-surface);
  color: var(--danger);
}
</style>
