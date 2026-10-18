import { render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Candle, IndicatorPoint } from '../../api/types'
import { MARKET_COLORS } from '../../theme/colors'
import { PriceChart } from './PriceChart'

// Canvas does not exist in jsdom, so the chart library is replaced by a recorder. What is
// checked here is how the wrapper uses it; the real drawing is checked in the browser test.
const mocks = vi.hoisted(() => {
  const created: FakeChart[] = []

  class FakeSeries {
    data: { time: unknown; value?: number }[] = []
    priceLines: { price: number; title: string }[] = []
    removed: unknown[] = []
    kind: string
    options: Record<string, unknown>
    pane: number
    constructor(kind: string, options: Record<string, unknown>, pane: number) {
      this.kind = kind
      this.options = options
      this.pane = pane
    }
    setData(data: FakeSeries['data']) {
      this.data = data
    }
    createPriceLine(line: { price: number; title: string }) {
      this.priceLines.push(line)
      return line
    }
    removePriceLine(line: unknown) {
      this.removed.push(line)
      this.priceLines = this.priceLines.filter((l) => l !== line)
    }
  }

  class FakeChart {
    series: FakeSeries[] = []
    removed = 0
    stretch: Record<number, number> = {}
    fitted = 0
    element: HTMLElement
    options: Record<string, unknown>
    constructor(element: HTMLElement, options: Record<string, unknown>) {
      this.element = element
      this.options = options
    }
    addSeries(def: string, options: Record<string, unknown>, pane = 0) {
      const series = new FakeSeries(def, options, pane)
      this.series.push(series)
      return series
    }
    panes() {
      return [0, 1, 2, 3].map((index) => ({ setStretchFactor: (f: number) => (this.stretch[index] = f) }))
    }
    timeScale() {
      return { fitContent: () => (this.fitted += 1) }
    }
    remove() {
      this.removed += 1
    }
  }

  const markerPlugins: { series: FakeSeries; markers: unknown[]; setMarkers: (m: unknown[]) => void }[] = []

  return { created, FakeChart, markerPlugins }
})

vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'Candlestick',
  LineSeries: 'Line',
  HistogramSeries: 'Histogram',
  ColorType: { Solid: 'solid' },
  LineStyle: { Dashed: 2 },
  createChart: (element: HTMLElement, options: Record<string, unknown>) => {
    const chart = new mocks.FakeChart(element, options)
    mocks.created.push(chart)
    return chart
  },
  createSeriesMarkers: (series: unknown) => {
    const plugin = {
      series: series as never,
      markers: [] as unknown[],
      setMarkers(markers: unknown[]) {
        plugin.markers = markers
      },
    }
    mocks.markerPlugins.push(plugin)
    return plugin
  },
}))

const candle = (time: string, open: number, close: number, volume = 1000): Candle => ({
  time,
  open,
  high: Math.max(open, close) + 1,
  low: Math.min(open, close) - 1,
  close,
  volume,
  is_complete: true,
})

const point = (time: string, extra: Partial<IndicatorPoint> = {}): IndicatorPoint => ({
  time,
  rsi: 50,
  macd: 1,
  macd_signal: 0.5,
  macd_hist: 0.5,
  bb_lower: 90,
  bb_mid: 100,
  bb_upper: 110,
  pct_b: 0.5,
  bandwidth: 0.2,
  obv: 0,
  atr: 1,
  ...extra,
})

const CANDLES = [candle('2026-10-14', 100, 104), candle('2026-10-15', 104, 101), candle('2026-10-16', 101, 103)]
const POINTS = CANDLES.map((c) => point(c.time))

const chart = () => mocks.created[mocks.created.length - 1]
const find = (kind: string, pane: number, index = 0) =>
  chart().series.filter((s) => s.kind === kind && s.pane === pane)[index]

