// The shapes of a backtest's ``summary`` and ``detail`` (backend/app/backtest). The API types them
// as free-form objects; these interfaces are what the screens rely on.

export interface Period {
  start: string
  end: string
}

export interface Adoption {
  adoptable: boolean
  reasons: string[]
  n_dates?: number
  min_sample_dates?: number
  min_sample_cycles?: number
}

export interface EventStats {
  n_events: number
  n_dates: number
  mean?: number
  median?: number
  std?: number
  p10?: number
  p25?: number
  p75?: number
  p90?: number
  win_rate?: number
  avg_win?: number
  avg_loss?: number
  payoff_ratio?: number | null
  profit_factor?: number | null
  clustered_mean?: number
  clustered_median?: number
  trial_medians?: number[]
}

export interface Ratios {
  total_return: number | null
  annualized_return: number | null
  sharpe: number | null
  sortino: number | null
  calmar: number | null
  max_drawdown: number | null
}

export interface PortfolioRatios {
  horizon: number
  exposure: number
  strategy: Ratios
  universe: Ratios
  kospi: Ratios
  random: { mean: Ratios; std: Ratios; trials: number }
}

export interface CandidateStats {
  days: number
  per_day_mean: number
  per_day_median: number
  zero_days: number
  zero_days_share: number
  gate_modes: Record<string, number>
}

export type SeriesKey = 'strategy' | 'universe' | 'random' | 'kospi'

export interface HorizonBlock {
  strategy: EventStats
  universe: EventStats
  random: EventStats
  kospi: EventStats
}

export interface RegimeBlock {
  days: number
  strategy: EventStats
  universe: EventStats
}

export interface SlippageRow {
  slippage: number
  mean: number | null
  median: number | null
  win_rate: number | null
  universe_mean: number | null
  edge: number | null
}

export interface QualityEvent {
  signal_date: string
  code: string
  name: string
  score: number
  entry_date: string
  entry_price: number
  exit_date: string
  exit_price: number
  return: number
}

export interface QualityDetail {
  engine: 'pandas' | 'vectorbt'
  period: Period & { sessions: number }
  costs: { fee_per_side: number; base_slippage: number }
  candidates: CandidateStats
  primary_horizon: number
  horizons: Record<string, HorizonBlock>
  portfolios: PortfolioRatios
  curves: { dates: string[]; strategy: number[]; universe: number[]; kospi: number[]; random: number[] }
  regimes: Record<'up' | 'down' | 'flat', RegimeBlock>
  slippage: SlippageRow[]
  adoption: Adoption
  events: QualityEvent[]
}

export interface CycleHeadline {
  bar_length: string
  slippage: number
  stocks: number
  sells: number
  finished: number
  completed: number
  completion_rate: number | null
  gain_rate: number | null
  mean_increase_rate: number | null
  median_increase_rate: number | null
  cumulative_increase: number
  cumulative_increase_pct: number | null
  signal_dates: number
  expired: number
  total_return: number
  hold_return: number
  excess_return: number
  max_drawdown: number
  costs: number
}

export interface CompareRow extends CycleHeadline {
  adoption: Adoption
  forced: number
}

export interface MeanMedian {
  mean: number | null
  median: number | null
}

export interface CycleMetrics {
  bar_length: string
  stocks: number
  sells: number
  finished: number
  open_at_end: number
  completed: number
  completion_rate: number | null
  gain_rate: number | null
  increase_rate: MeanMedian
  cumulative_increase: number
  cumulative_increase_pct: number | null
  signal_dates: number
  expired: number
  expired_share: number | null
  missed_pct: MeanMedian
  missed_value: number
  wait_sessions: MeanMedian
  forced: { count: number; stocks: number; after: Record<string, { n: number } & MeanMedian> }
  delisted_exits: number
  held_back: number
  costs: number
  total_return: number
  hold_return: number
  excess_return: number
  max_drawdown: number
  hold_max_drawdown: number
  slippage: number
}

export type CycleState = 'open' | 'done' | 'expired' | 'abandoned' | 'forced'

export interface CycleRow {
  code: string
  name: string
  state: CycleState
  forced: boolean
  sold_at: string
  sell_price: number
  sell_quantity: number
  rebuy_target_price: number
  rebought_at: string | null
  rebuy_price: number | null
  rebuy_quantity: number | null
  quantity_increase: number | null
  increase_rate: number | null
  net_cash: number | null
  costs: number
  wait_sessions: number | null
  expired: boolean
  missed_pct: number | null
  missed_value: number | null
}

export interface CycleDetail {
  period: Period
  metrics: CycleMetrics
  cycles: CycleRow[]
  curves: { times: string[]; strategy: number[]; hold: number[]; quantity_gain_pct: number[] }
  notes: { stocks: number; skipped: string[]; delisted_exits: string[]; slippage: number }
  slippage: CycleHeadline[]
  comparison: CompareRow[]
}

export interface GridAxis {
  path: string
  values: number[]
  default: number
}

export interface Pick {
  x: number
  y: number | null
  value: number
}

export interface SensitivityGrid {
  target: 'cycle' | 'signal_quality'
  metric: string
  x: GridAxis
  y: GridAxis | null
  cells: (number | null)[][]
  samples: number[][]
  smoothed: (number | null)[][]
  min_samples: number
  best: Pick | null
  robust_best: Pick | null
}

export interface FoldGridRow {
  value: number
  metric: number | null
  samples: number
}

export interface Fold {
  fold: number
  train: [string, string]
  test: [string, string]
  chosen: number | null
  train_metric: number | null
  train_samples: number
  test_metric: number | null
  test_samples: number
  default_test_metric: number | null
  default_test_samples: number
  train_grid: FoldGridRow[]
}

export interface WalkForward {
  target: 'cycle' | 'signal_quality'
  metric: string
  param: string
  values: number[]
  default: number
  train_days: number
  test_days: number
  step_days: number
  folds: Fold[]
  reason?: string
  summary: {
    folds: number
    mean_train_metric: number | null
    mean_test_metric: number | null
    mean_default_test_metric: number | null
    test_minus_default: number | null
    efficiency: number | null
    chosen_values: number[]
    chosen_changes: number
  } | null
}

export interface BacktestSummary {
  message?: string
  period?: Period
  data?: {
    stocks: number
    sessions: number
    delisted: string[]
    notes: {
      adjusted_prices?: boolean
      include_delisted?: boolean
      universe?: string
      snapshots?: number
      intraday_span?: [string, string]
      suspected_unadjusted?: Record<string, number>
    }
  }
  signal_quality?: {
    engine: 'pandas' | 'vectorbt'
    period: Period & { sessions: number }
    horizon: number
    candidates: CandidateStats
    strategy: EventStats
    universe: EventStats
    random: EventStats
    kospi: EventStats
    ratios: PortfolioRatios
    adoption: Adoption
  }
  cycle?: {
    period: Period
    stocks: number
    headline: CycleHeadline
    adoption: Adoption
    comparison: CompareRow[]
  }
  warnings?: string[]
}

export interface BacktestDetail {
  signal_quality?: QualityDetail
  cycle?: CycleDetail
  sensitivity?: SensitivityGrid
  walk_forward?: WalkForward
}

export function asSummary(value: unknown): BacktestSummary {
  return (value ?? {}) as BacktestSummary
}

export function asDetail(value: unknown): BacktestDetail {
  return (value ?? {}) as BacktestDetail
}
