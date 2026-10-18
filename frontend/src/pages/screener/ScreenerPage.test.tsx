import { AxiosError, AxiosHeaders } from 'axios'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../../api/endpoints'
import { MARKET_COLORS } from '../../theme/colors'
import {
  makeCandles,
  makeFlow,
  makeHealth,
  makeIndicatorPoints,
  makeResult,
  makeResults,
  makeSettings,
  makeWatch,
} from '../../test/fixtures'
import { renderApp } from '../../test/render'
import { ScreenerPage } from './ScreenerPage'

vi.mock('../../api/endpoints')
vi.mock('../../components/charts/PriceChart', () => ({
  PriceChart: (props: { candles: unknown[]; indicators?: unknown[] }) => (
    <div data-testid="price-chart" data-candles={props.candles.length} data-indicators={props.indicators?.length} />
  ),
}))
vi.mock('../../components/charts/FlowBarChart', () => ({
  FlowBarChart: (props: { flow: unknown[] }) => <div data-testid="flow-chart" data-days={props.flow.length} />,
}))

const user = () => userEvent.setup({ delay: null, pointerEventsCheck: 0 })

function conflict(detail: string): AxiosError {
  const config = { headers: new AxiosHeaders(), url: '/api/screener/run' }
  return new AxiosError('409', 'ERR_BAD_REQUEST', config, null, {
    status: 409,
    statusText: '',
    headers: {},
    config,
    data: { detail },
  })
}

const RESULTS = [
  makeResult('900010', { name: '모의A', score: 40, change_pct: -2.1, trading_value: 3_000_000_000 }),
  makeResult('900020', { name: '모의B', score: 58, change_pct: 3.2, trading_value: 9_000_000_000 }),
  makeResult('900030', { name: '모의C', score: 52, change_pct: 0, trading_value: 1_500_000_000, in_watchlist: true }),
]

function show(route = '/screener') {
  return renderApp(<ScreenerPage />, { route })
}