describe('PriceChart', () => {
  beforeEach(() => {
    mocks.created.length = 0
    mocks.markerPlugins.length = 0
  })

  it('draws everything on one chart, so every pane shares one time axis', () => {
    render(<PriceChart candles={CANDLES} indicators={POINTS} />)

    expect(mocks.created).toHaveLength(1)
    expect(chart().options.autoSize).toBe(true) // follows its container when it resizes
    const panes = chart().series.map((s) => [s.kind, s.pane])
    expect(panes).toEqual([
      ['Candlestick', 0],
      ['Line', 0], // Bollinger upper, middle, lower
      ['Line', 0],
      ['Line', 0],
      ['Histogram', 1], // volume
      ['Line', 2], // RSI
      ['Histogram', 3], // MACD histogram
      ['Line', 3], // MACD
      ['Line', 3], // signal
    ])
  })

  it('colors rising candles red and falling candles blue', () => {
    render(<PriceChart candles={CANDLES} />)

    const options = find('Candlestick', 0).options
    expect(options.upColor).toBe(MARKET_COLORS.up)
    expect(options.borderUpColor).toBe(MARKET_COLORS.up)
    expect(options.downColor).toBe(MARKET_COLORS.down)
    expect(options.wickDownColor).toBe(MARKET_COLORS.down)
  })

  it('gives the volume bars the color of their candle', () => {
    render(<PriceChart candles={CANDLES} />)

    const colors = find('Histogram', 1).data.map((d) => (d as unknown as { color: string }).color)
    expect(colors[0].startsWith(MARKET_COLORS.up)).toBe(true) // 100 -> 104
    expect(colors[1].startsWith(MARKET_COLORS.down)).toBe(true) // 104 -> 101
  })

  it('feeds the same bars to every series, so the panes line up', () => {
    render(<PriceChart candles={CANDLES} indicators={POINTS} />)

    const times = chart().series.map((s) => s.data.map((d) => d.time))
    for (const seriesTimes of times) expect(seriesTimes).toEqual(CANDLES.map((c) => c.time))
  })

  it('leaves a gap, not a wrong value, where an indicator is not available yet', () => {
    const points = [point('2026-10-14', { bb_upper: null, rsi: null }), point('2026-10-15'), point('2026-10-16')]

    render(<PriceChart candles={CANDLES} indicators={points} />)

    expect(find('Line', 0, 0).data[0]).toEqual({ time: '2026-10-14' }) // whitespace point
    expect(find('Line', 0, 0).data[1]).toEqual({ time: '2026-10-15', value: 110 })
    expect(find('Line', 2).data[0]).toEqual({ time: '2026-10-14' })
  })

  it('aligns indicators to candles by time even if the lists differ in length', () => {
    render(<PriceChart candles={CANDLES} indicators={[point('2026-10-16', { rsi: 77 })]} />)

    expect(find('Line', 2).data).toEqual([
      { time: '2026-10-14' },
      { time: '2026-10-15' },
      { time: '2026-10-16', value: 77 },
    ])
  })

  it('shows minute bars on the Korean clock', () => {
    const bars = [{ ...candle('2026-10-16T09:00:00+09:00', 100, 101) }]

    render(<PriceChart candles={bars} />)

    const time = find('Candlestick', 0).data[0].time as number
    expect(new Date(time * 1000).toISOString()).toBe('2026-10-16T09:00:00.000Z')
  })

  it('marks sales and rebuys with arrows, in time order', () => {
    render(
      <PriceChart
        candles={CANDLES}
        markers={[
          { time: '2026-10-16', kind: 'rebuy' },
          { time: '2026-10-14', kind: 'sell', text: '매도 30주' },
        ]}
      />,
    )

    const [plugin] = mocks.markerPlugins
    expect(plugin.markers).toEqual([
      { time: '2026-10-14', position: 'aboveBar', shape: 'arrowDown', color: MARKET_COLORS.down, text: '매도 30주' },
      { time: '2026-10-16', position: 'belowBar', shape: 'arrowUp', color: MARKET_COLORS.up, text: '재매수' },
    ])
    expect(plugin.series).toBe(find('Candlestick', 0))
  })

  it('draws price lines and replaces them when they change', () => {
    const { rerender } = render(
      <PriceChart candles={CANDLES} priceLines={[{ price: 98.79, title: '재매수 목표가' }, { price: 90, title: '손절선' }]} />,
    )
    const candles = find('Candlestick', 0)
    expect(candles.priceLines.map((l) => [l.price, l.title])).toEqual([
      [98.79, '재매수 목표가'],
      [90, '손절선'],
    ])

    rerender(<PriceChart candles={CANDLES} priceLines={[{ price: 91, title: '손절선' }]} />)

    expect(candles.removed).toHaveLength(2)
    expect(candles.priceLines.map((l) => [l.price, l.title])).toEqual([[91, '손절선']])
  })

  it('marks the RSI 30 and 70 levels', () => {
    render(<PriceChart candles={CANDLES} />)

    expect(find('Line', 2).priceLines.map((l) => l.price).sort()).toEqual([30, 70])
  })

  it('gives the price pane the most room', () => {
    render(<PriceChart candles={CANDLES} />)

    const { stretch } = chart()
    expect(stretch[0]).toBeGreaterThan(stretch[1])
    expect(stretch[0]).toBeGreaterThan(stretch[2])
    expect(stretch[0]).toBeGreaterThan(stretch[3])
  })

  it('updates the data without building a new chart', () => {
    const { rerender } = render(<PriceChart candles={CANDLES} />)

    rerender(<PriceChart candles={[...CANDLES, candle('2026-10-19', 103, 107)]} />)

    expect(mocks.created).toHaveLength(1)
    expect(find('Candlestick', 0).data).toHaveLength(4)
    expect(chart().removed).toBe(0)
  })

  it('removes the chart when it unmounts', () => {
    const { unmount } = render(<PriceChart candles={CANDLES} />)

    unmount()

    expect(chart().removed).toBe(1)
  })

  it('takes its height from the prop', () => {
    const { getByTestId } = render(<PriceChart candles={CANDLES} height={333} />)

    expect(getByTestId('price-chart')).toHaveStyle({ height: '333px' })
  })
})
