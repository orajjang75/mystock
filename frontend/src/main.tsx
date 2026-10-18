import '@ant-design/v5-patch-for-react-19'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider } from 'antd'
import koKR from 'antd/locale/ko_KR'
import dayjs from 'dayjs'
import 'dayjs/locale/ko'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { queryKeys } from './api/queries'
import { setUnauthorizedHandler } from './api/client'
import './index.css'
import { router } from './router'
import { antdTheme } from './theme/antdTheme'
import { applyCssVariables } from './theme/colors'

dayjs.locale('ko')
applyCssVariables()

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: true, retry: 1 } },
})
// A 401 on any request means the session ended: the auth guard then sends the user to /login.
setUnauthorizedHandler(() => queryClient.setQueryData(queryKeys.me, null))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider theme={antdTheme} locale={koKR}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>
  </StrictMode>,
)
