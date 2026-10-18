import { Progress, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ResultItem } from '../../api/types'
import { Direction } from '../../components/Direction'
import { formatAmount, formatNumber, formatPercent, formatScore } from '../../lib/format'
import { WatchButton } from './WatchButton'
import { tagColor } from './tags'

interface Props {
  items: ResultItem[]
  loading?: boolean
  onOpen: (code: string) => void
}

const num = (value: number | null | undefined) => value ?? Number.NEGATIVE_INFINITY

/** 점수순 결과 표. Clicking a row opens the stock's detail drawer. */
export function ResultsTable({ items, loading, onOpen }: Props) {
  const columns: ColumnsType<ResultItem> = [
    {
      title: '',
      key: 'watch',
      width: 44,
      render: (_, row) => <WatchButton code={row.code} watched={row.in_watchlist} />,
    },
    {
      title: '종목',
      key: 'name',
      width: 180,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{row.name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.code} · {row.market}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '점수',
      dataIndex: 'score',
      width: 130,
      defaultSortOrder: 'descend',
      sorter: (a, b) => a.score - b.score,
      render: (score: number) => (
        <Space direction="vertical" size={0} style={{ width: 100 }}>
          <Typography.Text strong>{formatScore(score)}</Typography.Text>
          <Progress percent={score} showInfo={false} size="small" strokeColor="#722ed1" />
        </Space>
      ),
    },
    {
      title: '충족 조건',
      dataIndex: 'tags',
      render: (tags: ResultItem['tags']) => (
        <Space size={[4, 4]} wrap>
          {tags.map((tag) => (
            <Tag key={tag.key} color={tagColor(tag.key)} style={{ marginInlineEnd: 0 }}>
              {tag.label}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '거래대금',
      dataIndex: 'trading_value',
      align: 'right',
      width: 100,
      sorter: (a, b) => num(a.trading_value) - num(b.trading_value),
      render: (value: number | null) => formatAmount(value),
    },
    {
      title: '등락률',
      dataIndex: 'change_pct',
      align: 'right',
      width: 90,
      sorter: (a, b) => num(a.change_pct) - num(b.change_pct),
      render: (value: number | null) => <Direction value={value}>{formatPercent(value)}</Direction>,
    },
    {
      title: '종가',
      dataIndex: 'close',
      align: 'right',
      width: 90,
      render: (value: number | null) => formatNumber(value),
    },
  ]

  return (
    <Table<ResultItem>
      rowKey="code"
      size="middle"
      columns={columns}
      dataSource={items}
      loading={loading}
      scroll={{ x: 860 }}
      pagination={{ pageSize: 20, showSizeChanger: false, hideOnSinglePage: true }}
      locale={{ emptyText: '이 날짜의 스캔 결과가 없습니다' }}
      onRow={(row) => ({ onClick: () => onOpen(row.code), style: { cursor: 'pointer' } })}
    />
  )
}
