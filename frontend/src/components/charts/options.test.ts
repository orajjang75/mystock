import { describe, expect, it } from 'vitest'
import { MARKET_COLORS } from '../../theme/colors'
import { FLOW_COLORS, flowChartOption } from './flowOption'
import { sparklineOption } from './sparklineOption'

describe('flowChartOption', () => {
  const flow = [
    { date: '2026-10-14', foreign_net_buy: 1_500_000_000, institution_net_buy: -300_000_000 },
    { date: '2026-10-15', foreign_net_buy: -200_000_000, institution_net_buy: 800_000_000 },
  ]

  it('has a foreign and an institution bar series over the same dates', () => {
    const option = flowChartOption(flow)
    const series = option.series as { name: string; type: string; data: number[] }[]

    expect(series.map((s) => [s.name, s.type])).toEqual([
      ['외국인', 'bar'],
      ['기관', 'bar'],
    ])
    expect(series[0].data).toEqual([1_500_000_000, -200_000_000])
    expect(series[1].data).toEqual([-300_000_000, 800_000_000])
    expect((option.xAxis as { data: string[] }).data).toEqual(['10-14', '10-15'])
  })

  it('does not use the price-direction colors for the two groups', () => {
    const option = flowChartOption(flow)

    expect(option.color).toEqual([FLOW_COLORS.foreign, FLOW_COLORS.institution])
    expect(Object.values(FLOW_COLORS)).not.toContain(MARKET_COLORS.up)
    expect(Object.values(FLOW_COLORS)).not.toContain(MARKET_COLORS.down)
  })

  it('handles an empty period', () => {
    const series = flowChartOption([]).series as { data: number[] }[]

    expect(series.map((s) => s.data)).toEqual([[], []])
  })
})

describe('sparklineOption', () => {
  const colorOf = (values: number[]) =>
    ((sparklineOption(values).series as { lineStyle: { color: string } }[])[0].lineStyle.color)

  it('is red when the line ends above its start and blue when it ends below', () => {
    expect(colorOf([100, 101, 105])).toBe(MARKET_COLORS.up)
    expect(colorOf([105, 101, 100])).toBe(MARKET_COLORS.down)
    expect(colorOf([100, 110, 100])).toBe(MARKET_COLORS.flat)
  })

  it('draws no symbols or axes', () => {
    const option = sparklineOption([1, 2, 3])
    const series = (option.series as { showSymbol: boolean; data: number[] }[])[0]

    expect(series.showSymbol).toBe(false)
    expect(series.data).toEqual([1, 2, 3])
    expect((option.xAxis as { show: boolean }).show).toBe(false)
  })
})
