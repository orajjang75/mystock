import type { EChartsOption } from 'echarts'
import type { FlowPoint } from '../../api/types'
import { formatAmount } from '../../lib/format'

// Not red/blue: those are reserved for price direction. Foreign and institution just need to
// be told apart.
export const FLOW_COLORS = { foreign: '#7c4dff', institution: '#fa8c16' } as const

/** The ECharts option for the 외국인·기관 순매수 bars (amounts in 원, shown as 억/조). */
export function flowChartOption(flow: FlowPoint[]): EChartsOption {
  return {
    animation: false,
    color: [FLOW_COLORS.foreign, FLOW_COLORS.institution],
    grid: { left: 56, right: 12, top: 32, bottom: 28 },
    legend: { top: 0, data: ['외국인', '기관'], itemWidth: 12, itemHeight: 8 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value) => formatAmount(Number(value)),
    },
    xAxis: { type: 'category', data: flow.map((p) => p.date.slice(5)), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', axisLabel: { formatter: (value: number) => formatAmount(value) } },
    series: [
      { name: '외국인', type: 'bar', data: flow.map((p) => p.foreign_net_buy), barMaxWidth: 10 },
      { name: '기관', type: 'bar', data: flow.map((p) => p.institution_net_buy), barMaxWidth: 10 },
    ],
  }
}
