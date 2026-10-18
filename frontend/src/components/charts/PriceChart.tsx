import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import type { Candle, IndicatorPoint } from '../../api/types'
import { BRAND_PRIMARY, MARKET_COLORS } from '../../theme/colors'
import { toChartTime } from './chartTime'

export interface PriceMarker {
  /** Same label format as the candles' ``time``. */
  time: string
  kind: 'sell' | 'rebuy'
  text?: string
}

export interface PriceLineSpec {
  price: number
  title: string
  color?: string
}

interface Props {
  candles: Candle[]
  /** Indicator values for the same bars; points missing a value are left blank on the axis. */
  indicators?: IndicatorPoint[]
  markers?: PriceMarker[]
  priceLines?: PriceLineSpec[]
  height?: number
}

// Pane order: 0 price (+ Bollinger), 1 volume, 2 RSI, 3 MACD. All panes belong to one chart, so
// they share a single time axis and scroll, zoom and crosshair together.
const PANE = { price: 0, volume: 1, rsi: 2, macd: 3 } as const

const BAND = '#9aa4b2'
const WON = { type: 'price', precision: 0, minMove: 1 } as const
const alpha = (hex: string, a: number) =>
  `${hex}${Math.round(a * 255)
    .toString(16)
    .padStart(2, '0')}`

interface Series {
  candles: ISeriesApi<'Candlestick'>
  bbUpper: ISeriesApi<'Line'>
  bbMid: ISeriesApi<'Line'>
  bbLower: ISeriesApi<'Line'>
  volume: ISeriesApi<'Histogram'>
  rsi: ISeriesApi<'Line'>
  macdHist: ISeriesApi<'Histogram'>
  macd: ISeriesApi<'Line'>
  macdSignal: ISeriesApi<'Line'>
}

function lineData(candles: Candle[], points: IndicatorPoint[] | undefined, pick: (p: IndicatorPoint) => number | null) {
  const byTime = new Map(points?.map((p) => [p.time, pick(p)]))
  return candles.map((candle) => {
    const value = byTime.get(candle.time)
    const time = toChartTime(candle.time)
    return value === null || value === undefined ? { time } : { time, value }
  })
}

/**
 * A thin React wrapper around Lightweight Charts: candles (rising red, falling blue), Bollinger
 * bands, buy/sell markers and price lines on the price pane, and volume, RSI and MACD panes
 * below it on the same time axis.
 */
