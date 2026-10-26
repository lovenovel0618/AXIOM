import type { LocationQuery } from 'vue-router'
import { readQueryString } from './queryState'

export function readBackRef(query: LocationQuery): string {
  return readQueryString(query, 'ref')
}

export function withBackRef(
  currentPath: string,
  query: Record<string, string | undefined> = {},
): Record<string, string> {
  const next: Record<string, string> = {}
  for (const [key, value] of Object.entries(query)) {
    if (typeof value === 'string' && value !== '') next[key] = value
  }
  if (currentPath !== '') next.ref = currentPath
  return next
}
