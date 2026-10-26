import type { LocationQuery, RouteLocationNormalizedLoaded, Router } from 'vue-router'

export type QueryValue = string | undefined

function first(query: LocationQuery, key: string): string {
  const value = query[key]
  if (typeof value === 'string') return value
  return Array.isArray(value) ? (typeof value[0] === 'string' ? value[0] : '') : ''
}

export function readQueryString(query: LocationQuery, key: string): string {
  return first(query, key)
}

export function readQueryList(query: LocationQuery, key: string): string[] {
  const value = first(query, key)
  if (value.trim() === '') return []
  return value
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry !== '')
}

export function selectionKey(listTitle: string, subtitle: string): string {
  return `${listTitle}::${subtitle}`
}

export async function replaceQueryState(
  router: Router,
  route: RouteLocationNormalizedLoaded,
  patch: Record<string, QueryValue>,
): Promise<void> {
  const next = { ...route.query }
  let changed = false

  for (const [key, value] of Object.entries(patch)) {
    const current = first(route.query, key)
    if (value === undefined || value === '') {
      if (key in next) {
        delete next[key]
        changed = true
      }
      continue
    }
    if (current !== value) {
      next[key] = value
      changed = true
    }
  }

  if (!changed) return
  await router.replace({ query: next })
}
