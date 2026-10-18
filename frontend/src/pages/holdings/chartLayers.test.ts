import { describe, expect, it } from 'vitest'
import type { Candle } from '../../api/types'
import { makeCycle, makeHolding } from '../../test/fixtures'
import { STOP_LINE_COLOR, TARGET_LINE_COLOR, cycleMarkers, holdingPriceLines, snapToCandle } from './chartLayers'

const candle = (time: string): Candle => ({ time, open: 1, high: 2, low: 1, close: 2, volume: 1, is_complete: true })
const hourly = ['09:00', '10:00', '11:00', '12:00'].map((hhmm) => candle(`2026-10-16T${hhmm}:00+09:00`))
const daily = ['2026-10-14', '2026-10-15', '2026-10-16'].map(candle)

describe('snapToCandle', () => {
  it('puts a fill on the bar that was open when it happened', () => {
    expect(snapToCandle(hourly, '2026-10-16T10:40:00+09:00')).toBe('2026-10-16T10:00:00+09:00')
    expect(snapToCandle(hourly, '2026-10-16T11:00:10+09:00')).toBe('2026-10-16T11:00:00+09:00')
  })

  it('reads the instant, not the text, so an offset in another zone still lands right', () => {
    expect(snapToCandle(hourly, '2026-10-16T01:40:00+00:00')).toBe('2026-10-16T10:00:00+09:00')
  })

  it('puts a fill after the last bar on the last bar and drops one before the first', () => {
    expect(snapToCandle(hourly, '2026-10-17T09:00:00+09:00')).toBe('2026-10-16T12:00:00+09:00')
    expect(snapToCandle(hourly, '2026-10-16T08:00:00+09:00')).toBeNull()
    expect(snapToCandle([], '2026-10-16T08:00:00+09:00')).toBeNull()
  })

  it('uses the Korean date for daily bars', () => {
    expect(snapToCandle(daily, '2026-10-15T18:00:00+09:00')).toBe('2026-10-15')
    expect(snapToCandle(daily, '2026-10-15T23:30:00+09:00')).toBe('2026-10-15')
    expect(snapToCandle(daily, '2026-10-15T08:00:00+00:00')).toBe('2026-10-15') // 17:00 in Seoul
  })
})

describe('cycleMarkers', () => {
  it('marks the sale and the rebuy of each cycle', () => {
    const cycles = [
      makeCycle(1, { sold_at: '2026-10-16T10:20:00+09:00', rebought_at: '2026-10-16T11:30:00+09:00', state: 'rebuy_done' }),
      makeCycle(2, { sold_at: '2026-10-16T12:05:00+09:00', rebought_at: null }),
    ]

    expect(cycleMarkers(cycles, hourly)).toEqual([
      { time: '2026-10-16T10:00:00+09:00', kind: 'sell', text: '매도' },
      { time: '2026-10-16T11:00:00+09:00', kind: 'rebuy', text: '재매수' },
      { time: '2026-10-16T12:00:00+09:00', kind: 'sell', text: '매도' },
    ])
  })

  it('labels a forced sale and skips fills older than the chart', () => {
    const cycles = [makeCycle(1, { forced: true, sold_at: '2026-10-16T10:00:00+09:00' }), makeCycle(2, { sold_at: '2026-09-01T10:00:00+09:00' })]

    expect(cycleMarkers(cycles, hourly)).toEqual([{ time: '2026-10-16T10:00:00+09:00', kind: 'sell', text: '강제 매도' }])
  })
})

describe('holdingPriceLines', () => {
  it('draws the rebuy target only while a cycle is open, and the ATR stop when there is one', () => {
    const waiting = makeHolding(1, { open_cycle: makeCycle(1, { rebuy_target_price: 99300 }), stop_price: 86000 })
    expect(holdingPriceLines(waiting)).toEqual([
      { price: 99300, title: '재매수 목표가', color: TARGET_LINE_COLOR },
      { price: 86000, title: 'ATR 손절선', color: STOP_LINE_COLOR },
    ])
    expect(holdingPriceLines(makeHolding(1, { state: 'holding', open_cycle: null, stop_price: null }))).toEqual([])
  })
})
