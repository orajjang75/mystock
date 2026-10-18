import { describe, expect, it } from 'vitest'
import { BRAND_PRIMARY, MARKET_COLORS, applyCssVariables, directionColor, directionOf } from './colors'
import { antdTheme } from './antdTheme'

describe('market colors', () => {
  it('uses red for rising and blue for falling (Korean convention)', () => {
    expect(directionOf(1.5)).toBe('up')
    expect(directionOf(-0.01)).toBe('down')
    expect(directionColor(3)).toBe(MARKET_COLORS.up)
    expect(directionColor(-3)).toBe(MARKET_COLORS.down)
    expect(MARKET_COLORS.up).toMatch(/^#f/i) // a red
    expect(MARKET_COLORS.down).toMatch(/^#[0-3]/i) // a blue
  })

  it('is neutral for zero and for missing values', () => {
    for (const value of [0, null, undefined, Number.NaN]) {
      expect(directionOf(value)).toBe('flat')
      expect(directionColor(value)).toBe(MARKET_COLORS.flat)
    }
  })

  it('exposes the colors to CSS from the same constants', () => {
    const root = document.createElement('div')

    applyCssVariables(root)

    expect(root.style.getPropertyValue('--color-up')).toBe(MARKET_COLORS.up)
    expect(root.style.getPropertyValue('--color-down')).toBe(MARKET_COLORS.down)
    expect(root.style.getPropertyValue('--color-brand')).toBe(BRAND_PRIMARY)
  })
})

describe('antd theme', () => {
  it('takes the brand color from the one constant', () => {
    expect(antdTheme.token?.colorPrimary).toBe(BRAND_PRIMARY)
  })
})
