import { useCallback, useState } from 'react'
import { entryFor } from './menu'

const STORAGE_KEY = 'mystock.tabs'
const HOME = '/'

/** Paths from storage, keeping only screens that exist; never empty. */
export function sanitizeTabs(value: unknown): string[] {
  const paths = Array.isArray(value) ? value.filter((p): p is string => typeof p === 'string' && !!entryFor(p)) : []
  return paths.length > 0 ? [...new Set(paths)] : [HOME]
}

function readStored(): string[] {
  try {
    return sanitizeTabs(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null'))
  } catch {
    return [HOME]
  }
}

function store(tabs: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tabs))
  } catch {
    // private mode or blocked storage: the tabs just are not remembered
  }
}

/** Pure: the tabs after opening ``path`` (already open is a no-op). */
export function openTab(tabs: string[], path: string): string[] {
  return tabs.includes(path) || !entryFor(path) ? tabs : [...tabs, path]
}

/** Pure: the tabs after closing ``path`` and where to go if it was the active one. */
export function closeTab(tabs: string[], path: string, active: string): { tabs: string[]; next: string } {
  if (tabs.length <= 1 || !tabs.includes(path)) return { tabs, next: active }
  const index = tabs.indexOf(path)
  const remaining = tabs.filter((p) => p !== path)
  if (path !== active) return { tabs: remaining, next: active }
  return { tabs: remaining, next: remaining[Math.min(index, remaining.length - 1)] }
}

/** The open tabs, remembered across reloads. */
export function useOpenTabs() {
  const [tabs, setTabs] = useState<string[]>(readStored)

  const open = useCallback((path: string) => {
    setTabs((current) => {
      const next = openTab(current, path)
      if (next !== current) store(next)
      return next
    })
  }, [])

  const close = useCallback(
    (path: string, active: string): string => {
      const result = closeTab(tabs, path, active)
      setTabs(result.tabs)
      store(result.tabs)
      return result.next
    },
    [tabs],
  )

  return { tabs, open, close }
}
