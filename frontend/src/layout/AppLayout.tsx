import { LogoutOutlined } from '@ant-design/icons'
import { Badge, Button, Tabs, Tooltip } from 'antd'
import { useEffect } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAlerts, useLogout } from '../api/queries'
import { Disclaimer } from '../components/Disclaimer'
import { AlertFeed } from './AlertFeed'
import { HealthBanner } from './HealthBanner'
import { HeaderStatus } from './HeaderStatus'
import { MENU, entryFor } from './menu'
import { useOpenTabs } from './tabs'

/**
 * The "mix" layout of wewatch 2.0: an icon rail on the left chooses the main menu, tabs on top
 * switch between the screens that are open, and the status area sits at the top right.
 */
export function AppLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const logout = useLogout()
  const unread = useAlerts({ unread_only: true, limit: 20 })
  const { tabs, open, close } = useOpenTabs()

  const active = entryFor(location.pathname) ? location.pathname : '/'
  useEffect(() => open(active), [active, open])

  return (
    <div className="app-shell">
      <nav className="rail" aria-label="주 메뉴">
        <div className="rail-logo" aria-hidden>
          M
        </div>
        {MENU.map((entry) => (
          <NavLink
            key={entry.path}
            to={entry.path}
            end
            className={({ isActive }) => `rail-item${isActive ? ' active' : ''}`}
            aria-label={entry.label}
          >
            <Badge dot={entry.path === '/alerts' && (unread.data?.unread ?? 0) > 0} offset={[-2, 2]}>
              <span className="rail-icon">{entry.icon}</span>
            </Badge>
            <span className="rail-label">{entry.label}</span>
          </NavLink>
        ))}
        <div className="rail-spacer" />
        <Tooltip title="로그아웃" placement="right">
          <Button
            type="text"
            aria-label="로그아웃"
            className="rail-logout"
            icon={<LogoutOutlined />}
            loading={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/login', { replace: true }) })}
          />
        </Tooltip>
      </nav>

      <div className="main">
        <header className="topbar">
          <Tabs
            className="screen-tabs"
            type="editable-card"
            hideAdd
            size="small"
            activeKey={active}
            onChange={(path) => navigate(path)}
            onEdit={(target, action) => {
              if (action === 'remove' && typeof target === 'string') navigate(close(target, active))
            }}
            items={tabs.map((path) => {
              const entry = entryFor(path)
              return {
                key: path,
                label: (
                  <span>
                    {entry?.icon} {entry?.label}
                  </span>
                ),
                closable: tabs.length > 1,
              }
            })}
          />
          <HeaderStatus />
        </header>
        <HealthBanner />
        <AlertFeed />
        <main className="content">
          <Outlet />
        </main>
        <footer className="footer">
          <Disclaimer />
        </footer>
      </div>
    </div>
  )
}
