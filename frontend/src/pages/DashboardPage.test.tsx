import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../api/endpoints'
import { MARKET_COLORS } from '../theme/colors'
import {
  makeAlert,
  makeAlerts,
  makeCandles,
  makeHealth,
  makeHolding,
  makeResult,
  makeResults,
  makeSettings,
  makeWatch,
} from '../test/fixtures'
import { renderApp } from '../test/render'
import { DashboardPage } from './DashboardPage'

vi.mock('../api/endpoints')
vi.mock('../components/charts/Sparkline', () => ({
  Sparkline: (props: { values: number[] }) => <div data-testid="sparkline" data-points={props.values.length} />,
}))

function Where() {
  const location = useLocation()
  return <p>at {location.pathname + location.search}</p>
}

function show() {
  return renderApp(
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="*" element={<Where />} />
    </Routes>,
  )
}

const candidates = Array.from({ length: 7 }, (_, i) =>
  makeResult(`90000${i}`, { name: `후보${i}`, score: 70 - i * 5, change_pct: i % 2 === 0 ? 1.5 : -0.8 }),
)

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings({ refresh_seconds: 0 }))
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(makeHealth())
    vi.mocked(endpoints.fetchResults).mockResolvedValue(makeResults(candidates))
    vi.mocked(endpoints.fetchWatchlist).mockResolvedValue([])
    vi.mocked(endpoints.fetchHoldings).mockResolvedValue([])
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([]))
    vi.mocked(endpoints.fetchCandles).mockResolvedValue(makeCandles(40))
  })

  it('shows the top five candidates with their scores and a trend line each', async () => {
    show()

    await screen.findByText('후보0')
    for (const name of ['후보0', '후보1', '후보2', '후보3', '후보4']) expect(screen.getByText(name)).toBeInTheDocument()
    expect(screen.queryByText('후보5')).not.toBeInTheDocument()
    expect(screen.getByText('70.0점')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByTestId('sparkline')).toHaveLength(5))
    expect(screen.getAllByTestId('sparkline')[0]).toHaveAttribute('data-points', '40')
    expect(screen.getAllByText('+1.50%')[0]).toHaveStyle({ color: MARKET_COLORS.up })
    expect(screen.getAllByText('-0.80%')[0]).toHaveStyle({ color: MARKET_COLORS.down })
  })

  it('opens a candidate in the screener', async () => {
    show()

    await userEvent.setup({ pointerEventsCheck: 0 }).click(await screen.findByText('후보1'))

    expect(await screen.findByText('at /screener?stock=900001')).toBeInTheDocument()
  })

  it('suggests running a scan when there is no result yet', async () => {
    vi.mocked(endpoints.fetchResults).mockResolvedValue({ scan_date: null, scan_dates: [], gate: null, items: [] })
    show()

    expect(await screen.findByText(/스캔을 실행하면 후보가 나타납니다/)).toBeInTheDocument()
  })

  it('shows the score of each watched stock and how it changed', async () => {
    vi.mocked(endpoints.fetchWatchlist).mockResolvedValue([
      makeWatch('900010', { name: '관심A', score: 58, change: 6 }),
      makeWatch('900020', { name: '관심B', score: 31, change: -4.5 }),
      makeWatch('900030', { name: '관심C', score: null, change: null }),
    ])
    show()

    await screen.findByText('관심A')
    expect(screen.getByText('58.0점')).toBeInTheDocument()
    expect(screen.getByText('▲ 6.0')).toHaveStyle({ color: MARKET_COLORS.up })
    expect(screen.getByText('▼ 4.5')).toHaveStyle({ color: MARKET_COLORS.down })
    expect(screen.getByText('게이트 미통과')).toBeInTheDocument()
    expect(screen.getByText('3종목')).toBeInTheDocument()
  })

  it('reflects a watchlist that changes', async () => {
    const { client } = show()
    expect(await screen.findByText(/★로 관심종목을 추가하세요/)).toBeInTheDocument()

    vi.mocked(endpoints.fetchWatchlist).mockResolvedValue([makeWatch('900010', { name: '새 관심종목' })])
    await client.invalidateQueries({ queryKey: ['watchlist'] })

    expect(await screen.findByText('새 관심종목')).toBeInTheDocument()
  })

  it('shows a card per holding with its state, trend warning and trend line', async () => {
    vi.mocked(endpoints.fetchHoldings).mockResolvedValue([
      makeHolding(1, { name: '보유A', state: 'rebuy_wait', quantity: 70, start_quantity: 100, last_close: 99000, avg_price: 90000 }),
      makeHolding(2, { code: '900020', name: '보유B', state: 'holding', daily_downtrend: true, last_close: 81000, avg_price: 90000 }),
    ])
    show()

    const cardA = (await screen.findByLabelText('보유A 보유 상태')) as HTMLElement
    expect(within(cardA).getByText('재매수 대기')).toBeInTheDocument()
    expect(within(cardA).getByText('+10.00%')).toHaveStyle({ color: MARKET_COLORS.up })
    expect(within(cardA).getByText(/시작 100/)).toBeInTheDocument()
    expect(within(cardA).getByText('손절선 86,000')).toBeInTheDocument()
    const cardB = screen.getByLabelText('보유B 보유 상태')
    expect(within(cardB).getByText('보유')).toBeInTheDocument()
    expect(within(cardB).getByText('일봉 하락 추세')).toBeInTheDocument()
    expect(within(cardB).getByText('-10.00%')).toHaveStyle({ color: MARKET_COLORS.down })
  })

  it('opens the holding from its card and from a sell alert', async () => {
    vi.mocked(endpoints.fetchHoldings).mockResolvedValue([makeHolding(4, { name: '보유A', state: 'holding' })])
    show()

    await userEvent.setup({ pointerEventsCheck: 0 }).click(await screen.findByRole('link', { name: '보유A' }))

    expect(await screen.findByText('at /holdings?holding=4')).toBeInTheDocument()
  })

  it('takes a sell alert to the holding with the fill form', async () => {
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([makeAlert(8, { kind: 'sell', name: '보유A', holding_id: 4 })]))
    show()

    await userEvent.setup({ pointerEventsCheck: 0 }).click(await screen.findByText('보유A'))

    expect(await screen.findByText('at /holdings?holding=4&alert=8')).toBeInTheDocument()
  })

  it('shows the quantity gained over the cycles', async () => {
    vi.mocked(endpoints.fetchHoldings).mockResolvedValue([makeHolding(1, { name: '보유A', cumulative_increase: 3 })])
    show()

    expect(await screen.findByText('누적 수량 +3')).toHaveStyle({ color: MARKET_COLORS.up })
  })

  it('says there are no holdings yet', async () => {
    show()

    expect(await screen.findByText(/등록한 보유 종목이 없습니다/)).toBeInTheDocument()
  })

  it('lists the latest alerts and how many are unread', async () => {
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
      makeAlerts(
        [
          makeAlert(2, { label: '손절선 이탈 경고', level: 'warning', name: '보유A', suggested_quantity: null, is_read: false }),
          makeAlert(1, { label: '매도 신호', name: '보유B', suggested_quantity: 33, is_read: true }),
        ],
        2,
      ),
    )
    show()

    expect(await screen.findByText('손절선 이탈 경고')).toBeInTheDocument()
    expect(screen.getByText('읽지 않음 2건')).toBeInTheDocument()
    expect(screen.getAllByText(/^제안 /)).toHaveLength(1)
    expect(screen.getByText('제안 33주')).toBeInTheDocument()
  })

  it('shows the collection status of the market data', async () => {
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(
      makeHealth({
        collection: {
          daily: { stale: false, last_success: '2026-10-16T18:00:10+09:00', last_error: null },
          intraday: { stale: true, last_success: null, last_error: 'ConnectionError: timeout' },
        },
      }),
    )
    show()

    expect(await screen.findByText('ConnectionError: timeout')).toBeInTheDocument()
    expect(screen.getByText('지연')).toBeInTheDocument()
    expect(screen.getByText('정상')).toBeInTheDocument()
  })
})
