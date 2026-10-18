import { Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import type { CycleOut } from '../../api/types'
import { Direction } from '../../components/Direction'
import { formatNumber } from '../../lib/format'
import { CycleStateTag } from './holdingState'

const when = (value: string | null) => (value ? dayjs(value).format('MM-DD HH:mm') : '-')

/** 사이클 이력: every sale and rebuy with the 수량 증가분 and the cash result after costs. */
export function CycleTable({ cycles, loading }: { cycles: CycleOut[]; loading: boolean }) {
  const columns: ColumnsType<CycleOut> = [
    { title: '#', key: 'no', width: 48, render: (_, __, index) => index + 1 },
    { title: '상태', dataIndex: 'state', render: (state: CycleOut['state']) => <CycleStateTag state={state} /> },
    {
      title: '매도',
      key: 'sell',
      render: (_, c) => (
        <div>
          <div>
            {formatNumber(c.sell_price)} × {formatNumber(c.sell_quantity)}주
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {when(c.sold_at)}
          </Typography.Text>
        </div>
      ),
    },
    { title: '재매수 목표가', dataIndex: 'rebuy_target_price', align: 'right', render: (v: number) => formatNumber(v) },
    {
      title: '재매수',
      key: 'rebuy',
      render: (_, c) =>
        c.rebuy_price !== null && c.rebuy_quantity !== null ? (
          <div>
            <div>
              {formatNumber(c.rebuy_price)} × {formatNumber(c.rebuy_quantity)}주
            </div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {when(c.rebought_at)}
            </Typography.Text>
          </div>
        ) : c.expires_at && (c.state === 'rebuy_wait' || c.state === 'expired') ? (
          <Typography.Text type="secondary">~{dayjs(c.expires_at).format('MM-DD')}까지</Typography.Text>
        ) : (
          '-'
        ),
    },
    {
      title: '수량 증가분',
      dataIndex: 'quantity_increase',
      align: 'right',
      render: (v: number | null) =>
        v === null ? (
          '-'
        ) : (
          <Direction value={v}>
            <strong>
              {v > 0 ? '+' : ''}
              {v}주
            </strong>
          </Direction>
        ),
    },
    {
      title: '현금 결과',
      dataIndex: 'net_cash',
      align: 'right',
      render: (v: number | null) => (v === null ? '-' : <Direction value={v}>{formatNumber(v)}</Direction>),
    },
    {
      title: '수수료·세금',
      key: 'costs',
      align: 'right',
      render: (_, c) => formatNumber(c.sell_fee + c.sell_tax + (c.rebuy_fee ?? 0)),
    },
  ]
  return (
    <Table<CycleOut>
      size="small"
      rowKey="id"
      loading={loading}
      dataSource={cycles}
      columns={columns}
      pagination={false}
      scroll={{ x: 760 }}
      locale={{ emptyText: '아직 사이클이 없습니다. 매도 체결을 기록하면 시작됩니다.' }}
    />
  )
}
