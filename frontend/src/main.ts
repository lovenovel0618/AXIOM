import { createApp } from 'vue'
import App from './App.vue'
import { restoreSession } from './lib/session'
import { router } from './router'
import './style.css'

await restoreSession()
createApp(App).use(router).mount('#app')
