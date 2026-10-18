import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../api/endpoints'
import { makeAlert, makeAlerts, makeSettings } from '../test/fixtures'
import { newClient, renderApp } from '../test/render'
import { AlertFeed } from './AlertFeed'
import { useLocation } from 'react-router-dom'

function Where() {
  const location = useLocation()
  return <p>at {location.pathname + location.search}</p>
}

vi.mock('../api/endpoints')

function polled(items: ReturnType<typeof makeAlert>[]) {
  vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts(items))
}

/** Run one more poll, as the interval would. */
async function poll(client: ReturnType<typeof newClient>) {
  await client.invalidateQueries({ queryKey: ['alerts'] })
}

/** Wait until the feed has processed a poll that ends at alert ``id``. */
async function seen(id: number) {
  await waitFor(() => expect(localStorage.getItem('mystock.lastSeenAlertId')).toBe(String(id)))
}

describe('AlertFeed', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings({ refresh_seconds: 0 }))
  })

  it('stays quiet about alerts that were already there on the first visit', async () => {
    polled([makeAlert(1), makeAlert(2)])

    renderApp(<AlertFeed />)

    await seen(2)
    expect(screen.queryByText(/새 알림/)).not.toBeInTheDocument()
    expect(document.querySelector('.ant-notification-notice')).not.toBeInTheDocument()
  })

  it('raises a notification and a banner when a new alert arrives', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />)
    await seen(1)

    polled([makeAlert(2, { suggested_quantity: 33 }), makeAlert(1)])
    await poll(client)

    expect(await screen.findByText(/새 알림 1건/)).toBeInTheDocument()
    expect(screen.getAllByText(/매도 신호 모의KOSPI001 · 제안 33주/).length).toBeGreaterThanOrEqual(2) // banner + notification
    expect(document.querySelector('.ant-notification-notice')).toBeInTheDocument()
    expect(localStorage.getItem('mystock.lastSeenAlertId')).toBe('2')
  })

  it('collects several new alerts in one banner and does not repeat old ones', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />)
    await seen(1)

    polled([makeAlert(2), makeAlert(1)])
    await poll(client)
    await screen.findByText(/새 알림 1건/)
    polled([makeAlert(3, { name: '모의KOSPI002' }), makeAlert(2), makeAlert(1)])
    await poll(client)

    expect(await screen.findByText(/새 알림 2건 · 매도 신호 모의KOSPI002 · 제안 33주 외 1건/)).toBeInTheDocument()
  })

  it('turns the banner into a warning when one of the new alerts is a warning', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />)
    await seen(1)

    polled([makeAlert(2, { level: 'warning', label: '손절선 이탈 경고' }), makeAlert(1)])
    await poll(client)

    await screen.findByText(/새 알림 1건/)
    expect(document.querySelector('.ant-alert-warning')).toBeInTheDocument()
  })

  it('clears the banner when it is dismissed', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />)
    await seen(1)
    polled([makeAlert(2), makeAlert(1)])
    await poll(client)
    await screen.findByText(/새 알림 1건/)

    await userEvent.setup().click(screen.getByRole('button', { name: /close/i }))

    await waitFor(() => expect(screen.queryByText(/새 알림 1건/)).not.toBeInTheDocument())
  })

  it('goes to the alerts screen from the banner', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />, {
      extraRoutes: [{ path: '/alerts', element: <p>알림 화면</p> }],
    })
    await seen(1)
    polled([makeAlert(2), makeAlert(1)])
    await poll(client)

    await userEvent.setup().click(await screen.findByRole('button', { name: '알림 보기' }))

    expect(await screen.findByText('알림 화면')).toBeInTheDocument()
  })

  it('opens the holding with the fill form when a sell notification is clicked', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />, {
      extraRoutes: [{ path: '/holdings', element: <Where /> }],
    })
    await seen(1)
    polled([makeAlert(2, { kind: 'sell', holding_id: 3 }), makeAlert(1)])
    await poll(client)

    expect(await screen.findByText('클릭하면 보유 종목에서 체결을 기록합니다')).toBeInTheDocument()
    await userEvent.setup().click(document.querySelector('.ant-notification-notice') as HTMLElement)

    expect(await screen.findByText('at /holdings?holding=3&alert=2')).toBeInTheDocument()
  })

  it('opens just the holding for a warning, and says so', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />, { extraRoutes: [{ path: '/holdings', element: <Where /> }] })
    await seen(1)
    polled([makeAlert(2, { kind: 'rebuy_held', level: 'warning', holding_id: 3 }), makeAlert(1)])
    await poll(client)

    expect(await screen.findByText('클릭하면 보유 종목 화면으로 이동합니다')).toBeInTheDocument()
    await userEvent.setup().click(document.querySelector('.ant-notification-notice') as HTMLElement)

    expect(await screen.findByText('at /holdings?holding=3')).toBeInTheDocument()
  })

  it('goes to the alerts screen for an alert that is not about a holding', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />, { extraRoutes: [{ path: '/alerts', element: <Where /> }] })
    await seen(1)
    polled([makeAlert(2, { kind: 'data_stale', level: 'warning', holding_id: null, code: null }), makeAlert(1)])
    await poll(client)

    await userEvent.setup().click(await screen.findByRole('button', { name: '알림 보기' }))

    expect(await screen.findByText('at /alerts')).toBeInTheDocument()
  })

  it('puts a 체결 기록 button in the banner of a sell alert', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />, { extraRoutes: [{ path: '/holdings', element: <Where /> }] })
    await seen(1)
    polled([makeAlert(2, { kind: 'rebuy', holding_id: 3 }), makeAlert(1)])
    await poll(client)

    await userEvent.setup().click(await screen.findByRole('button', { name: '체결 기록' }))

    expect(await screen.findByText('at /holdings?holding=3&alert=2')).toBeInTheDocument()
    expect(screen.queryByText(/새 알림/)).not.toBeInTheDocument() // the banner is cleared
  })

  it('has no 체결 기록 button for a warning', async () => {
    polled([makeAlert(1)])
    const { client } = renderApp(<AlertFeed />)
    await seen(1)
    polled([makeAlert(2, { kind: 'stop_loss', level: 'warning', holding_id: 3 }), makeAlert(1)])
    await poll(client)

    await screen.findByText(/새 알림 1건/)
    expect(screen.queryByRole('button', { name: '체결 기록' })).not.toBeInTheDocument()
  })

  it('remembers what was seen across reloads and announces only what came since', async () => {
    localStorage.setItem('mystock.lastSeenAlertId', '2')
    polled([makeAlert(3), makeAlert(2), makeAlert(1)])

    renderApp(<AlertFeed />)

    expect(await screen.findByText(/새 알림 1건/)).toBeInTheDocument()
  })
})
