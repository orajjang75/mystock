import type { EChartsOption } from 'echarts'
import type {
  CompareRow,
  Fold,
  HorizonBlock,
  SensitivityGrid,
  SeriesKey,
} from '../../features/backtest/result'

// Not red or blue: those mean up and down on this app's screens.
export const SERIES_COLORS: Record<SeriesKey | 'hold', string> = {
  strategy: '#7c4dff',
  universe: '#8c8c8c',
  random: '#fa8c16',
  kospi: '#13c2c2',
  hold: '#8c8c8c',
}
export const SERIES_LABELS: Record<SeriesKey, string> = {
  strategy: '후보',
  universe: '유니버스 전체',
  random: '무작위 진입',
  kospi: 'KOSPI',
}

const pct = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined ? '-' : `${(value * 100).toFixed(digits)}%`

export interface LineSeries {
  name: string
  values: (number | null)[]
  color: string
  dashed?: boolean
}

/** Lines over a shared x axis (dates or bar times). */
export function lineOption(x: string[], series: LineSeries[], opts: { unit?: string } = {}): EChartsOption {
  return {
    animation: false,
    color: series.map((s) => s.color),
    grid: { left: 56, right: 16, top: 36, bottom: 36 },
    legend: { top: 0, data: series.map((s) => s.name), itemWidth: 14, itemHeight: 8 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: x, axisLabel: { hideOverlap: true } },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { formatter: (value: number) => `${value}${opts.unit ?? ''}` },
    },
    series: series.map((s) => ({
      name: s.name,
      type: 'line' as const,
      data: s.values,
      showSymbol: false,
      smooth: false,
      lineStyle: { width: 2, type: s.dashed ? ('dashed' as const) : ('solid' as const) },
    })),
  }
}

/** 보유 기간별 중앙값: the scanner's picks against the three baselines. */
export function horizonOption(horizons: Record<string, HorizonBlock>): EChartsOption {
  const keys = Object.keys(horizons).sort((a, b) => Number(a) - Number(b))
  const names: SeriesKey[] = ['strategy', 'universe', 'random', 'kospi']
  return {
    animation: false,
    color: names.map((n) => SERIES_COLORS[n]),
    grid: { left: 56, right: 16, top: 36, bottom: 32 },
    legend: { top: 0, data: names.map((n) => SERIES_LABELS[n]), itemWidth: 12, itemHeight: 8 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => pct(Number(v) / 100) },
    xAxis: { type: 'category', data: keys.map((k) => `${k}일`) },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => `${v}%` } },
    series: names.map((n) => ({
      name: SERIES_LABELS[n],
      type: 'bar' as const,
      barMaxWidth: 18,
      data: keys.map((k) => {
        const median = horizons[k][n].median
        return median === undefined ? null : Number((median * 100).toFixed(4))
      }),
    })),
  }
}

export const COMPARE_METRICS = {
  mean_increase_rate: { label: '사이클당 평균 수량 증가율', format: (v: number) => `${(v * 100).toFixed(2)}%`, scale: 100 },
  completion_rate: { label: '사이클 성공률', format: (v: number) => `${(v * 100).toFixed(1)}%`, scale: 100 },
  cumulative_increase_pct: { label: '누적 수량 증가(시작 수량 대비 %)', format: (v: number) => `${v.toFixed(2)}%`, scale: 1 },
  total_return: { label: '수익률', format: (v: number) => `${(v * 100).toFixed(2)}%`, scale: 100 },
} as const
export type CompareMetric = keyof typeof COMPARE_METRICS

/** 봉 길이별 비교: one bar per bar length for the chosen metric. */
export function compareOption(rows: CompareRow[], metric: CompareMetric): EChartsOption {
  const meta = COMPARE_METRICS[metric]
  return {
    animation: false,
    color: ['#7c4dff'],
    grid: { left: 56, right: 16, top: 32, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const first = (Array.isArray(params) ? params[0] : params) as { dataIndex: number }
        const row = rows[first.dataIndex]
        const value = row[metric]
        return `${row.bar_length}<br/>${meta.label}: ${value === null ? '-' : meta.format(value)}<br/>끝난 매도 ${row.finished}건 · 신호 발생일 ${row.signal_dates}일`
      },
    },
    xAxis: { type: 'category', data: rows.map((r) => r.bar_length) },
    yAxis: { type: 'value', name: meta.label, nameTextStyle: { align: 'left' }, axisLabel: { formatter: (v: number) => `${v}%` } },
    series: [
      {
        type: 'bar',
        barMaxWidth: 36,
        data: rows.map((r) => {
          const value = r[metric]
          return value === null ? null : Number((value * (metric === 'cumulative_increase_pct' ? 1 : 100)).toFixed(4))
        }),
        label: { show: true, position: 'top', formatter: (p: unknown) => `n=${rows[(p as { dataIndex: number }).dataIndex].finished}` },
      },
    ],
  }
}

