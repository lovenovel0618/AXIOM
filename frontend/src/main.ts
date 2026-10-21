import { createApp } from 'vue'
import App from './App.vue'
import { restoreSession } from './lib/session'
import { router } from './router'
import './style.css'

async function bootstrap(): Promise<void> {
  await restoreSession()
  createApp(App).use(router).mount('#app')
}

void bootstrap()
