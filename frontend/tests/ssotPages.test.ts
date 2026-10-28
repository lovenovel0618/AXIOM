/**
 * M3 逐頁驗收：以 docs/AXIOM_UIUX_重製版/assets/pages.json 為權威，逐頁比對前台實作。
 *
 * 目的不是重跑畫面，而是擋住三類退化：SSOT 頁面漏做或做錯路由、選單與標題出現英文、
 * 以及用設計圖靜態圖片冒充真實組件（已於專案內明確否決的做法）。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { SSOT_PAGES, SUPPORT_PAGES, pageForRoute } from '../src/lib/ssotPages'

interface SsotPageEntry {
  id: number
  category: string
  title: string
  file: string
}

interface DeclaredRoute {
  path: string
  name: string
  component: string
}

function readSource(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')
}

const pagesJson = JSON.parse(
  readSource('../../docs/AXIOM_UIUX_重製版/assets/pages.json'),
) as SsotPageEntry[]

const routerSource = readSource('../src/router.ts')
const appSource = readSource('../src/App.vue')

/** router.ts 的 import 名稱 → 視圖檔相對路徑（如 TestView → views/TestView.vue）。 */
const viewByImport = new Map<string, string>()
for (const match of routerSource.matchAll(/import\s+(\w+)\s+from\s+'\.\/(views\/[^']+)'/g)) {
  const importName = match[1]
  const viewPath = match[2]
  if (importName === undefined || viewPath === undefined) continue
  viewByImport.set(importName, viewPath)
}

const declaredRoutes: DeclaredRoute[] = []
for (const match of routerSource.matchAll(/path: '([^']+)', name: '([^']+)', component: (\w+)/g)) {
  const path = match[1]
  const name = match[2]
  const component = match[3]
  if (path === undefined || name === undefined || component === undefined) continue
  declaredRoutes.push({ path, name, component })
}

/** App.vue 左側導覽：標籤與目標路由。 */
const navEntries: Array<{ label: string; routeName: string }> = []
for (const match of appSource.matchAll(/label: '([^']+)', icon: '[^']*', route: \{ name: '([^']+)'/g)) {
  const label = match[1]
  const routeName = match[2]
  if (label === undefined || routeName === undefined) continue
  navEntries.push({ label, routeName })
}

const ALL_PAGES = [...SSOT_PAGES, ...SUPPORT_PAGES]
const registryByRoute = new Map(ALL_PAGES.map((page) => [page.routeName, page]))
const routeByName = new Map(declaredRoutes.map((route) => [route.name, route]))
const viewPathForRoute = (routeName: string): string | null => {
  const route = routeByName.get(routeName)
  if (!route) return null
  return viewByImport.get(route.component) ?? null
}

/** 掃描 src 下所有 .vue，回傳檔名 → 內容。 */
function readViewSources(): Map<string, string> {
  const files = readdirSync(fileURLToPath(new URL('../src/views', import.meta.url))).filter((name) => name.endsWith('.vue'))
  return new Map(files.map((name) => [name, readSource(`../src/views/${name}`)]))
}

const viewSources = readViewSources()

/** 各 .vue 宣告的 SSOT 頁碼（"SSOT SCREEN 07" 形式的標註）。 */
function declaredSsotIds(source: string): number[] {
  return [...source.matchAll(/SSOT SCREEN (\d{2})/g)].map((match) => Number(match[1]))
}

const hasAsciiLetter = (text: string): boolean => /[A-Za-z]/.test(text)

