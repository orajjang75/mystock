import { BellOutlined, ReloadOutlined } from '@ant-design/icons'
import { useIsFetching, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Space, Tag, Tooltip } from 'antd'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { useAlerts, useHealth, usePollingMs } from '../api/queries'

type Tone = { color: string; text: string }

function statusTone(status: string | undefined, connected: boolean): Tone {
  if (!connected) return { color: 'error', text: '연결 끊김' }
  if (status === 'ok') return { color: 'success', text: '정상' }
  if (status === 'degraded') return { color: 'warning', text: '지연' }
  if (status === 'error') return { color: 'error', text: '오류' }
  return { color: 'default', text: '확인 중' }
}

/** Top-right: unread-alert badge, last refresh status, and the manual refresh button. */
export function HeaderStatus() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const polling = usePollingMs()
  const health = useHealth()
  const unread = useAlerts({ unread_only: true, limit: 20 })
  const fetching = useIsFetching() > 0

  const tone = statusTone(health.data?.status, !health.isError)
  const checkedAt = health.dataUpdatedAt ? dayjs(health.dataUpdatedAt).format('HH:mm:ss') : '--:--:--'
  const quote = health.data?.last_quote_update
  const period = polling === false ? '수동 조회' : `${Math.round(polling / 1000)}초마다`

  return (
    <Space size="middle" className="header-status">
      <Tooltip title="알림 보기">
        <Badge count={unread.data?.unread ?? 0} overflowCount={99} size="small">
          <Button
            type="text"
            aria-label="알림"
            icon={<BellOutlined />}
            onClick={() => navigate('/alerts')}
          />
        </Badge>
      </Tooltip>
      <Tooltip
        title={
          quote ? `마지막 시세 갱신 ${dayjs(quote).format('MM-DD HH:mm:ss')} · ${period}` : `시세 갱신 기록 없음 · ${period}`
        }
      >
        <Tag color={tone.color} style={{ marginInlineEnd: 0 }}>
          {tone.text} · {checkedAt}
        </Tag>
      </Tooltip>
      <Tooltip title="지금 조회">
        <Button
          type="text"
          aria-label="새로고침"
          icon={<ReloadOutlined spin={fetching} />}
          onClick={() => void client.refetchQueries({ type: 'active' })}
        />
      </Tooltip>
    </Space>
  )
}
