import { AxiosError, AxiosHeaders } from 'axios'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../api/endpoints'
import { DISCLAIMER_TEXT } from '../components/Disclaimer'
import { renderApp } from '../test/render'
import { LoginPage } from './LoginPage'

vi.mock('../api/endpoints')

function unauthorized(): AxiosError {
  const config = { headers: new AxiosHeaders(), url: '/api/auth/login' }
  return new AxiosError('401', 'ERR_BAD_REQUEST', config, null, {
    status: 401,
    statusText: 'Unauthorized',
    headers: {},
    config,
    data: { detail: 'Invalid username or password' },
  })
}

async function signIn(username: string, password: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('아이디'), username)
  await user.type(screen.getByLabelText('비밀번호'), password)
  await user.click(screen.getByRole('button', { name: /로그인/ }))
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchMe).mockResolvedValue(null)
  })

  it('shows the always-on disclaimer', async () => {
    renderApp(<LoginPage />, { route: '/login' })

    expect(await screen.findByText(DISCLAIMER_TEXT)).toBeInTheDocument()
  })

  it('asks for both fields before it calls the API', async () => {
    renderApp(<LoginPage />, { route: '/login' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /로그인/ }))

    expect(await screen.findByText('아이디를 입력하세요')).toBeInTheDocument()
    expect(screen.getByText('비밀번호를 입력하세요')).toBeInTheDocument()
    expect(endpoints.login).not.toHaveBeenCalled()
  })

  it('signs in and goes to the screen the user came from', async () => {
    vi.mocked(endpoints.login).mockResolvedValue({ username: 'admin' })

    renderApp(<LoginPage />, {
      route: '/login',
      extraRoutes: [{ path: '/', element: <p>home screen</p> }],
    })
    await signIn('admin', 'secret')

    await waitFor(() => expect(endpoints.login).toHaveBeenCalledWith('admin', 'secret'))
    expect(await screen.findByText('home screen')).toBeInTheDocument()
  })

  it('says so when the password is wrong and stays on the page', async () => {
    vi.mocked(endpoints.login).mockRejectedValue(unauthorized())

    renderApp(<LoginPage />, { route: '/login' })
    await signIn('admin', 'wrong')

    expect(await screen.findByText('아이디 또는 비밀번호가 올바르지 않습니다')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /로그인/ })).toBeInTheDocument()
  })

  it('leaves the login page when the user is already signed in', async () => {
    vi.mocked(endpoints.fetchMe).mockResolvedValue({ username: 'admin' })

    renderApp(<LoginPage />, { route: '/login', extraRoutes: [{ path: '/', element: <p>home screen</p> }] })

    expect(await screen.findByText('home screen')).toBeInTheDocument()
  })
})
