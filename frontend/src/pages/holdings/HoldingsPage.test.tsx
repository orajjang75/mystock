import { AxiosError, AxiosHeaders } from 'axios'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../../api/endpoints'
import { MARKET_COLORS } from '../../theme/colors'
import {
  makeAlert,
  makeAlerts,
  makeCandles,
  makeCycle,
  makeCycles,
  makeHolding,
  makeIndicatorPoints,
  makeResults,
  makeSettings,
} from '../../test/fixtures'
import { renderApp } from '../../test/render'
import { HoldingsPage } from './HoldingsPage'

vi.mock('../../api/endpoints')
vi.mock('../../components/charts/PriceChart', () => ({
  PriceChart: (props: { candles: { time: string }[]; markers?: unknown[]; priceLines?: unknown[] }) => (
    <div
      data-testid="price-chart"
      data-first={props.candles[0]?.time}
      data-markers={JSON.stringify(props.markers ?? [])}
      data-lines={JSON.stringify(props.priceLines ?? [])}
    />
  ),
}))

const user = () => userEvent.setup({ delay: null, pointerEventsCheck: 0 })

const WAITING = makeCycle(1, { state: 'rebuy_wait', sell_quantity: 100, rebuy_target_price: 288018 })
const HOLDINGS = [
  makeHolding(1, { name: '모의A', code: '900040', state: 'holding', quantity: 300, start_quantity: 300, avg_price: 263761, last_close: 293068, stop_price: 253125 }),
  makeHolding(2, { name: '모의B', code: '900010', state: 'rebuy_wait', quantity: 200, start_quantity: 300, open_cycle: WAITING, cumulative_increase: 5 }),
  makeHolding(3, { name: '모의C', code: '900020', state: 'expired', quantity: 200, open_cycle: { ...WAITING, id: 9, state: 'expired' }, daily_downtrend: true }),
]

function notFound(): AxiosError {
  const config = { headers: new AxiosHeaders(), url: '/api/holdings' }
  return new AxiosError('422', 'ERR_BAD_REQUEST', config, null, {
    status: 422,
    statusText: '',
    headers: {},
    config,
    data: { detail: 'Unknown stock 999999' },
  })
}

function show(route = '/holdings') {
  return renderApp(<HoldingsPage />, { route })
}

