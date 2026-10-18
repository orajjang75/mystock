import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../api/endpoints'
import { renderApp } from '../test/render'
import { RequireAuth } from './RequireAuth'

vi.mock('../api/endpoints')

const user = { username: 'admin' }

describe('RequireAuth', () => {
  beforeEach(() => vi.resetAllMocks())

  it('shows the screen to a signed-in user', async () => {
    vi.mocked(endpoints.fetchMe).mockResolvedValue(user)

    renderApp(
      <RequireAuth>
        <p>secret screen</p>
      </RequireAuth>,
    )

    expect(await screen.findByText('secret screen')).toBeInTheDocument()
  })

  it('sends a signed-out visitor to the login screen', async () => {
    vi.mocked(endpoints.fetchMe).mockResolvedValue(null)

    renderApp(
      <RequireAuth>
        <p>secret screen</p>
      </RequireAuth>,
      { route: '/settings', extraRoutes: [{ path: '/login', element: <p>login screen</p> }] },
    )

    expect(await screen.findByText('login screen')).toBeInTheDocument()
    expect(screen.queryByText('secret screen')).not.toBeInTheDocument()
  })

  it('does not flash the screen while it is still checking', async () => {
    vi.mocked(endpoints.fetchMe).mockReturnValue(new Promise(() => {}))

    renderApp(
      <RequireAuth>
        <p>secret screen</p>
      </RequireAuth>,
    )

    await waitFor(() => expect(document.querySelector('.ant-spin')).toBeInTheDocument())
    expect(screen.queryByText('secret screen')).not.toBeInTheDocument()
  })

  it('treats a failed check as signed out', async () => {
    vi.mocked(endpoints.fetchMe).mockRejectedValue(new Error('network'))

    renderApp(
      <RequireAuth>
        <p>secret screen</p>
      </RequireAuth>,
      { extraRoutes: [{ path: '/login', element: <p>login screen</p> }] },
    )

    expect(await screen.findByText('login screen')).toBeInTheDocument()
  })
})
