import type { BacktestRun, BacktestRunSummary } from '../api/types'
import type {
  BacktestDetail,
  BacktestSummary,
  CompareRow,
  CycleDetail,
  CycleHeadline,
  CycleMetrics,
  CycleRow,
  EventStats,
  QualityDetail,
  Ratios,
  SensitivityGrid,
  WalkForward,
} from '../features/backtest/result'

const stats = (n: number, mean: number, median: number): EventStats => ({
  n_events: n,
  n_dates: Math.round(n / 2),
  mean,
  median,
  std: 0.05,
  p10: -0.06,
  p25: -0.02,
  p75: 0.03,
  p90: 0.07,
  win_rate: 0.52,
  avg_win: 0.03,
  avg_loss: -0.025,
  payoff_ratio: 1.2,
  profit_factor: 1.3,
})

const ratios = (total: number): Ratios => ({
  total_return: total,
  annualized_return: total * 1.2,
  sharpe: 0.8,
  sortino: 1.1,
  calmar: 0.6,
  max_drawdown: -0.12,
})

export function makeQuality(overrides: Partial<QualityDetail> = {}): QualityDetail {
  return {
    engine: 'pandas',
    period: { start: '2025-12-01', end: '2026-10-16', sessions: 230 },
    costs: { fee_per_side: 0.00105, base_slippage: 0.001 },
    candidates: { days: 230, per_day_mean: 1.07, per_day_median: 0, zero_days: 122, zero_days_share: 0.53, gate_modes: { strict: 230 } },
    primary_horizon: 5,
    horizons: {
      '3': { strategy: stats(228, -0.01, -0.007), universe: stats(5600, -0.006, -0.006), random: stats(1100, -0.005, -0.004), kospi: stats(100, -0.001, -0.002) },
      '5': { strategy: stats(220, 0.012, 0.009), universe: stats(5585, -0.008, -0.008), random: { ...stats(1109, -0.007, -0.008), trial_medians: [-0.008, -0.009] }, kospi: stats(102, -0.002, -0.004) },
    },
    portfolios: {
      horizon: 5,
      exposure: 0.5,
      strategy: ratios(0.1),
      universe: ratios(-0.17),
      kospi: ratios(-0.01),
      random: { mean: ratios(-0.18), std: ratios(0.02), trials: 20 },
    },
    curves: {
      dates: ['2025-12-01', '2026-03-01', '2026-06-01'],
      strategy: [100, 105, 110],
      universe: [100, 95, 83],
      kospi: [100, 99, 99],
      random: [100, 94, 82],
    },
    regimes: {
      up: { days: 60, strategy: stats(40, 0.02, 0.015), universe: stats(1500, 0.01, 0.01) },
      down: { days: 90, strategy: stats(100, -0.01, -0.01), universe: stats(2500, -0.02, -0.02) },
      flat: { days: 80, strategy: stats(80, 0.005, 0.004), universe: stats(1500, -0.001, -0.001) },
    },
    slippage: [
      { slippage: 0, mean: 0.015, median: 0.012, win_rate: 0.55, universe_mean: -0.006, edge: 0.021 },
      { slippage: 0.003, mean: 0.009, median: 0.006, win_rate: 0.5, universe_mean: -0.011, edge: 0.02 },
    ],
    adoption: { adoptable: true, reasons: [], n_dates: 101, min_sample_dates: 30 },
    events: [
      { signal_date: '2026-10-08', code: '900140', name: '모의KOSPI014', score: 58, entry_date: '2026-10-09', entry_price: 14000, exit_date: '2026-10-16', exit_price: 14400, return: 0.0258 },
      { signal_date: '2026-10-07', code: '900210', name: '모의KOSPI021', score: 52, entry_date: '2026-10-08', entry_price: 8000, exit_date: '2026-10-15', exit_price: 7800, return: -0.0262 },
    ],
    ...overrides,
  }
}

export function makeHeadline(overrides: Partial<CycleHeadline> = {}): CycleHeadline {
  return {
    bar_length: '60m',
    slippage: 0.001,
    stocks: 12,
    sells: 40,
    finished: 38,
    completed: 20,
    completion_rate: 0.526,
    gain_rate: 0.42,
    mean_increase_rate: 0.018,
    median_increase_rate: 0.015,
    cumulative_increase: 14,
    cumulative_increase_pct: 0.31,
    signal_dates: 30,
    expired: 12,
    total_return: 0.021,
    hold_return: 0.012,
    excess_return: 0.009,
    max_drawdown: -0.045,
    costs: 120000,
    ...overrides,
  }
}

