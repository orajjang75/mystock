import type { EChartsOption } from 'echarts'
import { directionColor } from '../../theme/colors'

/** A small trend line: red when it ends above where it began, blue when below. */
export function sparklineOption(values: number[]): EChartsOption {
  const color = directionColor(values.length > 1 ? values[values.length - 1] - values[0] : 0)
  return {
    animation: false,
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: 'category', show: false, data: values.map((_, i) => i) },
    yAxis: { type: 'value', show: false, scale: true },
    series: [
      {
        type: 'line',
        data: values,
        showSymbol: false,
        silent: true,
        lineStyle: { width: 1.5, color },
        areaStyle: { color, opacity: 0.08 },
      },
    ],
  }
}
