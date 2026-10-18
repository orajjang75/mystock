import { describe, expect, it } from 'vitest'
import { makeCompare, makeGrid, makeQuality, makeWalkForward } from '../../test/backtestFixtures'
import { COMPARE_METRICS, compareOption, heatmapOption, horizonOption, lineOption, walkForwardOption } from './chartOptions'

type Loose = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any

describe('lineOption', () => {
  it('draws one line per series on a shared axis', () => {
    const option = lineOption(['a', 'b'], [{ name: '전략', values: [100, 101], color: '#7c4dff' }, { name: '보유', values: [100, null], color: '#8c8c8c', dashed: true }]) as Loose

    expect(option.xAxis.data).toEqual(['a', 'b'])
    expect(option.series.map((s: Loose) => s.name)).toEqual(['전략', '보유'])
    expect(option.series[1].lineStyle.type).toBe('dashed')
    expect(option.series[1].data).toEqual([100, null])
  })

  it('keeps red and blue for price direction', () => {
    const option = lineOption(['a'], [{ name: 'x', values: [1], color: '#7c4dff' }]) as Loose

    expect(option.color).not.toContain('#f04452')
    expect(option.color).not.toContain('#3485fa')
  })
})

describe('horizonOption', () => {
  it('compares the medians of the picks and the three baselines per holding period, in percent', () => {
    const option = horizonOption(makeQuality().horizons) as Loose

    expect(option.xAxis.data).toEqual(['3일', '5일'])
    expect(option.series).toHaveLength(4)
    const strategy = option.series.find((s: Loose) => s.name === '후보')
    expect(strategy.data).toEqual([-0.7, 0.9])
  })
})

describe('compareOption', () => {
  it('has a bar per bar length for the chosen metric', () => {
    const rows = makeCompare()

    const option = compareOption(rows, 'mean_increase_rate') as Loose

    expect(option.xAxis.data).toEqual(['30m', '60m', '1d'])
    expect(option.series[0].data).toEqual([1.2, 1.8, 3])
    expect(COMPARE_METRICS.mean_increase_rate.label).toContain('수량 증가율')
  })

  it('shows the sample size on every bar so a thin one is not mistaken for a good one', () => {
    const option = compareOption(makeCompare(), 'completion_rate') as Loose

    expect(option.series[0].label.formatter({ dataIndex: 2 })).toBe('n=8')
  })

  it('keeps a missing value empty instead of zero', () => {
    const rows = makeCompare()
    rows[0] = { ...rows[0], completion_rate: null }

    expect((compareOption(rows, 'completion_rate') as Loose).series[0].data[0]).toBeNull()
  })
})

describe('heatmapOption', () => {
  it('lays the grid out cell by cell, empty cells included', () => {
    const option = heatmapOption(makeGrid(), false) as Loose

    expect(option.xAxis.data).toEqual(['0.005', '0.01', '0.02'])
    expect(option.yAxis.data).toEqual(['1', '2'])
    const values = option.series[0].data.map((d: Loose) => d.value)
    expect(values).toHaveLength(6)
    expect(values[0]).toEqual([0, 0, 0.01])
    expect(values[5]).toEqual([2, 1, null])
  })

  it('outlines the best cell, or the best-in-its-neighbourhood cell when smoothed', () => {
    const raw = (heatmapOption(makeGrid(), false) as Loose).series[0].data
    const smooth = (heatmapOption(makeGrid(), true) as Loose).series[0].data

    const marked = (data: Loose[]) => data.filter((d) => d.itemStyle).map((d) => d.value.slice(0, 2))
    expect(marked(raw)).toEqual([[1, 1]]) // x=0.01, y=2
    expect(marked(smooth)).toEqual([[2, 1]]) // x=0.02, y=2
  })

  it('draws a one-row strip when there is no second axis', () => {
    const grid = makeGrid({ y: null, cells: [[0.01, 0.02, 0.015]], samples: [[40, 38, 30]], smoothed: [[0.015, 0.0150, 0.0175]], best: { x: 0.01, y: null, value: 0.02 } })

    const option = heatmapOption(grid, false) as Loose

    expect(option.yAxis.data).toEqual([''])
    expect(option.series[0].data).toHaveLength(3)
  })

  it('does not break when every cell is empty', () => {
    const grid = makeGrid({ cells: [[null, null, null], [null, null, null]], smoothed: [[null, null, null], [null, null, null]], best: null, robust_best: null })

    const option = heatmapOption(grid, false) as Loose

    expect(option.visualMap.min).toBeLessThan(option.visualMap.max)
  })

  it('names the parameters and the sample size in the tooltip', () => {
    const option = heatmapOption(makeGrid(), false) as Loose

    const text = option.tooltip.formatter({ value: [1, 1, 0.03] })

    expect(text).toContain('rebuy.target_gain=0.01')
    expect(text).toContain('sell.min_overlap=2')
    expect(text).toContain('표본 35')
  })
})

describe('walkForwardOption', () => {
  it('plots the training metric against the test metric of the chosen value and of the default', () => {
    const option = walkForwardOption(makeWalkForward().folds) as Loose

    expect(option.xAxis.data).toEqual(['1', '2'])
    expect(option.series.map((s: Loose) => s.name)).toEqual(['학습(고른 값)', '검증(고른 값)', '검증(기본값)'])
  })
})
