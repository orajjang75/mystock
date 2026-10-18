import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import { makeSettings } from '../../test/fixtures'
import { FormError, buildRequest, defaultValues, parseNumbers, suggestValues } from './requestForm'

const base = () => defaultValues(makeSettings())

describe('parseNumbers', () => {
  it('reads numbers separated by commas and spaces', () => {
    expect(parseNumbers('0.005, 0.01  0.02')).toEqual([0.005, 0.01, 0.02])
    expect(parseNumbers('-20,-30')).toEqual([-20, -30])
  })

  it('refuses anything that is not a number', () => {
    expect(parseNumbers('1, abc')).toBeNull()
    expect(parseNumbers('')).toEqual([])
  })
})

describe('suggestValues', () => {
  it('spreads half to one and a half times around the current value', () => {
    expect(suggestValues(0.01, 'number')).toEqual([0.005, 0.0075, 0.01, 0.0125, 0.015])
  })

  it('keeps counts whole and drops duplicates', () => {
    expect(suggestValues(2, 'integer')).toEqual([1, 2, 3])
    expect(suggestValues(14, 'integer')).toEqual([7, 11, 14, 18, 21])
  })

  it('works for negative thresholds', () => {
    expect(suggestValues(-30, 'number')).toEqual([-45, -37.5, -30, -22.5, -15])
  })
})

describe('buildRequest', () => {
  it('turns the default form into a request that runs both parts and compares the bars', () => {
    const request = buildRequest(base())

    expect(request.name).toBeNull()
    expect(request.start_date).toBeNull()
    expect(request.bar_length).toBe('60m')
    expect(request.universe).toEqual({ point_in_time: true, include_delisted: true })
    expect(request.compare_bar_lengths).toBe(true)
    expect(request.signal_quality).toMatchObject({ horizons: [1, 3, 5, 10, 20], primary_horizon: 5, random_trials: 20, slippages: [0, 0.001, 0.003], min_sample_dates: 30 })
    expect(request.cycle).toMatchObject({ max_stocks: 30, on_expiry: 'abandon', slippage: 0.001, min_sample_cycles: 30, initial_value: 10_000_000 })
    expect(request.sensitivity).toBeNull()
    expect(request.walk_forward).toBeNull()
    expect(request.params).toEqual(makeSettings().signal_params) // the current settings by default
  })

  it('sends the dates, the name and what was changed', () => {
    const values = {
      ...base(),
      name: '  시험  ',
      range: [dayjs('2026-01-05'), dayjs('2026-09-30')] as [dayjs.Dayjs, dayjs.Dayjs],
      point_in_time: false,
      include_delisted: false,
      bar_length: '1d' as const,
      on_expiry: 'retry' as const,
    }

    const request = buildRequest(values)

    expect(request.name).toBe('시험')
    expect([request.start_date, request.end_date]).toEqual(['2026-01-05', '2026-09-30'])
    expect(request.universe).toEqual({ point_in_time: false, include_delisted: false })
    expect(request.bar_length).toBe('1d')
    expect(request.cycle?.on_expiry).toBe('retry')
  })

  it('leaves out the part that is not asked for, and the bar comparison with it', () => {
    const onlyQuality = buildRequest({ ...base(), run: ['signal_quality'] })
    expect(onlyQuality.cycle).toBeNull()
    expect(onlyQuality.compare_bar_lengths).toBe(false)

    const onlyCycle = buildRequest({ ...base(), run: ['cycle'] })
    expect(onlyCycle.signal_quality).toBeNull()
    expect(onlyCycle.compare_bar_lengths).toBe(true)
  })

  it('refuses a run of nothing', () => {
    expect(() => buildRequest({ ...base(), run: [] })).toThrow(FormError)
  })

  it('builds the sensitivity grid with one or two axes', () => {
    const one = buildRequest({ ...base(), sensitivity: true })
    expect(one.sensitivity).toEqual({
      target: 'cycle',
      metric: 'mean_increase_rate',
      x: { path: 'rebuy.target_gain', values: [0.005, 0.01, 0.015, 0.02] },
      y: null,
    })

    const two = buildRequest({ ...base(), sensitivity: true, sens_y: 'sell.min_overlap', sens_y_values: '1, 2, 3' })
    expect(two.sensitivity?.y).toEqual({ path: 'sell.min_overlap', values: [1, 2, 3] })
  })

  it('builds the walk-forward spec', () => {
    const request = buildRequest({ ...base(), walk_forward: true })

    expect(request.walk_forward).toEqual({
      target: 'signal_quality',
      metric: 'median_return',
      param: { path: 'screener.drawdown_threshold_pct', values: [-20, -25, -30, -35] },
      train_days: 120,
      test_days: 40,
      step_days: 40,
      min_samples: 10,
    })
  })

  it('explains what is wrong with an axis', () => {
    expect(() => buildRequest({ ...base(), sensitivity: true, sens_x: undefined })).toThrow('가로축: 파라미터를 고르세요')
    expect(() => buildRequest({ ...base(), sensitivity: true, sens_x_values: '0.01' })).toThrow('두 개 이상')
    expect(() => buildRequest({ ...base(), walk_forward: true, wf_values: 'a, b' })).toThrow('롤링 검증')
  })

  it('refuses to judge by a part that is not run', () => {
    expect(() => buildRequest({ ...base(), run: ['signal_quality'], sensitivity: true, sens_target: 'cycle' })).toThrow('사이클 시뮬레이션도')
    expect(() => buildRequest({ ...base(), run: ['cycle'], walk_forward: true, wf_target: 'signal_quality' })).toThrow('신호 품질도')
  })
})
