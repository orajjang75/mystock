import { Card, Descriptions, Tag } from 'antd'
import dayjs from 'dayjs'
import { useHealth } from '../../api/queries'

const SOURCE_LABELS: Record<string, string> = { daily: '일봉', intraday: '분봉' }

/** 시세 수집 상태: when each source was last collected and whether it is late. */
export function SystemStatus() {
  const health = useHealth()
  const data = health.data

  return (
    <Card title="시세 수집 상태" loading={health.isPending} size="small">
      {data && (
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="마지막 시세 갱신">
            {data.last_quote_update ? dayjs(data.last_quote_update).format('YYYY-MM-DD HH:mm:ss') : '기록 없음'}
          </Descriptions.Item>
          {Object.entries(data.collection).map(([source, state]) => (
            <Descriptions.Item key={source} label={`${SOURCE_LABELS[source] ?? source} 수집`}>
              <Tag color={state.stale ? 'warning' : 'success'}>{state.stale ? '지연' : '정상'}</Tag>
              {state.last_success ? dayjs(state.last_success).format('MM-DD HH:mm') : '수집 기록 없음'}
              {state.last_error && <Tag color="error">{state.last_error}</Tag>}
            </Descriptions.Item>
          ))}
          <Descriptions.Item label="스케줄러">{data.scheduler === 'running' ? '실행 중' : '꺼짐'}</Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  )
}
