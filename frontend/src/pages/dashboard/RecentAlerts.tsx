import { Card, Empty, List, Space, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { useAlerts } from '../../api/queries'
import { alertPath } from '../../features/alertTargets'

/** 최근 알림 5건. */
export function RecentAlerts() {
  const navigate = useNavigate()
  const alerts = useAlerts({ limit: 5 })
  const items = alerts.data?.items ?? []

  return (
    <Card
      title="최근 알림"
      extra={<Typography.Text type="secondary">읽지 않음 {alerts.data?.unread ?? 0}건</Typography.Text>}
      loading={alerts.isPending}
      size="small"
    >
      {items.length === 0 ? (
        <Empty description="아직 알림이 없습니다" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          dataSource={items}
          renderItem={(alert) => (
            <List.Item style={{ cursor: 'pointer' }} onClick={() => navigate(alertPath(alert))}>
              <List.Item.Meta
                title={
                  <Space wrap size={6}>
                    <Tag color={alert.level === 'warning' ? 'warning' : 'processing'}>{alert.label}</Tag>
                    <span style={{ fontWeight: alert.is_read ? 400 : 600 }}>{alert.name ?? ''}</span>
                  </Space>
                }
                description={dayjs(alert.occurred_at).format('MM-DD HH:mm')}
              />
              {alert.suggested_quantity ? <Typography.Text>제안 {alert.suggested_quantity}주</Typography.Text> : null}
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}
