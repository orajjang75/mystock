import {
  AlertOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FundOutlined,
  RadarChartOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

export interface MenuEntry {
  path: string
  label: string
  icon: ReactNode
}

// The six main menus of PRD 7장, in order.
export const MENU: MenuEntry[] = [
  { path: '/', label: '대시보드', icon: <DashboardOutlined /> },
  { path: '/screener', label: '스크리너', icon: <RadarChartOutlined /> },
  { path: '/holdings', label: '보유 종목', icon: <FundOutlined /> },
  { path: '/alerts', label: '알림', icon: <AlertOutlined /> },
  { path: '/backtest', label: '백테스트', icon: <ExperimentOutlined /> },
  { path: '/settings', label: '설정', icon: <SettingOutlined /> },
]

export function entryFor(path: string): MenuEntry | undefined {
  return MENU.find((entry) => entry.path === path)
}
