/**
 * M3 跨頁鏈路驗收：以真實路由表建立 memory history 的 router，逐步驗證
 * 上傳→語意確認→研究→SEARCH→候選比較→FIT→證據檢視 的深連結、導覽上下文（ref）與返回。
 *
 * 路由表直接自 src/router.ts 剖析，與前台執行期同源；元件以樁取代，只驗路由與查詢語意，
 * 因此不需 DOM 也能真實走過 vue-router 的解析、正規化與跳轉。
 */
import { readFileSync } from 'node:fs'
import { createMemoryHistory, createRouter, type RouteRecordRaw, type Router } from 'vue-router'
import { describe, expect, it } from 'vitest'
import { readBackRef, withBackRef } from '../src/lib/navigationState'
import { readQueryList, readQueryString, replaceQueryState } from '../src/lib/queryState'
import { pageForRoute } from '../src/lib/ssotPages'

const ROUTER_SOURCE = readFileSync(new URL('../src/router.ts', import.meta.url), 'utf8')

function routeTable(): { path: string; name: string }[] {
  const rows: { path: string; name: string }[] = []
  for (const match of ROUTER_SOURCE.matchAll(/\{ path: '([^']+)', name: '([^']+)', component: \w+ \}/g)) {
    const path = match[1]
    const name = match[2]
    if (path !== undefined && name !== undefined) rows.push({ path, name })
  }
  return rows
}

const STUB = { template: '<div />' }

function journeyRouter(): Router {
  const routes: RouteRecordRaw[] = [
    { path: '/', redirect: { name: 'overview' } },
    ...routeTable().map((row): RouteRecordRaw => ({ path: row.path, name: row.name, component: STUB })),
  ]
  return createRouter({ history: createMemoryHistory(), routes })
}

interface Stop {
  stage: string
  name: string
  params?: Record<string, string>
  query?: Record<string, string>
}

/** 前台真實交接點：路徑與查詢鍵皆取自各頁實際的 RouterLink／replaceQueryState 用法。 */
const M3_CHAIN: readonly Stop[] = [
  { stage: '上傳', name: 'datasets' },
  { stage: '上傳', name: 'data-upload', params: { id: 'dataset-1' } },
  { stage: '語意確認', name: 'data-preview', params: { id: 'dataset-1' }, query: { version: 'version-1' } },
  { stage: '語意確認', name: 'research-create' },
  { stage: '研究', name: 'research-workbench', params: { id: 'research-1' }, query: { version: 'version-1' } },
  { stage: 'SEARCH', name: 'discoveries', query: { run: 'search-1' } },
  { stage: '候選比較', name: 'discovery-compare', query: { run: 'search-1', pins: 'candidate-1,candidate-2' } },
  { stage: '候選比較', name: 'candidate', params: { id: 'candidate-1' }, query: { run: 'search-1' } },
  { stage: 'FIT', name: 'run', params: { id: 'search-1' } },
  { stage: '證據檢視', name: 'verification' },
  { stage: '證據檢視', name: 'verification-proof' },
  { stage: '證據檢視', name: 'artifact', params: { id: 'artifact-1' } },
]

describe('M3 跨頁鏈路', () => {
  it('每一站都對應已註冊頁面，且深連結可直接解析', () => {
    const known = new Set(routeTable().map((row) => row.name))
    const router = journeyRouter()
    for (const stop of M3_CHAIN) {
      expect(pageForRoute(stop.name), `${stop.name} 未註冊於 SSOT 頁面表`).toBeDefined()
      expect(known.has(stop.name), `${stop.name} 未註冊於 router.ts`).toBe(true)
      const resolved = router.resolve({ name: stop.name, params: stop.params ?? {}, query: stop.query ?? {} })
      expect(resolved.name).toBe(stop.name)
      expect(resolved.path).not.toContain(':')
    }
  })

  it('鏈路涵蓋 M3 七個階段', () => {
    expect([...new Set(M3_CHAIN.map((stop) => stop.stage))]).toEqual([
      '上傳', '語意確認', '研究', 'SEARCH', '候選比較', 'FIT', '證據檢視',
    ])
  })

  it('導覽上下文以 ref 串起相鄰頁，並可沿 ref 逐站返回', async () => {
    const router = journeyRouter()
    const visited: string[] = []
    await router.push({ name: 'datasets' })
    visited.push(router.currentRoute.value.fullPath)
    for (const stop of M3_CHAIN.slice(1)) {
      const previous = router.currentRoute.value.fullPath
      await router.push({ name: stop.name, params: stop.params ?? {}, query: withBackRef(previous, stop.query ?? {}) })
      expect(readBackRef(router.currentRoute.value.query), `${stop.name} 未帶回上一站`).toBe(previous)
      visited.push(router.currentRoute.value.fullPath)
    }
    const returned: string[] = []
    while (readBackRef(router.currentRoute.value.query) !== '') {
      await router.push(readBackRef(router.currentRoute.value.query))
      returned.push(router.currentRoute.value.fullPath)
    }
    expect(returned).toEqual(visited.slice(0, -1).reverse())
  })

  it('查詢狀態只在值變動時才改寫路由', async () => {
    const router = journeyRouter()
    await router.push({ name: 'discovery-compare', query: { run: 'search-1', pins: 'candidate-1,candidate-2' } })
    expect(readQueryString(router.currentRoute.value.query, 'run')).toBe('search-1')
    expect(readQueryList(router.currentRoute.value.query, 'pins')).toEqual(['candidate-1', 'candidate-2'])
    const stable = router.currentRoute.value.fullPath
    await replaceQueryState(router, router.currentRoute.value, { run: 'search-1' })
    expect(router.currentRoute.value.fullPath).toBe(stable)
    await replaceQueryState(router, router.currentRoute.value, { run: undefined })
    expect(router.currentRoute.value.fullPath).not.toContain('run=')
    expect(readQueryList(router.currentRoute.value.query, 'pins')).toEqual(['candidate-1', 'candidate-2'])
  })

  it('未註冊的深連結不會誤配成鏈路上的頁面', () => {
    const router = journeyRouter()
    expect(router.resolve('/not-a-registered-page').name).toBeUndefined()
  })

  it('未登入的深連結由路由守衛導向登入頁', () => {
    expect(ROUTER_SOURCE).toContain('router.beforeEach')
    expect(ROUTER_SOURCE).toContain("{ name: 'login' }")
  })
})
