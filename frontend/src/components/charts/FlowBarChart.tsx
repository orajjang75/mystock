import ReactEChartsCore from 'echarts-for-react/esm/core'
import type { FlowPoint } from '../../api/types'
import { echarts } from './echartsSetup'
import { flowChartOption } from './flowOption'

interface Props {
  flow: FlowPoint[]
  height?: number
}

/** 외국인·기관 순매수 막대 (ECharts). */
export function FlowBarChart({ flow, height = 220 }: Props) {
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={flowChartOption(flow)}
      notMerge
      style={{ width: '100%', height }}
      opts={{ renderer: 'canvas' }}
    />
  )
}
