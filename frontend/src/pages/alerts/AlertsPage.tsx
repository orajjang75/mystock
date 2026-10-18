import { WarningOutlined } from '@ant-design/icons'
import { Button, Card, Checkbox, Empty, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAlerts, useHoldings, useMarkAlertRead } from '../../api/queries'
import type { AlertOut } from '../../api/types'
import { PageHeader } from '../../components/PageHeader'
import { alertPath, fillSideOf, holdingPath } from '../../features/alertTargets'
import { formatNumber } from '../../lib/format'
import { ExpiredActions } from '../holdings/ExpiredActions'
import { AlertEvidence } from './AlertEvidence'

const PAGE_SIZE = 100

/** 알림 화면: every alert, filterable, with the evidence behind it and the next step. */
export function AlertsPage() {
  const navigate = useNavigate()
  const [kind, setKind] = useState<string | undefined>()
  const [code, setCode] = useState<string | undefined>()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const alerts = useAlerts({ kind, code, unread_only: unreadOnly || undefined, limit: PAGE_SIZE })
  const holdings = useHoldings()
  const markRead = useMarkAlertRead()

  const items = alerts.data?.items ?? []
  const stocks = (holdings.data ?? []).map((h) => ({ value: h.code, label: `${h.name} (${h.code})` }))

  // The 만료 alert offers its choice only while that very cycle is still the expired one.
  const openExpired = (alert: AlertOut) => {
    const holding = holdings.data?.find((h) => h.id === alert.holding_id)
    return holding?.state === 'expired' && holding.open_cycle?.id === alert.evidence.cycle_id ? holding : undefined
  }

  const columns: ColumnsType<AlertOut> = [
    {
      title: '시각',
      dataIndex: 'occurred_at',
      width: 110,
      render: (v: string, a) => <span style={{ fontWeight: a.is_read ? 400 : 600 }}>{dayjs(v).format('MM-DD HH:mm')}</span>,
    },
    {
      title: '종류',
      dataIndex: 'label',
      render: (_, a) =>
        a.kind === 'rebuy_held' ? (
          <Space direction="vertical" size={2}>
            <Tag color="warning" icon={<WarningOutlined />}>
              경고
            </Tag>
            <Typography.Text strong>일봉 수급 이탈로 보류됨</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              재매수 조건은 충족
            </Typography.Text>
          </Space>
        ) : (
          <Space size={4} wrap>
            {a.level === 'warning' && (
              <Tag color="warning" icon={<WarningOutlined />}>
                경고
              </Tag>
            )}
            <Tag color={a.level === 'warning' ? 'warning' : 'processing'}>{a.label}</Tag>
          </Space>
        ),
    },
    {
      title: '종목',
      dataIndex: 'name',
      render: (v: string | null, a) => (
        <span style={{ fontWeight: a.is_read ? 400 : 600 }}>
          {v ?? '-'}
          {a.code && <Typography.Text type="secondary"> {a.code}</Typography.Text>}
        </span>
      ),
    },
    { title: '제안 수량', dataIndex: 'suggested_quantity', align: 'right', render: (v: number | null) => (v ? `${formatNumber(v)}주` : '-') },
    { title: '가격', dataIndex: 'price', align: 'right', render: (v: number | null) => formatNumber(v) },
    { title: '재매수 목표가', dataIndex: 'rebuy_target_price', align: 'right', render: (v: number | null) => formatNumber(v) },
    {
      title: '',
      key: 'actions',
      align: 'right',
      render: (_, a) => {
        const expired = a.kind === 'expired' ? openExpired(a) : undefined
        return (
          <Space size={4} wrap style={{ justifyContent: 'flex-end' }}>
            {fillSideOf(a) && a.holding_id !== null && (
              <Button size="small" type={a.is_read ? 'default' : 'primary'} onClick={() => navigate(alertPath(a))}>
                체결 기록
              </Button>
            )}
            {expired?.open_cycle && (
              <ExpiredActions
                compact
                holdingId={expired.id}
                name={expired.name}
                cycleId={expired.open_cycle.id}
                rebuyTargetPrice={expired.open_cycle.rebuy_target_price}
                expiresAt={expired.open_cycle.expires_at}
              />
            )}
            {a.holding_id !== null && !fillSideOf(a) && !expired && a.kind !== 'data_stale' && (
              <Button size="small" onClick={() => navigate(holdingPath(a.holding_id as number))}>
                보유 종목 보기
              </Button>
            )}
            {!a.is_read && (
              <Button size="small" aria-label={`${a.label} 읽음 처리`} loading={markRead.isPending && markRead.variables === a.id} onClick={() => markRead.mutate(a.id)}>
                읽음
              </Button>
            )}
          </Space>
        )
      },
    },
  ]

  return (
    <>
      <PageHeader title="알림" description="신호 알림과 경고를 종류·종목별로 모아 보고, 행을 펼치면 근거 지표 값을 볼 수 있습니다." />
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Card size="small">
          <Space wrap size="middle">
            <Select
              allowClear
              placeholder="신호 종류"
              aria-label="신호 종류"
              style={{ width: 260 }}
              value={kind}
              onChange={setKind}
              options={(alerts.data?.kinds ?? []).map((k) => ({
                value: k.kind,
                label: k.level === 'warning' ? `⚠ ${k.label}` : k.label,
              }))}
            />
            <Select
              allowClear
              placeholder="종목"
              aria-label="종목"
              style={{ width: 220 }}
              value={code}
              onChange={setCode}
              options={stocks}
            />
            <Checkbox checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)}>
              읽지 않은 알림만
            </Checkbox>
            <Typography.Text type="secondary">
              읽지 않음 {alerts.data?.unread ?? 0}건 · 표시 {items.length}건
            </Typography.Text>
          </Space>
        </Card>
        <Card size="small" styles={{ body: { padding: 0 } }}>
          <Table<AlertOut>
            size="middle"
            rowKey="id"
            loading={alerts.isPending}
            dataSource={items}
            columns={columns}
            pagination={false}
            scroll={{ x: 900 }}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="조건에 맞는 알림이 없습니다" /> }}
            rowClassName={(a) => (a.level === 'warning' ? 'alert-row-warning' : a.is_read ? '' : 'alert-row-unread')}
            expandable={{ expandedRowRender: (a) => <AlertEvidence alert={a} />, expandRowByClick: false }}
          />
        </Card>
      </Space>
    </>
  )
}
