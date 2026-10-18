import type { Candle, CycleOut, HoldingOut } from '../../api/types'
import type { PriceLineSpec, PriceMarker } from '../../components/charts/PriceChart'

export const TARGET_LINE_COLOR = '#722ed1'
export const STOP_LINE_COLOR = '#fa8c16'

/**
 * The candle a fill belongs to: the last bar that started at or before it. A fill before the
 * first bar (older than the chart) has no place on it.
 */
export function snapToCandle(candles: Candle[], filledAt: string): string | null {
  if (candles.length === 0) return null
  const daily = candles[0].time.length === 10
  // Candle labels carry the +09:00 offset; compare instants for minute bars, dates for daily bars.
  const at = daily ? new Date(new Date(filledAt).getTime() + 9 * 3600_000).toISOString().slice(0, 10) : null
  let found: string | null = null
  for (const candle of candles) {
    const before = daily ? candle.time <= (at as string) : Date.parse(candle.time) <= Date.parse(filledAt)
    if (!before) break
    found = candle.time
  }
  return found
}

/** Sell and rebuy markers from the cycle history, placed on the chart's bars. */
export function cycleMarkers(cycles: CycleOut[], candles: Candle[]): PriceMarker[] {
  const markers: PriceMarker[] = []
  for (const cycle of cycles) {
    const sold = cycle.sold_at ? snapToCandle(candles, cycle.sold_at) : null
    if (sold) markers.push({ time: sold, kind: 'sell', text: cycle.forced ? '강제 매도' : '매도' })
    const rebought = cycle.rebought_at ? snapToCandle(candles, cycle.rebought_at) : null
    if (rebought) markers.push({ time: rebought, kind: 'rebuy', text: '재매수' })
  }
  return markers
}

/** 재매수 목표가 while a cycle waits, and the ATR 손절선 (A-8). */
export function holdingPriceLines(holding: HoldingOut): PriceLineSpec[] {
  const lines: PriceLineSpec[] = []
  if (holding.open_cycle) {
    lines.push({ price: holding.open_cycle.rebuy_target_price, title: '재매수 목표가', color: TARGET_LINE_COLOR })
  }
  if (holding.stop_price !== null) lines.push({ price: holding.stop_price, title: 'ATR 손절선', color: STOP_LINE_COLOR })
  return lines
}
