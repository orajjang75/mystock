import { Progress, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import type { BacktestRunSummary } from '../../api/types'
import { Direction } from '../../components/Direction'
import { asSummary } from '../../features/backtest/result'
import { AdoptionTag } from './AdoptionTag'
import { plainFraction, shares, signedFraction } from './fmt'

interface Props {
  runs: BacktestRunSummary[]
  loading: boolean
  selectedId: number | undefined
  onSelect: (id: number) => void
}

const STATUS: Record<string, { label: string; color: string }> = {
  queued: { label: '대기', color: 'default' },
  running: { label: '실행 중', color: 'processing' },
  done: { label: '완료', color: 'green' },
  failed: { label: '실패', color: 'error' },
}

/** 실행 목록: every stored run with its headline numbers. */
export function RunList({ runs, loading, selectedId, onSelect }: Props) {
  const columns: ColumnsType<BacktestRunSummary> = [
    { title: '#', dataIndex: 'id', width: 56 },
    {
      title: '이름',
      render: (_, r) => (
        <div>
          <Typography.Text strong>{r.name || `백테스트 #${r.id}`}</Typography.Text>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {dayjs(r.executed_at).format('MM-DD HH:mm')} · {r.start_date} ~ {r.end_date} · {r.bar_length}
            </Typography.Text>
          </div>
        </div>
      ),
    },
    {
      title: '상태',
      render: (_, r) =>
        r.status === 'running' || r.status === 'queued' ? (
          <Progress percent={Math.round(r.progress * 100)} size="small" style={{ minWidth: 100 }} />
        ) : (
          <Tag color={STATUS[r.status]?.color}>{STATUS[r.status]?.label ?? r.status}</Tag>
        ),
    },
    {
      title: '후보 중앙값 / 유니버스',
      align: 'right',
      render: (_, r) => {
        const q = asSummary(r.summary).signal_quality
        return q ? (
          <span>
            <Direction value={q.strategy.median}>{signedFraction(q.strategy.median)}</Direction> / {signedFraction(q.universe.median)}
          </span>
        ) : (
          '-'
        )
      },
    },
    {
      title: '사이클 성공률 · 누적 증가',
      align: 'right',
      render: (_, r) => {
        const c = asSummary(r.summary).cycle
        return c ? `${plainFraction(c.headline.completion_rate)} · ${shares(c.headline.cumulative_increase)}` : '-'
      },
    },
    {
      title: '표본',
      render: (_, r) => {
        const s = asSummary(r.summary)
        const adoptions = [s.signal_quality?.adoption, s.cycle?.adoption].filter((a) => a !== undefined)
        if (r.status !== 'done' || adoptions.length === 0) return '-'
        return <AdoptionTag adoption={{ adoptable: adoptions.every((a) => a.adoptable), reasons: adoptions.flatMap((a) => a.reasons) }} />
      },
    },
  ]
  return (
    <Table<BacktestRunSummary>
      size="small"
      rowKey="id"
      loading={loading}
      dataSource={runs}
      columns={columns}
      pagination={{ pageSize: 8, size: 'small', hideOnSinglePage: true }}
      scroll={{ x: 760 }}
      locale={{ emptyText: '아직 실행한 백테스트가 없습니다. 위 폼에서 실행하세요.' }}
      rowClassName={(r) => (r.id === selectedId ? 'row-selected' : '')}
      onRow={(r) => ({ onClick: () => onSelect(r.id), style: { cursor: 'pointer' } })}
    />
  )
}
