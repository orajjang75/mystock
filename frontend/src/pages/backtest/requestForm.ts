import type { Dayjs } from 'dayjs'
import type { BacktestRequest, BarLength, SettingsResponse } from '../../api/types'
import type { Leaf } from '../settings/paramSchema'

export const SQ_METRICS = ['median_return', 'mean_return', 'win_rate', 'profit_factor', 'n_dates', 'candidates_per_day'] as const
export const CYCLE_METRICS = ['mean_increase_rate', 'completion_rate', 'gain_rate', 'cumulative_increase_pct', 'max_drawdown', 'excess_return'] as const

export type Target = 'cycle' | 'signal_quality'

export interface BacktestFormValues {
  name?: string
  range?: [Dayjs, Dayjs] | null
  bar_length: BarLength
  point_in_time: boolean
  include_delisted: boolean
  run: ('signal_quality' | 'cycle')[]
  compare_bar_lengths: boolean
  // 신호 품질
  horizons: number[]
  primary_horizon: number
  random_trials: number
  slippages: number[]
  min_sample_dates: number
  // 사이클
  max_stocks: number
  initial_value: number
  on_expiry: 'abandon' | 'retry'
  slippage: number
  min_sample_cycles: number
  // 신뢰성
  sensitivity: boolean
  sens_target: Target
  sens_metric: string
  sens_x: string | undefined
  sens_x_values: string
  sens_y: string | undefined
  sens_y_values: string
  walk_forward: boolean
  wf_target: Target
  wf_metric: string
  wf_param: string | undefined
  wf_values: string
  wf_train: number
  wf_test: number
  wf_step: number
  wf_min_samples: number
  // 파라미터 (the settings' signal_params, editable for this run only)
  params: SettingsResponse['signal_params']
}

export const SLIPPAGE_OPTIONS = [0, 0.001, 0.003, 0.005]

export function defaultValues(settings: SettingsResponse): BacktestFormValues {
  return {
    bar_length: settings.signal_bar_length,
    point_in_time: true,
    include_delisted: true,
    run: ['signal_quality', 'cycle'],
    compare_bar_lengths: true,
    horizons: [1, 3, 5, 10, 20],
    primary_horizon: 5,
    random_trials: 20,
    slippages: [0, 0.001, 0.003],
    min_sample_dates: 30,
    max_stocks: 30,
    initial_value: 10_000_000,
    on_expiry: 'abandon',
    slippage: 0.001,
    min_sample_cycles: 30,
    sensitivity: false,
    sens_target: 'cycle',
    sens_metric: 'mean_increase_rate',
    sens_x: 'rebuy.target_gain',
    sens_x_values: '0.005, 0.01, 0.015, 0.02',
    sens_y: undefined,
    sens_y_values: '',
    walk_forward: false,
    wf_target: 'signal_quality',
    wf_metric: 'median_return',
    wf_param: 'screener.drawdown_threshold_pct',
    wf_values: '-20, -25, -30, -35',
    wf_train: 120,
    wf_test: 40,
    wf_step: 40,
    wf_min_samples: 10,
    params: settings.signal_params,
  }
}

/** "0.005, 0.01  0.02" -> [0.005, 0.01, 0.02]; ``null`` if anything is not a number. */
export function parseNumbers(text: string): number[] | null {
  const parts = text.split(/[\s,]+/).filter(Boolean)
  const numbers = parts.map(Number)
  return numbers.every((n) => Number.isFinite(n)) ? numbers : null
}

/** Values to try around the current one: half to one and a half times, whole numbers for counts. */
export function suggestValues(current: number, kind: Leaf['kind']): number[] {
  const factors = [0.5, 0.75, 1, 1.25, 1.5]
  const raw = factors.map((f) => current * f)
  const values = kind === 'integer' ? raw.map((v) => Math.max(1, Math.round(v))) : raw.map((v) => Number(v.toPrecision(3)))
  return [...new Set(values)].sort((a, b) => a - b)
}

export class FormError extends Error {}

function axis(path: string | undefined, text: string, what: string) {
  const values = parseNumbers(text)
  if (!path) throw new FormError(`${what}: 파라미터를 고르세요`)
  if (!values || values.length < 2) throw new FormError(`${what}: 값을 두 개 이상 숫자로 입력하세요 (쉼표로 구분)`)
  return { path, values }
}

/** The API request of a filled-in form. Throws ``FormError`` with a message for the user. */
export function buildRequest(v: BacktestFormValues): BacktestRequest {
  const quality = v.run.includes('signal_quality')
  const cycle = v.run.includes('cycle')
  if (!quality && !cycle) throw new FormError('실행할 항목을 하나 이상 고르세요')
  const request: BacktestRequest = {
    name: v.name?.trim() || null,
    start_date: v.range?.[0]?.format('YYYY-MM-DD') ?? null,
    end_date: v.range?.[1]?.format('YYYY-MM-DD') ?? null,
    bar_length: v.bar_length,
    params: v.params,
    universe: { point_in_time: v.point_in_time, include_delisted: v.include_delisted },
    signal_quality: quality
      ? {
          horizons: [...v.horizons].sort((a, b) => a - b),
          primary_horizon: v.primary_horizon,
          random_trials: v.random_trials,
          slippages: v.slippages,
          min_sample_dates: v.min_sample_dates,
          seed: 7,
          engine: 'auto',
        }
      : null,
    cycle: cycle
      ? {
          initial_value: v.initial_value,
          max_stocks: v.max_stocks,
          on_expiry: v.on_expiry,
          slippage: v.slippage,
          slippages: v.slippages,
          min_sample_cycles: v.min_sample_cycles,
          max_retries: 2,
          warmup_days: 5,
        }
      : null,
    compare_bar_lengths: cycle && v.compare_bar_lengths,
    sensitivity: null,
    walk_forward: null,
  }
  if (v.sensitivity) {
    request.sensitivity = {
      target: v.sens_target,
      metric: v.sens_metric,
      x: axis(v.sens_x, v.sens_x_values, '민감도 가로축'),
      y: v.sens_y ? axis(v.sens_y, v.sens_y_values, '민감도 세로축') : null,
    }
  }
  if (v.walk_forward) {
    request.walk_forward = {
      target: v.wf_target,
      metric: v.wf_metric,
      param: axis(v.wf_param, v.wf_values, '롤링 검증'),
      train_days: v.wf_train,
      test_days: v.wf_test,
      step_days: v.wf_step,
      min_samples: v.wf_min_samples,
    }
  }
  if (request.sensitivity?.target === 'cycle' && !cycle) throw new FormError('민감도를 사이클로 보려면 사이클 시뮬레이션도 실행하세요')
  if (request.walk_forward?.target === 'cycle' && !cycle) throw new FormError('롤링 검증을 사이클로 보려면 사이클 시뮬레이션도 실행하세요')
  if (request.sensitivity?.target === 'signal_quality' && !quality) throw new FormError('민감도를 신호 품질로 보려면 신호 품질도 실행하세요')
  if (request.walk_forward?.target === 'signal_quality' && !quality) throw new FormError('롤링 검증을 신호 품질로 보려면 신호 품질도 실행하세요')
  return request
}
