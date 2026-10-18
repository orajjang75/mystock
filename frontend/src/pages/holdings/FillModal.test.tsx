import { AxiosError, AxiosHeaders } from 'axios'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../../api/endpoints'
import type { FillResponse } from '../../api/types'
import { makeAlert, makeCycle, makeHolding } from '../../test/fixtures'
import { renderApp } from '../../test/render'
import { FillModal } from './FillModal'

vi.mock('../../api/endpoints')

const user = () => userEvent.setup({ delay: null, pointerEventsCheck: 0 })
const holding = makeHolding(1, { name: '모의A', state: 'holding', quantity: 300 })

function refused(detail: string): AxiosError {
  const config = { headers: new AxiosHeaders(), url: '/api/holdings/1/fills' }
  return new AxiosError('409', 'ERR_BAD_REQUEST', config, null, {
    status: 409,
    statusText: '',
    headers: {},
    config,
    data: { detail },
  })
}

function response(overrides: Partial<FillResponse['cycle']> = {}): FillResponse {
  return {
    fill: { id: 1, side: 'sell', price: 291546, quantity: 100, filled_at: '2026-10-16T11:00:10+09:00', fee: 1, tax: 2, forced: false },
    cycle: makeCycle(1, overrides),
    holding: makeHolding(1),
  }
}

function open(props: Partial<React.ComponentProps<typeof FillModal>> = {}) {
  const onClose = vi.fn()
  renderApp(
    <FillModal
      holding={holding}
      draft={{ side: 'sell', price: 291546, quantity: 100, forced: false }}
      alert={makeAlert(7, { kind: 'sell', suggested_quantity: 100, price: 291546 })}
      soldQuantity={null}
      onClose={onClose}
      {...props}
    />,
  )
  return { onClose }
}

describe('FillModal', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.recordFill).mockResolvedValue(response())
    vi.mocked(endpoints.markAlertRead).mockResolvedValue()
  })

  it('opens with the alert’s quantity and price filled in, so that confirming is enough', async () => {
    const { onClose } = open()

    expect(screen.getByRole('dialog', { name: /매도 체결 기록 · 모의A/ })).toBeInTheDocument()
    expect(screen.getByLabelText('체결가 (원)')).toHaveValue('291,546')
    expect(screen.getByLabelText('수량 (주)')).toHaveValue('100')

    await user().click(screen.getByRole('button', { name: '기록' }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(endpoints.recordFill).toHaveBeenCalledWith(1, { side: 'sell', price: 291546, quantity: 100, forced: false })
  })

  it('marks the alert as read once the fill is recorded, and tells what the sale set up', async () => {
    open()

    await user().click(screen.getByRole('button', { name: '기록' }))

    await waitFor(() => expect(endpoints.markAlertRead).toHaveBeenCalled())
    expect(vi.mocked(endpoints.markAlertRead).mock.calls[0][0]).toBe(7)
    expect(await screen.findByText(/재매수 목표가는 99,300원/)).toBeInTheDocument()
  })

  it('does not touch an alert that was already read', async () => {
    open({ alert: makeAlert(7, { kind: 'sell', is_read: true }) })

    await user().click(screen.getByRole('button', { name: '기록' }))

    await waitFor(() => expect(endpoints.recordFill).toHaveBeenCalled())
    expect(endpoints.markAlertRead).not.toHaveBeenCalled()
  })

  it('sends what the user changed', async () => {
    open()
    const u = user()

    await u.clear(screen.getByLabelText('수량 (주)'))
    await u.type(screen.getByLabelText('수량 (주)'), '40')
    await u.clear(screen.getByLabelText('체결가 (원)'))
    await u.type(screen.getByLabelText('체결가 (원)'), '290000')
    await u.click(screen.getByRole('button', { name: '기록' }))

    await waitFor(() => expect(endpoints.recordFill).toHaveBeenCalledWith(1, { side: 'sell', price: 290000, quantity: 40, forced: false }))
  })

  it('keeps the form open and shows the reason when the server refuses', async () => {
    vi.mocked(endpoints.recordFill).mockRejectedValue(refused('One sale per cycle: the holding is waiting to rebuy'))
    const { onClose } = open()

    await user().click(screen.getByRole('button', { name: '기록' }))

    expect(await screen.findByText('One sale per cycle: the holding is waiting to rebuy')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    expect(endpoints.markAlertRead).not.toHaveBeenCalled()
  })

  it('refuses to record without a price or a quantity', async () => {
    open({ draft: { side: 'sell', price: null, quantity: null, forced: false }, alert: undefined })

    await user().click(screen.getByRole('button', { name: '기록' }))

    expect(await screen.findByText('체결가를 입력하세요')).toBeInTheDocument()
    expect(screen.getByText('수량을 입력하세요')).toBeInTheDocument()
    expect(endpoints.recordFill).not.toHaveBeenCalled()
  })

  it('previews the gain in shares of a rebuy as the quantity is typed', async () => {
    open({
      holding: makeHolding(1, { name: '모의A', state: 'rebuy_wait' }),
      draft: { side: 'rebuy', price: 275755, quantity: 105, forced: false },
      alert: makeAlert(8, { kind: 'rebuy', suggested_quantity: 105, price: 275755 }),
      soldQuantity: 100,
    })

    expect(screen.getByRole('dialog', { name: /재매수 체결 기록/ })).toBeInTheDocument()
    expect(screen.getByText('+5주')).toBeInTheDocument()
    const input = screen.getByLabelText('수량 (주)')
    await user().clear(input)
    await user().type(input, '98')
    expect(screen.getByText('-2주')).toBeInTheDocument()
  })

  it('reports the quantity gain after a rebuy', async () => {
    vi.mocked(endpoints.recordFill).mockResolvedValue(response({ state: 'rebuy_done', quantity_increase: 5, rebuy_quantity: 105, rebuy_price: 275755 }))
    open({
      holding: makeHolding(1, { name: '모의A', state: 'rebuy_wait' }),
      draft: { side: 'rebuy', price: 275755, quantity: 105, forced: false },
      alert: undefined,
      soldQuantity: 100,
    })

    await user().click(screen.getByRole('button', { name: '기록' }))

    expect(await screen.findByText(/수량 증가분은 \+5주입니다/)).toBeInTheDocument()
  })

  it('records a forced sale when the alert asked for one', async () => {
    open({
      draft: { side: 'sell', price: 40000, quantity: 300, forced: true },
      alert: makeAlert(9, { kind: 'force_sell', suggested_quantity: 300, price: 40000 }),
    })

    expect(screen.getByRole('checkbox', { name: /강제 매도/ })).toBeChecked()
    await user().click(screen.getByRole('button', { name: '기록' }))

    await waitFor(() => expect(endpoints.recordFill).toHaveBeenCalledWith(1, { side: 'sell', price: 40000, quantity: 300, forced: true }))
  })

  it('can be cancelled without recording anything', async () => {
    const { onClose } = open()

    await user().click(screen.getByRole('button', { name: '취소' }))

    expect(onClose).toHaveBeenCalled()
    expect(endpoints.recordFill).not.toHaveBeenCalled()
  })
})
