import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../../api/endpoints'
import { makeAlert, makeAlerts, makeCycle, makeHolding, makeSettings } from '../../test/fixtures'
import { renderApp } from '../../test/render'
import { AlertsPage } from './AlertsPage'

vi.mock('../../api/endpoints')

const user = () => userEvent.setup({ delay: null, pointerEventsCheck: 0 })

function Where() {
  const location = useLocation()
  return <p>at {location.pathname + location.search}</p>
}

function show() {
  return renderApp(
    <Routes>
      <Route path="/" element={<AlertsPage />} />
      <Route path="*" element={<Where />} />
    </Routes>,
  )
}

const SELL = makeAlert(1, {
  kind: 'sell',
  holding_id: 1,
  suggested_quantity: 100,
  price: 291546,
  rebuy_target_price: 288018,
  evidence: { signals: ['rsi_overbought_exit', 'macd_weakening'], overlap: 2, rsi: 68.2, bar_length: '60m' },
})
const HELD = makeAlert(2, {
  kind: 'rebuy_held',
  label: '재매수 보류 경고 (일봉 수급 이탈)',
  level: 'warning',
  holding_id: 1,
  evidence: { signals: ['price_condition', 'rsi_rebound'], held_by_flow_filter: true },
})
const REBUY = makeAlert(3, { kind: 'rebuy', label: '재매수 신호', holding_id: 1, suggested_quantity: 105, is_read: true })
const EXPIRED = makeAlert(4, { kind: 'expired', label: '재매수 대기 만료', holding_id: 2, suggested_quantity: null, price: null, evidence: { cycle_id: 9, choices: ['retry', 'abandon'] } })

