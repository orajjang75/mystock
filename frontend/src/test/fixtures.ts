import type {
  AlertKind,
  AlertOut,
  AlertsResponse,
  Candle,
  CycleOut,
  CyclesResponse,
  FlowPoint,
  HealthResponse,
  HoldingOut,
  IndicatorPoint,
  ResultItem,
  ResultsResponse,
  SettingsResponse,
  SignalParams,
  WatchlistItem,
} from '../api/types'
import { defaultSignalParams } from '../pages/settings/paramSchema'

export function makeSettings(overrides: Partial<SettingsResponse> = {}): SettingsResponse {
  return {
    signal_params: defaultSignalParams() as unknown as SignalParams,
    signal_bar_length: '60m',
    alert_cooldown_bars: 6,
    channels: { telegram: false },
    refresh_seconds: 60,
    presets: [],
    ...overrides,
  }
}

export function makeHealth(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: 'ok',
    mode: 'normal',
    db: 'ok',
    last_quote_update: '2026-10-16T18:00:10+09:00',
    last_daily_update: '2026-10-16T18:00:10+09:00',
    last_intraday_update: null,
    latest_daily_date: '2026-10-16',
    latest_intraday_bar: null,
    warnings: [],
    collection: {
      daily: { stale: false, last_success: '2026-10-16T18:00:10+09:00', last_error: null },
      intraday: { stale: false, last_success: null, last_error: null },
    },
    channels: { telegram: { enabled: false, configured: false } },
    scheduler: 'disabled',
    ...overrides,
  }
}

export function makeAlert(id: number, overrides: Partial<AlertOut> = {}): AlertOut {
  return {
    id,
    kind: 'sell',
    label: '매도 신호',
    level: 'signal',
    code: '900010',
    name: '모의KOSPI001',
    holding_id: 1,
    occurred_at: '2026-10-16T10:00:10+09:00',
    bar_time: '2026-10-16T09:00:00+09:00',
    suggested_quantity: 33,
    price: 67405,
    rebuy_target_price: 66690,
    evidence: {},
    params: null,
    is_read: false,
    delivery: [],
    ...overrides,
  }
}

export const ALERT_KINDS: AlertKind[] = [
  { kind: 'sell', label: '매도 신호', level: 'signal' },
  { kind: 'rebuy', label: '재매수 신호', level: 'signal' },
  { kind: 'rebuy_held', label: '재매수 보류 경고 (일봉 수급 이탈)', level: 'warning' },
  { kind: 'reduce_position', label: '비중 축소 경고 (일봉 하락 추세)', level: 'warning' },
  { kind: 'stop_loss', label: '손절선 이탈 경고', level: 'warning' },
  { kind: 'force_sell', label: '강제 매도 (5일선 이탈)', level: 'signal' },
  { kind: 'expired', label: '재매수 대기 만료', level: 'signal' },
  { kind: 'data_stale', label: '시세 갱신 지연 경고', level: 'warning' },
]

export function makeAlerts(items: AlertOut[], unread = items.filter((a) => !a.is_read).length): AlertsResponse {
  return { unread, items, kinds: ALERT_KINDS }
}

export function makeResult(code: string, overrides: Partial<ResultItem> = {}): ResultItem {
  return {
    code,
    name: `모의${code}`,
    market: 'KOSPI',
    score: 50,
    tags: [
      { key: 'drawdown', label: '52주 낙폭' },
      { key: 'rsi_cross_up', label: 'RSI 30 상향 돌파' },
      { key: 'volume_3x', label: '거래량 3배' },
    ],
    close: 67405,
    change_pct: 1.5,
    trading_value: 4_800_000_000,
    flow_unreflected: false,
    in_watchlist: false,
    evidence: {
      close: 67405,
      drawdown_pct: -35.2,
      disparity_pct: -6.1,
      rsi: 41.3,
      pct_b: 0.12,
      macd_hist: -0.8,
      volume_ratio: 3.4,
      net_buy_strength_pct: 6.2,
      avg_trading_value: 4_100_000_000,
      breakdown: { reversal: 10, confirmation: 18, volume: 20, flow: 15 },
      max_points: 100,
    },
    ...overrides,
  }
}

