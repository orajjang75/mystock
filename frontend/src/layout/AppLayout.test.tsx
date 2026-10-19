import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../api/endpoints'
import { DISCLAIMER_TEXT } from '../components/Disclaimer'
import { makeAlert, makeAlerts, makeHealth, makeSettings } from '../test/fixtures'
import { renderApp } from '../test/render'
import { AppLayout } from './AppLayout'
import { Route, Routes } from 'react-router-dom'

vi.mock('../api/endpoints')

function renderLayout(route = '/') {
  return renderApp(
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<p>대시보드 화면</p>} />
        <Route path="screener" element={<p>스크리너 화면</p>} />
        <Route path="settings" element={<p>설정 화면</p>} />
        <Route path="alerts" element={<p>알림 화면</p>} />
      </Route>
    </Routes>,
    { route },
  )
}

/** The tabs that carry a screen name (antd adds a separate 'remove' tab-button to each). */
function screenTabs(): HTMLElement[] {
  return screen.getAllByRole('tab').filter((tab) => tab.textContent?.trim())
}

function removeButtons(): HTMLElement[] {
  return screen.queryAllByRole('tab', { name: /remove/i })
}

describe('AppLayout', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings())
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(makeHealth())
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([]))
  })

  it('has the six main menus on the icon rail', async () => {
    renderLayout()

    const rail = await screen.findByRole('navigation', { name: '주 메뉴' })

    for (const name of ['대시보드', '스크리너', '보유 종목', '알림', '백테스트', '설정']) {
      expect(within(rail).getByRole('link', { name })).toBeInTheDocument()
    }
  })

  it('shows the disclaimer at the bottom of every screen', async () => {
    renderLayout()
    expect(await screen.findByText(DISCLAIMER_TEXT)).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('link', { name: '설정' }))

    expect(await screen.findByText('설정 화면')).toBeInTheDocument()
    expect(screen.getByText(DISCLAIMER_TEXT)).toBeInTheDocument()
  })

  it('opens a tab for each screen visited and switches between them', async () => {
    const user = userEvent.setup()
    renderLayout()
    await screen.findByText('대시보드 화면')

    await user.click(screen.getByRole('link', { name: '스크리너' }))
    await user.click(screen.getByRole('link', { name: '설정' }))

    await screen.findByText('설정 화면')
    expect(screenTabs().map((t) => t.textContent?.trim())).toEqual(['대시보드', '스크리너', '설정'])
    expect(screenTabs().filter((t) => t.getAttribute('aria-selected') === 'true')[0]).toHaveTextContent('설정')

    await user.click(screen.getByRole('tab', { name: /스크리너/ }))
    expect(await screen.findByText('스크리너 화면')).toBeInTheDocument()
  })

  it('closes a tab and moves to its neighbour, but keeps the last one', async () => {
    const user = userEvent.setup()
    renderLayout()
    await user.click(await screen.findByRole('link', { name: '스크리너' }))
    await screen.findByText('스크리너 화면')
    expect(screenTabs()).toHaveLength(2)

    await user.click(removeButtons()[1]) // close the screener tab, the active one

    expect(await screen.findByText('대시보드 화면')).toBeInTheDocument()
    expect(screenTabs()).toHaveLength(1)
    expect(removeButtons()).toHaveLength(0) // the last tab cannot be closed
  })

  it('shows the unread alert count on the bell', async () => {
    vi.mocked(endpoints.fetchAlerts).mockResolvedValue(makeAlerts([makeAlert(1), makeAlert(2), makeAlert(3)]))

    renderLayout()

    const bell = await screen.findByRole('button', { name: '알림' })
    await waitFor(() => expect(bell.closest('.ant-badge')).toHaveTextContent('3'))
  })

  it('shows the market data status next to the time of the last refresh', async () => {
    renderLayout()

    expect(await screen.findByText(/정상 · \d\d:\d\d:\d\d/)).toBeInTheDocument()
  })

  it('shows a stale-data warning banner and a degraded status', async () => {
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(
      makeHealth({
        status: 'degraded',
        warnings: [{ source: 'intraday', message: '분봉 시세 수집이 10:00 이후 갱신되지 않았습니다' }],
      }),
    )

    renderLayout()

    expect(await screen.findByText(/시세 갱신 지연 · 분봉 시세 수집이 10:00 이후/)).toBeInTheDocument()
    expect(screen.getByText(/지연 · \d\d:\d\d:\d\d/)).toBeInTheDocument()
  })

  it('says so in a banner when the server runs in paper-run mode', async () => {
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(makeHealth({ mode: 'paper' }))

    renderLayout()

    expect(await screen.findByText(/모의 운영 중 · 신호와 알림만 받습니다/)).toBeInTheDocument()
  })

  it('shows no paper-run banner in normal mode', async () => {
    renderLayout()
    await screen.findByText(/정상/)

    expect(screen.queryByText(/모의 운영 중/)).not.toBeInTheDocument()
  })

  it('says so when the server cannot be reached', async () => {
    vi.mocked(endpoints.fetchHealth).mockRejectedValue(new Error('network'))

    renderLayout()

    expect(await screen.findByText(/서버에 연결할 수 없습니다/)).toBeInTheDocument()
    expect(screen.getByText(/연결 끊김/)).toBeInTheDocument()
  })

  it('refreshes everything on demand', async () => {
    const user = userEvent.setup()
    renderLayout()
    await screen.findByText(/정상/)
    const before = vi.mocked(endpoints.fetchHealth).mock.calls.length

    await user.click(screen.getByRole('button', { name: '새로고침' }))

    await waitFor(() => expect(vi.mocked(endpoints.fetchHealth).mock.calls.length).toBeGreaterThan(before))
  })

  it('logs out and goes to the login screen', async () => {
    vi.mocked(endpoints.logout).mockResolvedValue()
    const user = userEvent.setup()
    renderApp(
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<p>대시보드 화면</p>} />
        </Route>
        <Route path="/login" element={<p>login screen</p>} />
      </Routes>,
    )

    await user.click(await screen.findByRole('button', { name: '로그아웃' }))

    expect(await screen.findByText('login screen')).toBeInTheDocument()
    expect(endpoints.logout).toHaveBeenCalled()
  })
})
