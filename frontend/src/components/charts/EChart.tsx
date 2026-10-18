import type { EChartsOption } from 'echarts'
import ReactEChartsCore from 'echarts-for-react/esm/core'
import { echarts } from './echartsSetup'

interface Props {
  option: EChartsOption
  height?: number
  /** Read by tests and screen readers: what the chart shows. */
  label?: string
}

/** Any ECharts chart that is not a price chart (PRD 7장: 자산 곡선, 수량 증가 추이, 히트맵 ...). */
export function EChart({ option, height = 280, label }: Props) {
  return (
    <div role="img" aria-label={label} data-testid="echart">
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge
        style={{ width: '100%', height }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}