describe('SSOT 逐頁對齊', () => {
  it('pages.json 為 40 頁且註冊表逐頁逐字對應', () => {
    expect(pagesJson).toHaveLength(40)
    expect(pagesJson.map((page) => page.id)).toEqual([...Array(40).keys()].map((index) => index + 1))
    expect(SSOT_PAGES).toHaveLength(40)

    for (const entry of pagesJson) {
      const page = SSOT_PAGES.find((candidate) => candidate.id === entry.id)
      expect(page, `缺少 SSOT 第 ${entry.id} 頁的註冊`).toBeDefined()
      expect(page?.ssotTitle).toBe(entry.title)
      expect(page?.category).toBe(entry.category)
    }
    // 一頁只註冊一次，避免同一頁被兩條路由佔用
    expect(new Set(SSOT_PAGES.map((page) => page.id)).size).toBe(40)
    expect(new Set(SSOT_PAGES.map((page) => page.routeName)).size).toBe(40)
  })

  it('每個 SSOT 頁都有路由、視圖與對應的頁碼標註', () => {
    for (const page of SSOT_PAGES) {
      const marker = `SSOT SCREEN ${String(page.id).padStart(2, '0')}`
      const viewPath = viewPathForRoute(page.routeName)
      expect(viewPath, `路由 ${page.routeName} 缺少視圖`).not.toBeNull()

      const fileName = viewPath?.split('/').pop() ?? ''
      const source = viewSources.get(fileName)
      expect(source, `找不到視圖檔 ${viewPath}`).toBeDefined()
      expect(source, `${viewPath} 未標註 ${marker}`).toContain(marker)
    }
  })

  it('視圖的頁碼標註與路由註冊一對一，無張冠李戴', () => {
    const owner = new Map<number, string>()
    for (const [fileName, source] of viewSources) {
      for (const id of declaredSsotIds(source)) {
        expect(owner.has(id), `SSOT 第 ${id} 頁被多個視圖標註`).toBe(false)
        owner.set(id, fileName)
      }
    }

    for (let id = 1; id <= 40; id += 1) {
      const page = SSOT_PAGES.find((candidate) => candidate.id === id)
      const fileName = owner.get(id)
      expect(fileName, `SSOT 第 ${id} 頁沒有任何視圖標註`).toBeDefined()
      const expected = viewPathForRoute(page?.routeName ?? '')?.split('/').pop()
      expect(fileName).toBe(expected)
    }
    expect(owner.size).toBe(40)
  })

  it('路由與註冊表雙向一致，沒有孤兒路由', () => {
    for (const route of declaredRoutes) {
      expect(registryByRoute.has(route.name), `路由 ${route.name} 未登記在 ssotPages`).toBe(true)
    }
    for (const page of ALL_PAGES) {
      expect(routeByName.has(page.routeName), `註冊表 ${page.routeName} 沒有對應路由`).toBe(true)
    }
    // 登入頁以外的 SSOT 頁都要看得到實際檔案
    for (const page of SSOT_PAGES) {
      expect(viewPathForRoute(page.routeName)).not.toBeNull()
    }
  })
})

describe('介面文字與真實組件', () => {
  it('註冊表標題全為繁體中文（僅允許品牌名 AXIOM）', () => {
    for (const page of ALL_PAGES) {
      expect(page.title.replace(/AXIOM/g, '')).not.toMatch(/[A-Za-z]/)
      expect(page.navLabel.replace(/AXIOM/g, '')).not.toMatch(/[A-Za-z]/)
    }
  })

  it('左側導覽標籤皆為註冊表模組名且不含英文', () => {
    expect(navEntries).toHaveLength(12)
    const labels = new Set(ALL_PAGES.map((page) => page.navLabel))
    for (const entry of navEntries) {
      expect(hasAsciiLetter(entry.label), `導覽標籤「${entry.label}」含英文`).toBe(false)
      expect(labels.has(entry.label), `導覽標籤「${entry.label}」不在註冊表`).toBe(true)
      // 導覽需要高亮所在模組，因此目標路由的 navLabel 必須等於標籤
      expect(pageForRoute(entry.routeName)?.navLabel).toBe(entry.label)
    }
  })

  it('每個頁面標題與註冊表一致', () => {
    const titles = new Set(ALL_PAGES.map((page) => page.title))
    for (const [fileName, source] of viewSources) {
      const match = /<h1[^>]*>([^<{]*)<\/h1>/.exec(source)
      const rawText = match?.[1]
      if (rawText === undefined) continue // 動態標題（如系統總覽由 moduleDashboard 提供）另以來源檢查
      const text = rawText.replace(/AXIOM/g, '').trim()
      if (fileName === 'LoginView.vue') {
        expect(text).toBe('登入')
        continue
      }
      expect(titles.has(text), `${fileName} 標題「${text}」不在註冊表`).toBe(true)
    }
    // 系統總覽以動態標題呈現，來源固定為 moduleDashboard 的 '系統總覽'
    expect(readSource('../src/lib/moduleDashboard.ts')).toContain("title: '系統總覽'")
  })

  it('視圖不得以設計圖或靜態圖片冒充真實組件', () => {
    for (const [fileName, source] of viewSources) {
      expect(source, `${fileName} 使用了 <img>`).not.toMatch(/<img/i)
      expect(source, `${fileName} 使用了背景圖片`).not.toMatch(/background-image\s*:/i)
      expect(source, `${fileName} 引用了圖片檔`).not.toMatch(/\.(png|jpe?g|gif|webp)['")]/i)
    }
  })
})
