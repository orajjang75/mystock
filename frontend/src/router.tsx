import { createBrowserRouter, Navigate, type RouteObject } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { SettingsPage } from './pages/settings/SettingsPage'

export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      // the chart libraries only load with the screens that draw charts
      { index: true, lazy: async () => ({ Component: (await import('./pages/DashboardPage')).DashboardPage }) },
      {
        path: 'screener',
        lazy: async () => ({ Component: (await import('./pages/screener/ScreenerPage')).ScreenerPage }),
      },
      {
        path: 'holdings',
        lazy: async () => ({ Component: (await import('./pages/holdings/HoldingsPage')).HoldingsPage }),
      },
      {
        path: 'alerts',
        lazy: async () => ({ Component: (await import('./pages/alerts/AlertsPage')).AlertsPage }),
      },
      {
        path: 'backtest',
        lazy: async () => ({ Component: (await import('./pages/backtest/BacktestPage')).BacktestPage }),
      },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