export const METRIC_LABELS: Record<string, string> = {
  median_return: '후보 수익률 중앙값',
  mean_return: '후보 수익률 평균',
  win_rate: '승률',
  profit_factor: '손익비(PF)',
  n_dates: '신호 발생일 수',
  candidates_per_day: '일평균 후보 수',
  mean_increase_rate: '사이클당 평균 수량 증가율',
  completion_rate: '사이클 성공률',
  gain_rate: '수량이 늘어난 비율',
  cumulative_increase_pct: '누적 수량 증가(%)',
  max_drawdown: '최대 낙폭',
  excess_return: '보유 대비 초과 수익률',
}

/** 파라미터 민감도 히트맵. ``smoothed`` shows each cell's 3x3 neighbourhood mean instead. */
export function heatmapOption(grid: SensitivityGrid, smoothed: boolean): EChartsOption {
  const source = smoothed ? grid.smoothed : grid.cells
  const xs = grid.x.values.map((v) => String(v))
  const ys = grid.y ? grid.y.values.map((v) => String(v)) : ['']
  const finite = source.flat().filter((v): v is number => v !== null)
  const min = finite.length ? Math.min(...finite) : 0
  const max = finite.length ? Math.max(...finite) : 1
  const mark = (pick: { x: number; y: number | null } | null) => {
    if (!pick) return null
    return [grid.x.values.indexOf(pick.x), grid.y && pick.y !== null ? grid.y.values.indexOf(pick.y) : 0]
  }
  const best = mark(smoothed ? grid.robust_best : grid.best)
  const data = source.flatMap((row, iy) =>
    row.map((value, ix) => ({
      value: [ix, iy, value],
      itemStyle:
        best && best[0] === ix && best[1] === iy ? { borderColor: '#262626', borderWidth: 3 } : undefined,
    })),
  )
  return {
    animation: false,
    grid: { left: 80, right: 24, top: 16, bottom: 104 },
    tooltip: {
      formatter: (params: unknown) => {
        const [ix, iy, value] = (params as { value: [number, number, number | null] }).value
        const n = grid.samples[iy][ix]
        const label = grid.y ? `${grid.y.path}=${ys[iy]}<br/>` : ''
        return `${label}${grid.x.path}=${xs[ix]}<br/>${value === null ? '표본 부족' : value.toFixed(4)} (표본 ${n})`
      },
    },
    xAxis: { type: 'category', data: xs, name: grid.x.path, nameLocation: 'middle', nameGap: 30, splitArea: { show: true } },
    yAxis: { type: 'category', data: ys, name: grid.y?.path ?? '', splitArea: { show: true } },
    visualMap: {
      min,
      max: max === min ? min + 1 : max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 4,
      inRange: { color: ['#f3edff', '#7c4dff'] },
    },
    series: [
      {
        type: 'heatmap',
        data,
        label: {
          show: true,
          formatter: (p: unknown) => {
            const value = (p as { value: [number, number, number | null] }).value[2]
            return value === null ? '-' : value.toFixed(3)
          },
        },
      },
    ],
  }
}

/** Walk-forward: the metric on the training windows against the unseen test windows. */
export function walkForwardOption(folds: Fold[]): EChartsOption {
  const x = folds.map((f) => `${f.fold}`)
  return lineOption(
    x,
    [
      { name: '학습(고른 값)', values: folds.map((f) => f.train_metric), color: '#8c8c8c', dashed: true },
      { name: '검증(고른 값)', values: folds.map((f) => f.test_metric), color: '#7c4dff' },
      { name: '검증(기본값)', values: folds.map((f) => f.default_test_metric), color: '#fa8c16' },
    ],
    {},
  )
}