describe('AlertsPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings({ refresh_seconds: 0 }))
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([EXPIRED, REBUY, HELD, SELL]))
    vi.mocked(endpoints.fetchHoldings).mockResolvedValue([
      makeHolding(1, { name: '모의A', code: '900040', state: 'holding' }),
      makeHolding(2, { name: '모의B', code: '900010', state: 'expired', open_cycle: makeCycle(9, { state: 'expired' }) }),
    ])
    vi.mocked(endpoints.markAlertRead).mockResolvedValue()
  })

  const rowOf = (text: RegExp | string) => screen.getByRole('row', { name: text })

  it('lists the alerts with quantity, price and rebuy target', async () => {
    show()

    const sell = await screen.findByRole('row', { name: /매도 신호/ })
    expect(within(sell).getByText('100주')).toBeInTheDocument()
    expect(within(sell).getByText('291,546')).toBeInTheDocument()
    expect(within(sell).getByText('288,018')).toBeInTheDocument()
    expect(screen.getByText(/읽지 않음 3건 · 표시 4건/)).toBeInTheDocument()
  })

  it('shows the alert held back by the flow filter apart from the ordinary ones', async () => {
    show()

    const held = await screen.findByRole('row', { name: /일봉 수급 이탈로 보류됨/ })
    expect(held).toHaveClass('alert-row-warning')
    expect(within(held).getByText('경고')).toBeInTheDocument()
    expect(within(held).getByText('재매수 조건은 충족')).toBeInTheDocument()
    expect(within(held).queryByRole('button', { name: '체결 기록' })).not.toBeInTheDocument()
    for (const ordinary of [rowOf(/매도 신호/), rowOf(/재매수 신호/)]) {
      expect(ordinary).not.toHaveClass('alert-row-warning')
      expect(within(ordinary).queryByText('경고')).not.toBeInTheDocument()
    }
  })

  it('shows other warnings as warnings too', async () => {
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([makeAlert(5, { kind: 'stop_loss', label: '손절선 이탈 경고', level: 'warning' })]))

    show()

    const row = await screen.findByRole('row', { name: /손절선 이탈 경고/ })
    expect(row).toHaveClass('alert-row-warning')
    expect(within(row).getByText('경고')).toBeInTheDocument()
  })

  it('unfolds the evidence behind an alert', async () => {
    show()
    const sell = await screen.findByRole('row', { name: /매도 신호/ })

    await user().click(sell.querySelector('.ant-table-row-expand-icon') as HTMLElement)

    expect(await screen.findByText('RSI 과매수 이탈')).toBeInTheDocument()
    expect(screen.getByText('MACD 약화')).toBeInTheDocument()
    expect(screen.getByText('겹친 매도 신호 수')).toBeInTheDocument()
    expect(screen.getByText('68.20')).toBeInTheDocument()
    expect(screen.getByText('60분봉')).toBeInTheDocument()
  })

  it('explains in the evidence why the rebuy was held back', async () => {
    show()
    const held = await screen.findByRole('row', { name: /일봉 수급 이탈로 보류됨/ })

    await user().click(held.querySelector('.ant-table-row-expand-icon') as HTMLElement)

    expect(await screen.findByText(/알림을 보류했습니다/)).toBeInTheDocument()
    expect(screen.getByText('수급 이탈로 보류')).toBeInTheDocument()
  })

  it('marks an alert as read, and only offers that for unread ones', async () => {
    show()
    const sell = await screen.findByRole('row', { name: /매도 신호/ })

    await user().click(within(sell).getByRole('button', { name: /읽음 처리/ }))

    await waitFor(() => expect(vi.mocked(endpoints.markAlertRead).mock.calls[0][0]).toBe(1))
    expect(within(rowOf(/재매수 신호/)).queryByRole('button', { name: /읽음 처리/ })).not.toBeInTheDocument()
  })

  describe('filters', () => {
    it('asks the server for the chosen kind, offering the kinds the server lists', async () => {
      show()
      await screen.findByRole('row', { name: /매도 신호/ })

      await user().click(screen.getByRole('combobox', { name: '신호 종류' }))
      await user().click(await screen.findByText('재매수 신호', { selector: '.ant-select-item-option-content' }))

      await waitFor(() => expect(endpoints.fetchAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'rebuy' })))
    })

    it('marks warning kinds in the filter list', async () => {
      show()
      await screen.findByRole('row', { name: /매도 신호/ })

      await user().click(screen.getByRole('combobox', { name: '신호 종류' }))

      expect(await screen.findByText('⚠ 재매수 보류 경고 (일봉 수급 이탈)', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
    })

    it('asks for one stock', async () => {
      show()
      await screen.findByRole('row', { name: /매도 신호/ })

      await user().click(screen.getByRole('combobox', { name: '종목' }))
      await user().click(await screen.findByText('모의B (900010)', { selector: '.ant-select-item-option-content' }))

      await waitFor(() => expect(endpoints.fetchAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ code: '900010' })))
    })

    it('asks for the unread ones only', async () => {
      show()
      await screen.findByRole('row', { name: /매도 신호/ })

      await user().click(screen.getByRole('checkbox', { name: '읽지 않은 알림만' }))

      await waitFor(() => expect(endpoints.fetchAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ unread_only: true })))
    })

    it('says so when nothing matches', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([]))

      show()

      expect(await screen.findByText('조건에 맞는 알림이 없습니다')).toBeInTheDocument()
    })
  })

  describe('next steps', () => {
    it('opens the fill form of the holding from a sell or rebuy alert', async () => {
      show()

      await user().click(within(await screen.findByRole('row', { name: /매도 신호/ })).getByRole('button', { name: '체결 기록' }))

      expect(await screen.findByText('at /holdings?holding=1&alert=1')).toBeInTheDocument()
    })

    it('offers the expiry choice while that cycle is still the expired one', async () => {
      show()

      const row = await screen.findByRole('row', { name: /재매수 대기 만료/ })

      expect(within(row).getByRole('button', { name: '재매수 시도' })).toBeInTheDocument()
      expect(within(row).getByRole('button', { name: '사이클 포기' })).toBeInTheDocument()
    })

    it('retries from the alert row', async () => {
      vi.mocked(endpoints.retryCycle).mockResolvedValue(makeCycle(9))
      show()

      await user().click(within(await screen.findByRole('row', { name: /재매수 대기 만료/ })).getByRole('button', { name: '재매수 시도' }))

      await waitFor(() => expect(endpoints.retryCycle).toHaveBeenCalledWith(2, 9))
    })

    it('has no choice left once the cycle was handled', async () => {
      vi.mocked(endpoints.fetchHoldings).mockResolvedValue([makeHolding(2, { name: '모의B', state: 'holding', open_cycle: null })])

      show()

      const row = await screen.findByRole('row', { name: /재매수 대기 만료/ })
      expect(within(row).queryByRole('button', { name: '재매수 시도' })).not.toBeInTheDocument()
      expect(within(row).getByRole('button', { name: '보유 종목 보기' })).toBeInTheDocument()
    })

    it('links a warning to its holding', async () => {
      vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([makeAlert(5, { kind: 'stop_loss', label: '손절선 이탈 경고', level: 'warning', holding_id: 1 })]))
      show()

      await user().click(await screen.findByRole('button', { name: '보유 종목 보기' }))

      expect(await screen.findByText('at /holdings?holding=1')).toBeInTheDocument()
    })
  })
})