export function makeResults(items: ResultItem[], overrides: Partial<ResultsResponse> = {}): ResultsResponse {
  return {
    scan_date: '2026-10-16',
    scan_dates: ['2026-10-16', '2026-10-15'],
    gate: { mode: 'strict', drawdown_threshold_pct: -30 },
    items,
    ...overrides,
  }
}

export function makeWatch(code: string, overrides: Partial<WatchlistItem> = {}): WatchlistItem {
  return {
    code,
    name: `모의${code}`,
    market: 'KOSPI',
    added_date: '2026-10-10',
    scan_date: '2026-10-16',
    score: 58,
    previous_scan_date: '2026-10-15',
    previous_score: 52,
    change: 6,
    ...overrides,
  }
}

export function makeCandles(count = 30, start = 100): Candle[] {
  return Array.from({ length: count }, (_, i) => {
    const close = start + i
    return {
      time: `2026-09-${String(i + 1).padStart(2, '0')}`,
      open: close - 0.5,
      high: close + 1,
      low: close - 1,
      close,
      volume: 1000 + i,
      is_complete: true,
    }
  })
}

export function makeIndicatorPoints(candles: Candle[]): IndicatorPoint[] {
  return candles.map((c) => ({
    time: c.time,
    rsi: 45,
    macd: 0.2,
    macd_signal: 0.1,
    macd_hist: 0.1,
    bb_lower: c.close - 5,
    bb_mid: c.close,
    bb_upper: c.close + 5,
    pct_b: 0.5,
    bandwidth: 0.1,
    obv: 0,
    atr: 1,
  }))
}

export function makeFlow(): FlowPoint[] {
  return [
    { date: '2026-10-15', foreign_net_buy: 1_200_000_000, institution_net_buy: -300_000_000 },
    { date: '2026-10-16', foreign_net_buy: 800_000_000, institution_net_buy: 500_000_000 },
  ]
}

export function makeHolding(id: number, overrides: Partial<HoldingOut> = {}): HoldingOut {
  return {
    id,
    code: '900010',
    name: '모의KOSPI001',
    market: 'KOSPI',
    quantity: 70,
    start_quantity: 100,
    avg_price: 90000,
    state: 'rebuy_wait',
    open_cycle: null,
    last_close: 99000,
    daily_downtrend: false,
    stop_price: 86000,
    cumulative_increase: 0,
    unrecovered_quantity: 0,
    ...overrides,
  }
}

export function makeCycle(id: number, overrides: Partial<CycleOut> = {}): CycleOut {
  return {
    id,
    state: 'rebuy_wait',
    sell_price: 100000,
    sell_quantity: 100,
    rebuy_target_price: 99300,
    rebuy_price: null,
    rebuy_quantity: null,
    quantity_increase: null,
    net_cash: null,
    sell_fee: 15,
    sell_tax: 180,
    rebuy_fee: null,
    expires_at: '2026-10-23T15:30:00+09:00',
    created_at: '2026-10-16T11:00:10+09:00',
    sold_at: '2026-10-16T11:00:10+09:00',
    rebought_at: null,
    forced: false,
    ...overrides,
  }
}

export function makeCycles(holdingId: number, cycles: CycleOut[], overrides: Partial<CyclesResponse['totals']> = {}): CyclesResponse {
  const done = cycles.filter((c) => c.quantity_increase !== null)
  return {
    holding_id: holdingId,
    cycles,
    totals: {
      cycles: cycles.length,
      completed: done.length,
      successful: done.filter((c) => (c.quantity_increase ?? 0) > 0).length,
      cumulative_increase: done.reduce((sum, c) => sum + (c.quantity_increase ?? 0), 0),
      unrecovered_quantity: 0,
      pending_quantity: cycles.filter((c) => c.state === 'rebuy_wait' || c.state === 'expired').reduce((sum, c) => sum + c.sell_quantity, 0),
      start_quantity: 300,
      current_quantity: 300,
      ...overrides,
    },
  }
}
