import { describe, expect, it } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '../src/App.vue'
import { useCompatibilityStore } from '../src/state'

describe('T02 Vue stack compatibility', () => {
  it('renders a Vue SFC with Pinia state', async () => {
    const app = createSSRApp(App)
    app.use(createPinia())
    const html = await renderToString(app)
    expect(html).toContain('固定測試結果：7')
  })

  it('isolates state between applications', () => {
    const first = useCompatibilityStore(createPinia())
    const second = useCompatibilityStore(createPinia())
    first.evaluateLinear(3)
    expect(first.result).toBe(7)
    expect(second.result).toBe(0)
  })

  it('navigates using Vue Router memory history', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: App }] })
    await router.push('/')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.matched).toHaveLength(1)
  })
})