export function makeCycleMetrics(overrides: Partial<CycleMetrics> = {}): CycleMetrics {
  return {
    bar_length: '60m',
    stocks: 12,
    sells: 40,
    finished: 38,
    open_at_end: 2,
    completed: 20,
    completion_rate: 0.526,
    gain_rate: 0.42,
    increase_rate: { mean: 0.018, median: 0.015 },
    cumulative_increase: 14,
    cumulative_increase_pct: 0.31,
    signal_dates: 30,
    expired: 12,
    expired_share: 0.316,
    missed_pct: { mean: 3.4, median: 2.1 },
    missed_value: 540000,
    wait_sessions: { mean: 2.4, median: 2 },
    forced: { count: 3, stocks: 3, after: { '5': { n: 3, mean: 0.012, median: 0.01 }, '10': { n: 3, mean: -0.01, median: -0.02 } } },
    delisted_exits: 0,
    held_back: 4,
    costs: 120000,
    total_return: 0.021,
    hold_return: 0.012,
    excess_return: 0.009,
    max_drawdown: -0.045,
    hold_max_drawdown: -0.06,
    slippage: 0.001,
    ...overrides,
  }
}

export function makeCycleRow(overrides: Partial<CycleRow> = {}): CycleRow {
  return {
    code: '900180',
    name: '모의KOSPI018',
    state: 'done',
    forced: false,
    sold_at: '2026-08-03T10:00:00+09:00',
    sell_price: 47000,
    sell_quantity: 74,
    rebuy_target_price: 46400,
    rebought_at: '2026-08-05T12:00:00+09:00',
    rebuy_price: 46000,
    rebuy_quantity: 76,
    quantity_increase: 2,
    increase_rate: 0.027,
    net_cash: 1500,
    costs: 7000,
    wait_sessions: 2,
    expired: false,
    missed_pct: null,
    missed_value: null,
    ...overrides,
  }
}

export function makeCompare(): CompareRow[] {
  const adoption = (ok: boolean) => ({ adoptable: ok, reasons: ok ? [] : ['끝난 사이클 8건 < 최소 30건: 표본 부족'] })
  return [
    { ...makeHeadline({ bar_length: '30m', finished: 52, mean_increase_rate: 0.012 }), adoption: adoption(true), forced: 3 },
    { ...makeHeadline({ bar_length: '60m', finished: 38, mean_increase_rate: 0.018 }), adoption: adoption(true), forced: 3 },
    { ...makeHeadline({ bar_length: '1d', finished: 8, mean_increase_rate: 0.03 }), adoption: adoption(false), forced: 2 },
  ]
}

export function makeCycle(overrides: Partial<CycleDetail> = {}): CycleDetail {
  return {
    period: { start: '2026-07-27', end: '2026-10-16' },
    metrics: makeCycleMetrics(),
    cycles: [
      makeCycleRow(),
      makeCycleRow({ code: '900140', name: '모의KOSPI014', state: 'abandoned', rebought_at: null, rebuy_price: null, rebuy_quantity: null, quantity_increase: null, increase_rate: null, net_cash: null, wait_sessions: null, expired: true, missed_pct: 3.6, missed_value: 126000 }),
      makeCycleRow({ code: '900090', name: '모의KOSPI009', state: 'forced', forced: true, rebought_at: null, rebuy_price: null, rebuy_quantity: null, quantity_increase: null, increase_rate: null, net_cash: null, wait_sessions: null }),
    ],
    curves: {
      times: ['2026-07-27T15:30:00+09:00', '2026-09-01T15:30:00+09:00', '2026-10-16T15:30:00+09:00'],
      strategy: [100, 101, 102.1],
      hold: [100, 100.5, 101.2],
      quantity_gain_pct: [0, 0.1, 0.31],
    },
    notes: { stocks: 12, skipped: ['900060'], delisted_exits: [], slippage: 0.001 },
    slippage: [makeHeadline({ slippage: 0 }), makeHeadline({ slippage: 0.001 }), makeHeadline({ slippage: 0.003, cumulative_increase: 4 })],
    comparison: makeCompare(),
    ...overrides,
  }
}

