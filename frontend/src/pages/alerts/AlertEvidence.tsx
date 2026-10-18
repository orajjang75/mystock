import { Descriptions, Space, Tag, Typography } from 'antd'
import type { AlertOut } from '../../api/types'
import { SIGNAL_LABELS, evidenceRows } from '../../features/evidence'

/** 근거 지표 값: the numbers and signals the alert was made from. */
export function AlertEvidence({ alert }: { alert: AlertOut }) {
  const rows = evidenceRows(alert.evidence)
  const signals = Array.isArray(alert.evidence.signals) ? (alert.evidence.signals as string[]) : []
  const others = rows.filter((row) => row.key !== 'signals')
  return (
    <Space direction="vertical" size="small" className="alert-evidence">
      {alert.kind === 'rebuy_held' && (
        <Typography.Text type="warning">
          재매수 조건은 맞았지만 일봉 수급 이탈 상태라 알림을 보류했습니다. 이 경고에는 체결을 기록하지 않습니다.
        </Typography.Text>
      )}
      {signals.length > 0 && (
        <Space size={[4, 4]} wrap aria-label="충족한 신호">
          {signals.map((name) => (
            <Tag key={name} color="cyan">
              {SIGNAL_LABELS[name] ?? name}
            </Tag>
          ))}
        </Space>
      )}
      {others.length > 0 ? (
        <Descriptions size="small" bordered column={{ xs: 1, sm: 2, lg: 3 }}>
          {others.map((row) => (
            <Descriptions.Item key={row.key} label={row.label}>
              {row.value}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ) : (
        signals.length === 0 && <Typography.Text type="secondary">기록된 근거 지표가 없습니다.</Typography.Text>
      )}
    </Space>
  )
}