describe('HoldingsPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings({ refresh_seconds: 0 }))
    vi.mocked(endpoints.fetchHoldings).mockResolvedValue(HOLDINGS)
    vi.mocked(endpoints.fetchCycles).mockImplementation(async (id) => makeCycles(id, id === 2 ? [WAITING] : []))
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([]))
    const candles = makeCandles(20)
    vi.mocked(endpoints.fetchCandles).mockResolvedValue(candles)
    vi.mocked(endpoints.fetchIndicators).mockResolvedValue({ code: '900040', bar: '60m', points: makeIndicatorPoints(candles), flow: [] })
    vi.mocked(endpoints.fetchResults).mockResolvedValue(makeResults([]))
    vi.mocked(endpoints.fetchWatchlist).mockResolvedValue([])
  })

  describe('table', () => {
    it('lists each holding with its state tag', async () => {
      show()

      const rowA = await screen.findByRole('row', { name: /모의A/ })
      expect(within(rowA).getByText('보유')).toBeInTheDocument()
      expect(within(rowA).getByText('300주')).toBeInTheDocument()
      const rowB = screen.getByRole('row', { name: /모의B/ })
      expect(within(rowB).getByText('재매수 대기')).toBeInTheDocument()
      expect(within(rowB).getByText('288,018')).toBeInTheDocument() // the rebuy target
      expect(within(rowB).getByText('시작 300')).toBeInTheDocument()
      const rowC = screen.getByRole('row', { name: /모의C/ })
      expect(within(rowC).getByText('만료')).toBeInTheDocument()
      expect(within(rowC).getByText('일봉 하락 추세')).toBeInTheDocument()
    })

    it('colours the gain on the average price and the accumulated gain in shares by sign', async () => {
      show()

      const rowA = await screen.findByRole('row', { name: /모의A/ })
      expect(within(rowA).getByText('+11.11%')).toHaveStyle({ color: MARKET_COLORS.up })
      expect(within(screen.getByRole('row', { name: /모의B/ })).getByText('+5주')).toHaveStyle({ color: MARKET_COLORS.up })
    })

    it('says so when nothing is registered yet', async () => {
      vi.mocked(endpoints.fetchHoldings).mockResolvedValue([])

      show()

      expect(await screen.findByText(/등록한 보유 종목이 없습니다/)).toBeInTheDocument()
    })

    it('shows the first holding by default and the one in the link when there is one', async () => {
      const { unmount } = show()
      expect(await screen.findByText('모의A 차트')).toBeInTheDocument()
      unmount()

      show('/holdings?holding=2')
      expect(await screen.findByText('모의B 차트')).toBeInTheDocument()
    })

    it('switches the detail when another row is clicked', async () => {
      show()
      await screen.findByText('모의A 차트')

      await user().click(screen.getByRole('row', { name: /모의B/ }))

      expect(await screen.findByText('모의B 차트')).toBeInTheDocument()
    })
  })

  describe('chart', () => {
    it('draws the rebuy target and the ATR stop on the chart of a waiting holding', async () => {
      show('/holdings?holding=2')

      const chart = await screen.findByTestId('price-chart')
      expect(JSON.parse(chart.dataset.lines ?? '[]')).toEqual([
        expect.objectContaining({ price: 288018, title: '재매수 목표가' }),
        expect.objectContaining({ price: 86000, title: 'ATR 손절선' }),
      ])
    })

    it('puts the recorded sale on the bar it happened in', async () => {
      const candles = makeCandles(5)
      vi.mocked(endpoints.fetchCandles).mockResolvedValue(candles)
      vi.mocked(endpoints.fetchCycles).mockResolvedValue(makeCycles(2, [{ ...WAITING, sold_at: '2026-09-03T12:00:00+09:00' }]))

      show('/holdings?holding=2')

      const chart = await screen.findByTestId('price-chart')
      await waitFor(() => expect(JSON.parse(chart.dataset.markers ?? '[]')).toEqual([{ time: '2026-09-03', kind: 'sell', text: '매도' }]))
    })

    it('starts with the signal bar length of the settings and reloads on another choice', async () => {
      vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings({ refresh_seconds: 0, signal_bar_length: '60m' }))
      show()
      await waitFor(() => expect(endpoints.fetchCandles).toHaveBeenCalledWith('900040', '60m', 200))

      await user().click(screen.getByText('30분'))
      await waitFor(() => expect(endpoints.fetchCandles).toHaveBeenCalledWith('900040', '30m', 260))
      await user().click(screen.getByText('일봉'))
      await waitFor(() => expect(endpoints.fetchCandles).toHaveBeenCalledWith('900040', '1d', 250))
      expect(endpoints.fetchIndicators).toHaveBeenCalledWith('900040', '1d', 250)
    })
  })

  describe('cycles', () => {
    it('shows the cycle history and the gain in shares', async () => {
      vi.mocked(endpoints.fetchCycles).mockResolvedValue(
        makeCycles(1, [
          makeCycle(1, { state: 'rebuy_done', sell_price: 291546, sell_quantity: 100, rebuy_price: 275755, rebuy_quantity: 105, quantity_increase: 5, net_cash: -1200 }),
          makeCycle(2, { state: 'abandoned' }),
        ]),
      )

      show('/holdings?holding=1')

      const done = await screen.findByRole('row', { name: /재매수 완료/ })
      expect(within(done).getByText('+5주')).toHaveStyle({ color: MARKET_COLORS.up })
      expect(within(done).getByText('291,546 × 100주')).toBeInTheDocument()
      expect(within(done).getByText('275,755 × 105주')).toBeInTheDocument()
      expect(screen.getByRole('row', { name: /포기/ })).toBeInTheDocument()
      const card = screen.getByLabelText('수량 증가분 누적')
      expect(within(card).getByText('5')).toBeInTheDocument()
    })

    it('says what to do when there is no cycle yet', async () => {
      show('/holdings?holding=1')

      expect(await screen.findByText(/아직 사이클이 없습니다/)).toBeInTheDocument()
    })
  })

  describe('recording a fill', () => {
    it('opens, filled in, from the link of a sell alert', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
        makeAlerts([makeAlert(7, { kind: 'sell', holding_id: 1, code: '900040', suggested_quantity: 100, price: 291546 })]),
      )

      show('/holdings?holding=1&alert=7')

      const dialog = await screen.findByRole('dialog', { name: /매도 체결 기록 · 모의A/ })
      expect(within(dialog).getByLabelText('수량 (주)')).toHaveValue('100')
      expect(within(dialog).getByLabelText('체결가 (원)')).toHaveValue('291,546')
    })

    it('opens for a rebuy alert with the sold quantity for the preview', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
        makeAlerts([makeAlert(8, { kind: 'rebuy', holding_id: 2, code: '900010', suggested_quantity: 105, price: 275755 })]),
      )

      show('/holdings?holding=2&alert=8')

      const dialog = await screen.findByRole('dialog', { name: /재매수 체결 기록/ })
      expect(within(dialog).getByLabelText('수량 (주)')).toHaveValue('105')
      expect(within(dialog).getByText('+5주')).toBeInTheDocument()
    })

    it('leaves a stale link alone: a sell alert for a holding that already sold', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
        makeAlerts([makeAlert(7, { kind: 'sell', holding_id: 2, code: '900010' })]),
      )

      show('/holdings?holding=2&alert=7')

      await screen.findByText('모의B 차트')
      await waitFor(() => expect(endpoints.fetchAlerts).toHaveBeenCalled())
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('does not open the form for a warning that only wants to be read', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
        makeAlerts([makeAlert(8, { kind: 'rebuy_held', level: 'warning', holding_id: 2, code: '900010' })]),
      )

      show('/holdings?holding=2&alert=8')

      expect(await screen.findByText('일봉 수급 이탈로 보류됨')).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('opens by hand from the table with a third of the position and the last close', async () => {
      show()

      await user().click(await screen.findByRole('button', { name: '모의A 체결 기록' }))

      const dialog = await screen.findByRole('dialog', { name: /매도 체결 기록/ })
      expect(within(dialog).getByLabelText('수량 (주)')).toHaveValue('100')
      expect(within(dialog).getByLabelText('체결가 (원)')).toHaveValue('293,068')
    })

    it('offers the rebuy side by hand for a holding that is waiting', async () => {
      show()

      await user().click(await screen.findByRole('button', { name: '모의B 체결 기록' }))

      const dialog = await screen.findByRole('dialog', { name: /재매수 체결 기록/ })
      expect(within(dialog).getByLabelText('수량 (주)')).toHaveValue('100') // the sold quantity: break-even
    })

    it('updates the table at once after the fill is recorded', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
        makeAlerts([makeAlert(7, { kind: 'sell', holding_id: 1, code: '900040', suggested_quantity: 100, price: 291546 })]),
      )
      vi.mocked(endpoints.recordFill).mockImplementation(async () => {
        vi.mocked(endpoints.fetchHoldings).mockResolvedValue([
          { ...HOLDINGS[0], state: 'rebuy_wait', quantity: 200, open_cycle: WAITING },
          HOLDINGS[1],
          HOLDINGS[2],
        ])
        return { fill: { id: 1, side: 'sell', price: 291546, quantity: 100, filled_at: '', fee: 0, tax: 0, forced: false }, cycle: WAITING, holding: HOLDINGS[0] }
      })
      vi.mocked(endpoints.markAlertRead).mockResolvedValue()
      show('/holdings?holding=1&alert=7')
      const dialog = await screen.findByRole('dialog', { name: /매도 체결 기록/ })

      await user().click(within(dialog).getByRole('button', { name: '기록' }))

      const row = screen.getByRole('row', { name: /모의A/ })
      await waitFor(() => expect(within(row).getByText('재매수 대기')).toBeInTheDocument())
      expect(within(row).getByText('200주')).toBeInTheDocument()
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(endpoints.fetchCycles).toHaveBeenCalledTimes(2) // the history is read again too
    })
  })

  describe('expiry', () => {
    it('asks what to do about an expired wait, and retries on request', async () => {
      vi.mocked(endpoints.retryCycle).mockResolvedValue({ ...WAITING, id: 9 })

      show('/holdings?holding=3')

      expect(await screen.findByText('재매수 대기가 만료되었습니다')).toBeInTheDocument()
      await user().click(screen.getByRole('button', { name: '재매수 시도' }))
      await waitFor(() => expect(endpoints.retryCycle).toHaveBeenCalledWith(3, 9))
      expect(await screen.findByText(/재매수 대기를 다시 시작했습니다/)).toBeInTheDocument()
    })

    it('abandons the cycle only after a confirmation', async () => {
      vi.mocked(endpoints.abandonCycle).mockResolvedValue({ ...WAITING, id: 9, state: 'abandoned' })
      show('/holdings?holding=3')
      await screen.findByText('재매수 대기가 만료되었습니다')

      await user().click(screen.getByRole('button', { name: '사이클 포기' }))
      expect(endpoints.abandonCycle).not.toHaveBeenCalled()
      await user().click(await screen.findByRole('button', { name: '포기' }))

      await waitFor(() => expect(endpoints.abandonCycle).toHaveBeenCalledWith(3, 9))
    })

    it('has no such choice for a holding that is not expired', async () => {
      show('/holdings?holding=2')

      await screen.findByText('모의B 차트')
      expect(screen.queryByText('재매수 대기가 만료되었습니다')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '재매수 시도' })).not.toBeInTheDocument()
    })
  })

  describe('held-back rebuy', () => {
    it('warns that the rebuy was held back by the flow filter, as long as it is the latest word', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
        makeAlerts([
          makeAlert(8, { kind: 'rebuy_held', level: 'warning', holding_id: 2, code: '900010' }),
          makeAlert(7, { kind: 'sell', holding_id: 2, code: '900010' }),
        ]),
      )

      show('/holdings?holding=2')

      expect(await screen.findByText('일봉 수급 이탈로 보류됨')).toBeInTheDocument()
    })

    it('drops the warning once an actual rebuy alert follows it', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(
        makeAlerts([
          makeAlert(9, { kind: 'rebuy', holding_id: 2, code: '900010' }),
          makeAlert(8, { kind: 'rebuy_held', level: 'warning', holding_id: 2, code: '900010' }),
        ]),
      )

      show('/holdings?holding=2')

      await screen.findByText('모의B 차트')
      expect(screen.queryByText('일봉 수급 이탈로 보류됨')).not.toBeInTheDocument()
    })
  })

  describe('registering', () => {
    const open = async () => {
      await user().click(await screen.findByRole('button', { name: /보유 종목 등록/ }))
      return screen.findByRole('dialog', { name: '보유 종목 등록' })
    }

    it('registers a holding and shows it', async () => {
      vi.mocked(endpoints.createHolding).mockResolvedValue(makeHolding(4, { name: '새 종목', code: '005930', quantity: 10, start_quantity: 10 }))
      show()
      const dialog = await open()
      const u = user()

      await u.type(within(dialog).getByLabelText('종목 코드'), '005930')
      await u.type(within(dialog).getByLabelText('수량 (주)'), '10')
      await u.type(within(dialog).getByLabelText('평균단가 (원)'), '70000')
      await u.click(within(dialog).getByRole('button', { name: '등록' }))

      await waitFor(() => expect(endpoints.createHolding).toHaveBeenCalledWith({ code: '005930', quantity: 10, avg_price: 70000 }))
      expect(await screen.findByText(/시작 수량 10주/)).toBeInTheDocument()
    })

    it('checks the code before asking the server', async () => {
      show()
      const dialog = await open()

      await user().type(within(dialog).getByLabelText('종목 코드'), '12')
      await user().click(within(dialog).getByRole('button', { name: '등록' }))

      expect(await within(dialog).findByText('종목 코드는 6자리입니다')).toBeInTheDocument()
      expect(endpoints.createHolding).not.toHaveBeenCalled()
    })

    it('shows the server’s refusal', async () => {
      vi.mocked(endpoints.createHolding).mockRejectedValue(notFound())
      show()
      const dialog = await open()
      const u = user()

      await u.type(within(dialog).getByLabelText('종목 코드'), '999999')
      await u.type(within(dialog).getByLabelText('수량 (주)'), '10')
      await u.type(within(dialog).getByLabelText('평균단가 (원)'), '1000')
      await u.click(within(dialog).getByRole('button', { name: '등록' }))

      expect(await within(dialog).findByText('Unknown stock 999999')).toBeInTheDocument()
    })
  })
})
