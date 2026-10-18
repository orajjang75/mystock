import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { antdTheme } from '../theme/antdTheme'

export function newClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

interface Options {
  route?: string
  client?: QueryClient
  /** Extra routes rendered next to the element under test (to see where a redirect lands). */
  extraRoutes?: { path: string; element: ReactElement }[]
}

/** Renders ``ui`` with the app's providers and a memory router. */
export function renderApp(ui: ReactElement, { route = '/', client = newClient(), extraRoutes = [] }: Options = {}) {
  const view = render(
    <ConfigProvider theme={{ ...antdTheme, hashed: false }}>
      <AntdApp>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={[route]}>
            <Routes>
              {extraRoutes.map((r) => (
                <Route key={r.path} path={r.path} element={r.element} />
              ))}
              <Route path="*" element={ui} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  return { ...view, client }
}