export function PriceChart({ candles, indicators, markers = [], priceLines = [], height = 520 }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const series = useRef<Series | null>(null)
  const markerPlugin = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const lines = useRef<IPriceLine[]>([])

  // create once, remove on unmount
  useEffect(() => {
    if (!container.current) return
    const chart = createChart(container.current, {
      autoSize: true, // follows the container's size (window resize, Drawer, tabs)
      layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#595959', panes: { separatorColor: '#e8e8e8' } },
      grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
      rightPriceScale: { borderColor: '#e8e8e8' },
      timeScale: { borderColor: '#e8e8e8', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    })
    const up = MARKET_COLORS.up
    const down = MARKET_COLORS.down
    const s: Series = {
      candles: chart.addSeries(
        CandlestickSeries,
        {
          upColor: up,
          borderUpColor: up,
          wickUpColor: up,
          downColor: down,
          borderDownColor: down,
          wickDownColor: down,
          priceFormat: WON, // KRW prices are whole numbers
        },
        PANE.price,
      ),
      bbUpper: chart.addSeries(LineSeries, { color: BAND, lineWidth: 1, priceFormat: WON, priceLineVisible: false, lastValueVisible: false }, PANE.price),
      bbMid: chart.addSeries(LineSeries, { color: BAND, lineWidth: 1, lineStyle: LineStyle.Dashed, priceFormat: WON, priceLineVisible: false, lastValueVisible: false }, PANE.price),
      bbLower: chart.addSeries(LineSeries, { color: BAND, lineWidth: 1, priceFormat: WON, priceLineVisible: false, lastValueVisible: false }, PANE.price),
      volume: chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, PANE.volume),
      rsi: chart.addSeries(LineSeries, { color: BRAND_PRIMARY, lineWidth: 1, priceLineVisible: false }, PANE.rsi),
      macdHist: chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, PANE.macd),
      macd: chart.addSeries(LineSeries, { color: BRAND_PRIMARY, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, PANE.macd),
      macdSignal: chart.addSeries(LineSeries, { color: '#fa8c16', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, PANE.macd),
    }
    s.rsi.createPriceLine({ price: 70, color: alpha(up, 0.6), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '' })
    s.rsi.createPriceLine({ price: 30, color: alpha(down, 0.6), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '' })

    const panes = chart.panes()
    panes[PANE.price]?.setStretchFactor(5)
    panes[PANE.volume]?.setStretchFactor(1.2)
    panes[PANE.rsi]?.setStretchFactor(1.4)
    panes[PANE.macd]?.setStretchFactor(1.6)

    markerPlugin.current = createSeriesMarkers(s.candles, [])
    chartRef.current = chart
    series.current = s
    return () => {
      markerPlugin.current = null
      series.current = null
      chartRef.current = null
      lines.current = []
      chart.remove()
    }
  }, [])

  // price, bands, volume and indicator panes
  useEffect(() => {
    const s = series.current
    if (!s) return
    s.candles.setData(
      candles.map((c) => ({ time: toChartTime(c.time), open: c.open, high: c.high, low: c.low, close: c.close })),
    )
    s.volume.setData(
      candles.map((c) => ({
        time: toChartTime(c.time),
        value: c.volume,
        color: alpha(c.close >= c.open ? MARKET_COLORS.up : MARKET_COLORS.down, 0.55),
      })),
    )
    s.bbUpper.setData(lineData(candles, indicators, (p) => p.bb_upper))
    s.bbMid.setData(lineData(candles, indicators, (p) => p.bb_mid))
    s.bbLower.setData(lineData(candles, indicators, (p) => p.bb_lower))
    s.rsi.setData(lineData(candles, indicators, (p) => p.rsi))
    s.macd.setData(lineData(candles, indicators, (p) => p.macd))
    s.macdSignal.setData(lineData(candles, indicators, (p) => p.macd_signal))
    const hist = new Map(indicators?.map((p) => [p.time, p.macd_hist]))
    s.macdHist.setData(
      candles.map((c) => {
        const value = hist.get(c.time)
        const time = toChartTime(c.time)
        if (value === null || value === undefined) return { time }
        return { time, value, color: alpha(value >= 0 ? MARKET_COLORS.up : MARKET_COLORS.down, 0.7) }
      }),
    )
    chartRef.current?.timeScale().fitContent()
  }, [candles, indicators])

  // buy/sell markers
  useEffect(() => {
    const plugin = markerPlugin.current
    if (!plugin) return
    const sorted: SeriesMarker<Time>[] = markers
      .map((m) => ({
        time: toChartTime(m.time),
        position: m.kind === 'sell' ? ('aboveBar' as const) : ('belowBar' as const),
        shape: m.kind === 'sell' ? ('arrowDown' as const) : ('arrowUp' as const),
        color: m.kind === 'sell' ? MARKET_COLORS.down : MARKET_COLORS.up,
        text: m.text ?? (m.kind === 'sell' ? '매도' : '재매수'),
      }))
      .sort((a, b) => Number(a.time) - Number(b.time) || String(a.time).localeCompare(String(b.time)))
    plugin.setMarkers(sorted)
  }, [markers])

  // horizontal price lines (rebuy target, ATR stop)
  useEffect(() => {
    const s = series.current
    if (!s) return
    for (const line of lines.current) s.candles.removePriceLine(line)
    lines.current = priceLines.map((spec) =>
      s.candles.createPriceLine({
        price: spec.price,
        title: spec.title,
        color: spec.color ?? BRAND_PRIMARY,
        lineStyle: LineStyle.Dashed,
        lineWidth: 1,
        axisLabelVisible: true,
      }),
    )
  }, [priceLines])

  return <div ref={container} style={{ width: '100%', height }} data-testid="price-chart" />
}
