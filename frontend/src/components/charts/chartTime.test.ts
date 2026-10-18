import { describe, expect, it } from 'vitest'
import { toChartTime } from './chartTime'

describe('toChartTime', () => {
  it('keeps a daily label as a business day', () => {
    expect(toChartTime('2026-10-16')).toBe('2026-10-16')
  })

  it('turns a KST timestamp into seconds that read as Korean local time on the UTC axis', () => {
    const shown = toChartTime('2026-10-16T09:00:00+09:00') as number

    // 09:00 KST must come out as 09:00 on the UTC-drawn axis
    expect(new Date(shown * 1000).toISOString()).toBe('2026-10-16T09:00:00.000Z')
  })

  it('keeps bars ordered', () => {
    const a = toChartTime('2026-10-16T09:30:00+09:00') as number
    const b = toChartTime('2026-10-16T10:00:00+09:00') as number

    expect(b - a).toBe(1800)
  })
})
