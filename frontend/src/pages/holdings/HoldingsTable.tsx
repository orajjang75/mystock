import { Button, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import type { HoldingOut } from '../../api/types'
import { Direction } from '../../components/Direction'
import { formatNumber, formatPercent } from '../../lib/format'
import { HoldingStateTag } from './holdingState'

interface Props {
  holdings: HoldingOut[]
  selectedId: number | undefined
  loading: boolean
  onSelect: (id: number) => void
  onRecord: (holding: HoldingOut) => void
}

/** 종목 표: one row per holding with its state tag, the rebuy target and the stop line. */
export function HoldingsTable({ holdings, selectedId, loading, onSelect, onRecord }: Props) {
  const columns: ColumnsType<HoldingOut> = [
    {
      title: '종목',
      key: 'name',
      render: (_, h) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{h.name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {h.code} · {h.market}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '상태',
      key: 'state',
      render: (_, h) => (
        <Space size={4} wrap>
          <HoldingStateTag state={h.state} />
          {h.daily_downtrend && <Tag color="orange">일봉 하락 추세</Tag>}
        </Space>
      ),
    },
    {
      title: '수량',
      key: 'quantity',
      align: 'right',
      render: (_, h) => (
        <Space direction="vertical" size={0} style={{ textAlign: 'right' }}>
          <span>{formatNumber(h.quantity)}주</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            시작 {formatNumber(h.start_quantity)}
          </Typography.Text>
        </Space>
      ),
    },
    { title: '평균단가', dataIndex: 'avg_price', align: 'right', render: (v: number) => formatNumber(v) },
    {
      title: '현재가',
      key: 'last_close',
      align: 'right',
      render: (_, h) => {
        const gain = h.last_close === null ? null : (h.last_close / h.avg_price - 1) * 100
        return (
          <Space direction="vertical" size={0} style={{ textAlign: 'right' }}>
            <span>{formatNumber(h.last_close)}</span>
            <Direction value={gain}>{formatPercent(gain)}</Direction>
          </Space>
        )
      },
    },
    {
      title: '재매수 목표가',
      key: 'target',
      align: 'right',
      render: (_, h) =>
        h.open_cycle ? (
          <Space direction="vertical" size={0} style={{ textAlign: 'right' }}>
            <span>{formatNumber(h.open_cycle.rebuy_target_price)}</span>
            {h.open_cycle.expires_at && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                ~{dayjs(h.open_cycle.expires_at).format('MM-DD')}
              </Typography.Text>
            )}
          </Space>
        ) : (
          '-'
        ),
    },
    { title: 'ATR 손절선', dataIndex: 'stop_price', align: 'right', render: (v: number | null) => formatNumber(v) },
    {
      title: '누적 수량 증가',
      dataIndex: 'cumulative_increase',
      align: 'right',
      render: (v: number) => <Direction value={v}>{v > 0 ? '+' : ''}{v}주</Direction>,
    },
    {
      title: '',
      key: 'actions',
      align: 'right',
      render: (_, h) => (
        <Button
          size="small"
          aria-label={`${h.name} 체결 기록`}
          onClick={(event) => {
            event.stopPropagation()
            onRecord(h)
          }}
        >
          체결 기록
        </Button>
      ),
    },
  ]

  return (
    <Table<HoldingOut>
      size="middle"
      rowKey="id"
      loading={loading}
      dataSource={holdings}
      columns={columns}
      pagination={false}
      scroll={{ x: 900 }}
      locale={{ emptyText: '등록한 보유 종목이 없습니다. 위의 "보유 종목 등록"으로 추가하세요.' }}
      rowClassName={(h) => (h.id === selectedId ? 'row-selected' : '')}
      onRow={(h) => ({ onClick: () => onSelect(h.id), style: { cursor: 'pointer' } })}
    />
  )
}
