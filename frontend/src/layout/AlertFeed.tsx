import { App as AntdApp, Alert, Button, Space } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAlerts } from '../api/queries'
import type { AlertOut } from '../api/types'
import { alertPath, fillSideOf } from '../features/alertTargets'
import { describeAlert, detectNewAlerts, readLastSeen, writeLastSeen } from '../features/newAlerts'

/** What a click on the notification does, in a few words. */
function hint(alert: AlertOut): string {
  const path = alertPath(alert)
  if (path === '/alerts') return '클릭하면 알림 화면으로 이동합니다'
  return fillSideOf(alert) ? '클릭하면 보유 종목에서 체결을 기록합니다' : '클릭하면 보유 종목 화면으로 이동합니다'
}

/**
 * Watches the polled unread alerts. A new one raises an antd notification and joins the banner
 * above the content, until the user dismisses it or opens the alerts screen.
 */
export function AlertFeed() {
  const { notification } = AntdApp.useApp()
  const navigate = useNavigate()
  const { data } = useAlerts({ unread_only: true, limit: 20 })
  const [banner, setBanner] = useState<AlertOut[]>([])
  const lastSeen = useRef<number | null | undefined>(undefined)

  useEffect(() => {
    if (!data) return
    if (lastSeen.current === undefined) lastSeen.current = readLastSeen()
    const { fresh, nextSeen } = detectNewAlerts(data.items, lastSeen.current)
    lastSeen.current = nextSeen
    writeLastSeen(nextSeen)
    if (fresh.length === 0) return
    setBanner((current) => [...current, ...fresh.filter((a) => !current.some((c) => c.id === a.id))])
    for (const alert of fresh) {
      notification.open({
        key: `alert-${alert.id}`,
        type: alert.level === 'warning' ? 'warning' : 'info',
        message: describeAlert(alert),
        description: hint(alert),
        placement: 'topRight',
        onClick: () => {
          notification.destroy(`alert-${alert.id}`)
          navigate(alertPath(alert))
        },
      })
    }
  }, [data, notification, navigate])

  if (banner.length === 0) return null
  const latest = banner[banner.length - 1]
  const others = banner.length > 1 ? ` 외 ${banner.length - 1}건` : ''
  return (
    <Alert
      banner
      closable
      type={banner.some((a) => a.level === 'warning') ? 'warning' : 'info'}
      message={`새 알림 ${banner.length}건 · ${describeAlert(latest)}${others}`}
      action={
        <Space size={0}>
          {fillSideOf(latest) && latest.holding_id !== null && (
            <Button
              size="small"
              type="link"
              onClick={() => {
                setBanner([])
                navigate(alertPath(latest))
              }}
            >
              체결 기록
            </Button>
          )}
          <Button
            size="small"
            type="link"
            onClick={() => {
              setBanner([])
              navigate('/alerts')
            }}
          >
            알림 보기
          </Button>
        </Space>
      }
      onClose={() => setBanner([])}
    />
  )
}
