import type { ModuleList, ModuleListItem } from './moduleDashboard'

export interface ModuleListSelection {
  listTitle: string
  item: ModuleListItem
}

function normalize(value: string): string {
  return value.trim().toLowerCase()
}

export function matchesModuleItem(item: ModuleListItem, keyword: string): boolean {
  const query = normalize(keyword)
  if (query === '') return true
  return [item.title, item.subtitle, item.badge].some((value) => normalize(value).includes(query))
}

export function filterModuleList(list: ModuleList, keyword: string): ModuleList {
  return {
    ...list,
    items: list.items.filter((item) => matchesModuleItem(item, keyword)),
  }
}

export function flattenModuleLists(lists: ModuleList[]): ModuleListSelection[] {
  return lists.flatMap((list) => list.items.map((item) => ({ listTitle: list.title, item })))
}

export function sameSelection(
  left: ModuleListSelection | null,
  right: ModuleListSelection | null,
): boolean {
  if (left === null || right === null) return left === right
  return (
    left.listTitle === right.listTitle &&
    left.item.title === right.item.title &&
    left.item.subtitle === right.item.subtitle &&
    left.item.badge === right.item.badge
  )
}
