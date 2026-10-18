// The single place for colors. Change BRAND_PRIMARY to re-brand the app (PRD 오픈 이슈: 브랜드 색).
export const BRAND_PRIMARY = '#1677ff' // antd default blue until a brand color is decided

// Korean market convention: rising is red, falling is blue.
export const MARKET_COLORS = {
  up: '#f04452',
  down: '#3485fa',
  flat: '#8c8c8c',
} as const

export type Direction = 'up' | 'down' | 'flat'

export function directionOf(value: number | null | undefined): Direction {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

export function directionColor(value: number | null | undefined): string {
  return MARKET_COLORS[directionOf(value)]
}

// Expose the colors to CSS as --color-up / --color-down / --color-flat so stylesheets and
// components never repeat the hex values.
export function applyCssVariables(root: HTMLElement = document.documentElement): void {
  root.style.setProperty('--color-up', MARKET_COLORS.up)
  root.style.setProperty('--color-down', MARKET_COLORS.down)
  root.style.setProperty('--color-flat', MARKET_COLORS.flat)
  root.style.setProperty('--color-brand', BRAND_PRIMARY)
}
