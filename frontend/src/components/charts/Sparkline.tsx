import ReactEChartsCore from 'echarts-for-react/esm/core'
import { echarts } from './echartsSetup'
import { sparklineOption } from './sparklineOption'

interface Props {
  values: number[]
  width?: number | string
  height?: number
}

export function Sparkline({ values, width = 96, height = 32 }: Props) {
  if (values.length < 2) return <div style={{ width, height }} aria-hidden />
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={sparklineOption(values)}
      notMerge
      style={{ width, height }}
      opts={{ renderer: 'canvas' }}
    />
  )
}