export function makeGrid(overrides: Partial<SensitivityGrid> = {}): SensitivityGrid {
  return {
    target: 'cycle',
    metric: 'mean_increase_rate',
    x: { path: 'rebuy.target_gain', values: [0.005, 0.01, 0.02], default: 0.01 },
    y: { path: 'sell.min_overlap', values: [1, 2], default: 2 },
    cells: [
      [0.01, 0.02, 0.015],
      [0.005, 0.03, null],
    ],
    samples: [
      [40, 38, 30],
      [20, 35, 3],
    ],
    smoothed: [
      [0.016, 0.019, 0.02],
      [0.014, 0.017, 0.022],
    ],
    min_samples: 10,
    best: { x: 0.01, y: 2, value: 0.03 },
    robust_best: { x: 0.02, y: 2, value: 0.022 },
    ...overrides,
  }
}

export function makeWalkForward(overrides: Partial<WalkForward> = {}): WalkForward {
  const row = (fold: number, chosen: number) => ({
    fold,
    train: ['2026-01-01', '2026-04-30'] as [string, string],
    test: ['2026-05-04', '2026-06-26'] as [string, string],
    chosen,
    train_metric: 0.012,
    train_samples: 80,
    test_metric: 0.004 + fold / 1000,
    test_samples: 25,
    default_test_metric: 0.003,
    default_test_samples: 30,
    train_grid: [{ value: -20, metric: 0.01, samples: 70 }, { value: -30, metric: 0.012, samples: 80 }],
  })
  return {
    target: 'signal_quality',
    metric: 'median_return',
    param: 'screener.drawdown_threshold_pct',
    values: [-20, -30],
    default: -30,
    train_days: 120,
    test_days: 40,
    step_days: 40,
    folds: [row(1, -30), row(2, -20)],
    summary: {
      folds: 2,
      mean_train_metric: 0.012,
      mean_test_metric: 0.0045,
      mean_default_test_metric: 0.003,
      test_minus_default: 0.0015,
      efficiency: 0.375,
      chosen_values: [-30, -20],
      chosen_changes: 2,
    },
    ...overrides,
  }
}

export function makeSummary(overrides: Partial<BacktestSummary> = {}): BacktestSummary {
  const quality = makeQuality()
  return {
    period: { start: '2025-12-01', end: '2026-10-16' },
    data: {
      stocks: 30,
      sessions: 500,
      delisted: ['900060', '900090'],
      notes: { adjusted_prices: true, include_delisted: true, universe: 'point in time: the latest stored ranking on or before each day', snapshots: 13, intraday_span: ['2026-07-27T00:00:00', '2026-10-16T00:00:00'] },
    },
    signal_quality: {
      engine: 'pandas',
      period: quality.period,
      horizon: 5,
      candidates: quality.candidates,
      strategy: quality.horizons['5'].strategy,
      universe: quality.horizons['5'].universe,
      random: quality.horizons['5'].random,
      kospi: quality.horizons['5'].kospi,
      ratios: quality.portfolios,
      adoption: quality.adoption,
    },
    cycle: {
      period: { start: '2026-07-27', end: '2026-10-16' },
      stocks: 12,
      headline: makeHeadline(),
      adoption: { adoptable: true, reasons: [], min_sample_cycles: 30 },
      comparison: makeCompare(),
    },
    warnings: [],
    ...overrides,
  }
}

export function makeDetail(overrides: Partial<BacktestDetail> = {}): BacktestDetail {
  return { signal_quality: makeQuality(), cycle: makeCycle(), ...overrides }
}

export function makeRunSummary(id: number, overrides: Partial<BacktestRunSummary> = {}): BacktestRunSummary {
  return {
    id,
    name: `실행 ${id}`,
    status: 'done',
    progress: 1,
    executed_at: '2026-10-18T10:00:00+09:00',
    start_date: '2025-12-01',
    end_date: '2026-10-16',
    bar_length: '60m',
    summary: makeSummary() as unknown as BacktestRunSummary['summary'],
    error: null,
    ...overrides,
  }
}

export function makeRun(id: number, overrides: Partial<BacktestRun> = {}, detail: BacktestDetail = makeDetail()): BacktestRun {
  return {
    ...makeRunSummary(id),
    params: {},
    detail: detail as unknown as BacktestRun['detail'],
    ...overrides,
  }
}