describe('ScreenerPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings({ refresh_seconds: 0 }))
    vi.mocked(endpoints.fetchResults).mockResolvedValue(makeResults(RESULTS))
    vi.mocked(endpoints.fetchWatchlist).mockResolvedValue([makeWatch('900030')])
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(makeHealth())
    const candles = makeCandles()
    vi.mocked(endpoints.fetchCandles).mockResolvedValue(candles)
    vi.mocked(endpoints.fetchIndicators).mockResolvedValue({
      code: '900010',
      bar: '1d',
      points: makeIndicatorPoints(candles),
      flow: makeFlow(),
    })
  })

  const rows = () => screen.getAllByRole('row').slice(1)

  it('lists the results by score, highest first', async () => {
    show()

    await screen.findByText('모의B')
    expect(rows().map((row) => within(row).getByText(/^모의[ABC]$/).textContent)).toEqual(['모의B', '모의C', '모의A'])
    expect(within(rows()[0]).getByText('58.0')).toBeInTheDocument()
  })

  it('shows the condition tags, the trading value and the price change', async () => {
    show()

    const row = rows ? (await screen.findByText('모의B')).closest('tr') : null
    expect(row).not.toBeNull()
    const inRow = within(row as HTMLElement)
    expect(inRow.getAllByText('52주 낙폭').length).toBeGreaterThan(0)
    expect(inRow.getAllByText('거래량 3배').length).toBeGreaterThan(0)
    expect(inRow.getByText('90.0억')).toBeInTheDocument()
    expect(inRow.getByText('67,405')).toBeInTheDocument()
  })

  it('colors a rise red and a fall blue', async () => {
    show()

    await screen.findByText('모의B')
    expect(screen.getByText('+3.20%')).toHaveStyle({ color: MARKET_COLORS.up })
    expect(screen.getByText('-2.10%')).toHaveStyle({ color: MARKET_COLORS.down })
    expect(screen.getByText('0.00%')).toHaveStyle({ color: MARKET_COLORS.flat })
  })

  it('summarises the conditions in a bar', async () => {
    show()

    const bar = await screen.findByLabelText('조건 요약')
    await waitFor(() => expect(within(bar).getByText(/거래대금 ≥ 10.0억/)).toBeInTheDocument())
    expect(within(bar).getByText(/52주 낙폭 ≤ -30% 그리고 \(이격도 ≤ -8%/)).toBeInTheDocument()
    expect(within(bar).getByText(/배점 반전 30 · 확인 30 · 거래량 20 · 수급 20/)).toBeInTheDocument()
    expect(within(bar).getByText(/스캔 일자 2026-10-16 · 결과 3종목/)).toBeInTheDocument()
  })

  it('says when the gate was relaxed or replaced by a decline ranking', async () => {
    vi.mocked(endpoints.fetchResults).mockResolvedValue(
      makeResults(RESULTS, { gate: { mode: 'relaxed', drawdown_threshold_pct: -20 } }),
    )
    show()
    const bar = await screen.findByLabelText('조건 요약')
    expect(await within(bar).findByText('낙폭 기준 완화 적용')).toBeInTheDocument()
    expect(within(bar).getByText(/52주 낙폭 ≤ -20%/)).toBeInTheDocument()
  })

  it('offers the past scan dates and loads the one picked', async () => {
    const u = user()
    show()
    await screen.findByText('모의B')

    await u.click(screen.getByRole('combobox', { name: '스캔 일자' }))
    const option = await screen.findByText(/2026-10-15/, { selector: '.ant-select-item-option-content' })
    await u.click(option)

    await waitFor(() => expect(endpoints.fetchResults).toHaveBeenCalledWith({ scan_date: '2026-10-15' }))
  })

  it('runs a scan on demand and reports what it found', async () => {
    vi.mocked(endpoints.runScan).mockResolvedValue({
      scan_date: '2026-10-16',
      universe_size: 120,
      gate_mode: 'strict',
      drawdown_threshold_pct: -30,
      gated: 24,
      saved: 24,
      elapsed_seconds: 0.9,
    })
    const u = user()
    show()
    await screen.findByText('모의B')

    await u.click(screen.getByRole('button', { name: /스캔 실행/ }))

    await waitFor(() => expect(endpoints.runScan).toHaveBeenCalledWith({}))
    expect(await screen.findByText(/120종목 중 24개가 게이트를 통과했고 24개를 저장했습니다 \(0.9초\)/)).toBeInTheDocument()
  })

  it('shows why a scan could not run', async () => {
    vi.mocked(endpoints.runScan).mockRejectedValue(conflict('The scan universe is empty; run the ingest job first.'))
    const u = user()
    show()
    await screen.findByText('모의B')

    await u.click(screen.getByRole('button', { name: /스캔 실행/ }))

    expect(await screen.findByText('The scan universe is empty; run the ingest job first.')).toBeInTheDocument()
  })

  it('invites a first scan when there are no results yet', async () => {
    vi.mocked(endpoints.fetchResults).mockResolvedValue({ scan_date: null, scan_dates: [], gate: null, items: [] })
    show()

    expect(await screen.findByText(/아직 스캔한 결과가 없습니다/)).toBeInTheDocument()
  })

  it('sorts by trading value when that header is clicked', async () => {
    const u = user()
    show()
    await screen.findByText('모의B')

    await u.click(screen.getByRole('columnheader', { name: '거래대금' }))

    const names = rows().map((row) => within(row).getByText(/^모의[ABC]$/).textContent)
    expect(names).toEqual(['모의C', '모의A', '모의B']) // 15억, 30억, 90억
  })

  // --- watchlist stars ----------------------------------------------------------------------

  it('adds a stock to the watchlist from its star without opening the drawer', async () => {
    vi.mocked(endpoints.addToWatchlist).mockResolvedValue()
    const u = user()
    show()
    await screen.findByText('모의B')

    await u.click(screen.getByRole('button', { name: '900020 관심종목 추가' }))

    await waitFor(() => expect(endpoints.addToWatchlist).toHaveBeenCalledWith('900020'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('removes a watched stock from its star', async () => {
    vi.mocked(endpoints.removeFromWatchlist).mockResolvedValue()
    const u = user()
    show()
    await screen.findByText('모의C')

    await u.click(screen.getByRole('button', { name: '900030 관심종목 제외' }))

    await waitFor(() => expect(endpoints.removeFromWatchlist).toHaveBeenCalledWith('900030'))
  })

  // --- the detail drawer --------------------------------------------------------------------

  it('opens the stock detail with the chart, the evidence and the flow', async () => {
    const u = user()
    show()

    await u.click(await screen.findByText('모의B'))

    const drawer = await screen.findByRole('dialog')
    expect(await within(drawer).findByTestId('price-chart')).toHaveAttribute('data-candles', '30')
    expect(within(drawer).getByTestId('price-chart')).toHaveAttribute('data-indicators', '30') // same bars
    expect(within(drawer).getByTestId('flow-chart')).toHaveAttribute('data-days', '2')
    expect(within(drawer).getByText('58.0점')).toBeInTheDocument()
    expect(within(drawer).getByText('충족 조건')).toBeInTheDocument()
    expect(within(drawer).getByText('52주 고점 대비 낙폭')).toBeInTheDocument()
    expect(within(drawer).getByText('-35.2%')).toBeInTheDocument()
    expect(within(drawer).getByText('3.40배')).toBeInTheDocument()
    expect(within(drawer).getByText('점수 구성 (총 58.0점)')).toBeInTheDocument()
    expect(within(drawer).getByText('18.0점')).toBeInTheDocument() // the 확인 section
    expect(endpoints.fetchCandles).toHaveBeenCalledWith('900020', '1d', 250)
    expect(endpoints.fetchIndicators).toHaveBeenCalledWith('900020', '1d', 250)
  })

  it('shows the 수급 미반영 tag and explains the rescaling', async () => {
    vi.mocked(endpoints.fetchResults).mockResolvedValue(
      makeResults([
        makeResult('900040', {
          name: '모의D',
          flow_unreflected: true,
          tags: [
            { key: 'drawdown', label: '52주 낙폭' },
            { key: 'flow_unreflected', label: '수급 미반영' },
          ],
        }),
      ]),
    )
    const u = user()
    show()

    expect(await screen.findByText('수급 미반영')).toBeInTheDocument() // in the table
    await u.click(screen.getByText('모의D'))

    const drawer = await screen.findByRole('dialog')
    expect(within(drawer).getByText('수급 미반영')).toBeInTheDocument()
    expect(within(drawer).getByText(/100점 기준으로 환산/)).toBeInTheDocument()
  })

  it('opens straight from a link and closes back to the list', async () => {
    const u = user()
    show('/screener?stock=900010')

    const drawer = await screen.findByRole('dialog')
    expect(await within(drawer).findByText('모의A')).toBeInTheDocument()

    await u.click(within(drawer).getByRole('button', { name: /close/i }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('still shows the chart of a stock that is not in this scan', async () => {
    show('/screener?stock=900099')

    const drawer = await screen.findByRole('dialog')
    expect(await within(drawer).findByText(/스캔 결과에는 없는 종목입니다/)).toBeInTheDocument()
    expect(await within(drawer).findByTestId('price-chart')).toBeInTheDocument()
  })

  it('says so when the chart data cannot be loaded', async () => {
    vi.mocked(endpoints.fetchCandles).mockRejectedValue(new Error('down'))
    show('/screener?stock=900010')

    expect(await screen.findByText('차트 데이터를 불러오지 못했습니다')).toBeInTheDocument()
  })

  // --- the watchlist view -------------------------------------------------------------------

  it('switches to the watchlist with scores, changes and a remove button', async () => {
    vi.mocked(endpoints.fetchWatchlist).mockResolvedValue([
      makeWatch('900030', { name: '모의C', score: 52, previous_score: 49, change: 3 }),
      makeWatch('900050', { name: '모의E', score: null, previous_score: 40, change: null }),
      makeWatch('900060', { name: '모의F', score: 31, previous_score: 35, change: -4 }),
    ])
    vi.mocked(endpoints.removeFromWatchlist).mockResolvedValue()
    const u = user()
    show()
    await screen.findByText('모의B')

    await u.click(screen.getByText(/관심종목 3/))

    expect(await screen.findByText('▲ 3.0')).toHaveStyle({ color: MARKET_COLORS.up })
    expect(screen.getByText('▼ 4.0')).toHaveStyle({ color: MARKET_COLORS.down })
    expect(screen.getByText('게이트 미통과')).toBeInTheDocument()
    expect(screen.getByText('52.0')).toBeInTheDocument()

    await u.click(within(screen.getByText('모의C').closest('tr') as HTMLElement).getByRole('button', { name: '제외' }))
    await waitFor(() => expect(endpoints.removeFromWatchlist).toHaveBeenCalledWith('900030'))
  })

  it('says how to add the first watched stock', async () => {
    vi.mocked(endpoints.fetchWatchlist).mockResolvedValue([])
    const u = user()
    show('/screener?view=watchlist')

    expect(await screen.findByText(/관심종목이 없습니다/)).toBeInTheDocument()
    await u.click(screen.getByText('전체 결과'))
    expect(await screen.findByText('모의B')).toBeInTheDocument()
  })
})
