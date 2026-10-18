import { describe, expect, it } from 'vitest'
import { formatAmount, formatChange, formatNumber, formatPercent, formatScore } from './format'

describe('formatAmount (KRW in the units Korean traders read)', () => {
  it('uses 조, 억 and 만', () => {
    expect(formatAmount(3_500_000_000_000)).toBe('3.5조')
    expect(formatAmount(48_200_000_000)).toBe('482.0억')
    expect(formatAmount(1_000_000_000)).toBe('10.0억')
    expect(formatAmount(95_000_000)).toBe('9,500만')
    expect(formatAmount(1234)).toBe('1,234')
  })

  it('keeps the sign and shows a dash for a missing value', () => {
    expect(formatAmount(-250_000_000)).toBe('-2.5억')
    expect(formatAmount(null)).toBe('-')
    expect(formatAmount(undefined)).toBe('-')
    expect(formatAmount(Number.NaN)).toBe('-')
  })
})

describe('formatPercent', () => {
  it('signs gains and leaves losses with their minus', () => {
    expect(formatPercent(1.234)).toBe('+1.23%')
    expect(formatPercent(-0.5)).toBe('-0.50%')
    expect(formatPercent(0)).toBe('0.00%')
  })

  it('can drop the plus sign and change the digits', () => {
    expect(formatPercent(2.5, 1, false)).toBe('2.5%')
    expect(formatPercent(null)).toBe('-')
  })
})

describe('formatChange (score change)', () => {
  it('shows an arrow with the size of the move', () => {
    expect(formatChange(3.456)).toBe('▲ 3.5')
    expect(formatChange(-1)).toBe('▼ 1.0')
    expect(formatChange(0)).toBe('– 0.0')
    expect(formatChange(null)).toBe('-')
  })
})

describe('numbers and scores', () => {
  it('groups digits', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
    expect(formatNumber(12.345, 1)).toBe('12.3')
    expect(formatNumber(null)).toBe('-')
  })

  it('shows a score with one decimal', () => {
    expect(formatScore(58)).toBe('58.0')
    expect(formatScore(null)).toBe('-')
  })
})
