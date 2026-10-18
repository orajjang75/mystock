import { Button, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { WatchlistItem } from '../../api/types'
import { Direction } from '../../components/Direction'
import { formatChange, formatScore } from '../../lib/format'
import { useToggleWatch } from '../../api/queries'

interface Props {
  items: WatchlistItem[]
  loading?: boolean
  onOpen: (code: string) => void
}

/** 관심종목 보기: latest score, change since the previous scan, and a remove button. */
export function WatchlistTable({ items, loading, onOpen }: Props) {
  const toggle = useToggleWatch()

  const columns: ColumnsType<WatchlistItem> = [
    {
      title: '종목',
      key: 'name',
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
      title: '최신 점수',
      dataIndex: 'score',
      align: 'right',
      render: (score: number | null, row) =>
        score === null ? (
          <Tag>{row.scan_date ? '게이트 미통과' : '스캔 없음'}</Tag>
        ) : (
          <Typography.Text strong>{formatScore(score)}</Typography.Text>
        ),
    },
    {
      title: '전일 대비',
      dataIndex: 'change',
      align: 'right',
      render: (change: number | null) =>
        change === null ? '-' : <Direction value={change}>{formatChange(change)}</Direction>,
    },
    {
      title: '이전 점수',
      dataIndex: 'previous_score',
      align: 'right',
      render: (score: number | null) => formatScore(score),
    },
    { title: '추가일', dataIndex: 'added_date', width: 110 },
    {
      title: '',
      key: 'remove',
      width: 80,
      render: (_, row) => (
        <Button
          size="small"
          danger
          loading={toggle.isPending && toggle.variables?.code === row.code}
          onClick={(event) => {
            event.stopPropagation()
            toggle.mutate({ code: row.code, watched: true })
          }}
        >
          제외
        </Button>
      ),
    },
  ]

  return (
    <Table<WatchlistItem>
      rowKey="code"
      size="middle"
      columns={columns}
      dataSource={items}
      loading={loading}
      scroll={{ x: 640 }}
      pagination={false}
      locale={{ emptyText: '관심종목이 없습니다. 결과 표의 ★로 추가하세요.' }}
      onRow={(row) => ({ onClick: () => onOpen(row.code), style: { cursor: 'pointer' } })}
    />
  )
}
