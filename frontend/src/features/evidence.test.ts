import { describe, expect, it } from 'vitest'
import { SIGNAL_LABELS, evidenceRows } from './evidence'

describe('evidenceRows', () => {
  it('names the signals and the values in Korean and hides internal ids', () => {
    const rows = evidenceRows({
      signals: ['rsi_overbought_exit', 'macd_weakening'],
      overlap: 2,
      rsi: 68.2345,
      bar_length: '60m',
      flow_unreflected: false,
      held_by_flow_filter: true,
      cycle_id: 4,
      choices: ['retry', 'abandon'],
    })

    expect(Object.fromEntries(rows.map((r) => [r.label, r.value]))).toEqual({
      '충족한 신호': 'RSI 과매수 이탈 · MACD 약화',
      '겹친 매도 신호 수': '2',
      RSI: '68.23',
      '신호 봉': '60분봉',
      '수급 미반영': '아니오',
      '수급 이탈로 보류': '예',
    })
  })

  it('formats money, instants and missing values', () => {
    const rows = Object.fromEntries(
      evidenceRows({ stop_price: 257084, bar_end: '2026-10-16T11:00:00+09:00', pct_b: null, latency_seconds: 10.1 }).map((r) => [r.key, r.value]),
    )

    expect(rows.stop_price).toBe('257,084')
    expect(rows.bar_end).toBe('10-16 11:00')
    expect(rows.pct_b).toBe('-')
    expect(rows.latency_seconds).toBe('10.10')
  })

  it('shows an unknown key as it is rather than dropping it', () => {
    expect(evidenceRows({ brand_new: 'x' })).toEqual([{ key: 'brand_new', label: 'brand_new', value: 'x' }])
  })

  it('has a label for every signal the engine can name', () => {
    for (const name of ['rsi_overbought_exit', 'bollinger_upper_reentry', 'macd_weakening', 'bearish_divergence', 'atr_disparity_overheat', 'flow_exit', 'price_condition', 'rsi_rebound', 'bollinger_support', 'macd_golden_cross']) {
      expect(SIGNAL_LABELS[name], name).toBeTruthy()
    }
  })
})
