import { DeleteOutlined, DownloadOutlined } from '@ant-design/icons'
import { App as AntdApp, Alert, Button, Card, Popconfirm, Progress, Space, Tabs, Tag, Typography, type TabsProps } from 'antd'
import dayjs from 'dayjs'
import { errorMessage } from '../../api/client'
import { useDeleteBacktest } from '../../api/queries'
import type { BacktestRun } from '../../api/types'
import { asDetail, asSummary } from '../../features/backtest/result'
import { CompareTab } from './CompareTab'
import { downloadReport } from './downloadReport'
import { CycleTab } from './CycleTab'
import { PresetActions } from './PresetActions'
import { QualityTab } from './QualityTab'
import { SensitivityTab } from './SensitivityTab'
import { SummaryTab } from './SummaryTab'
import { WalkForwardTab } from './WalkForwardTab'

export function ResultView({ run, onDeleted }: { run: BacktestRun; onDeleted: () => void }) {
  const { message } = AntdApp.useApp()
  const remove = useDeleteBacktest()
  const summary = asSummary(run.summary)
  const detail = asDetail(run.detail)
  const title = run.name || `백테스트 #${run.id}`

  if (run.status === 'queued' || run.status === 'running') {
    return (
      <Card size="small" title={title}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Progress percent={Math.round(run.progress * 100)} status="active" aria-label="진행률" />
          <Typography.Text type="secondary">{run.status === 'queued' ? '순서를 기다리는 중입니다' : (summary.message ?? '계산하는 중입니다')}</Typography.Text>
        </Space>
      </Card>
    )
  }
  if (run.status === 'failed') {
    return (
      <Card size="small" title={title} extra={<Tag color="error">실패</Tag>}>
        <Alert type="error" showIcon message="백테스트를 끝내지 못했습니다" description={run.error ?? '알 수 없는 오류'} />
      </Card>
    )
  }

  const items: TabsProps['items'] = [
    { key: 'summary', label: '요약', children: <SummaryTab summary={summary} /> },
    detail.signal_quality && { key: 'quality', label: '신호 품질', children: <QualityTab detail={detail.signal_quality} /> },
    detail.cycle && { key: 'cycle', label: '수량 늘리기', children: <CycleTab detail={detail.cycle} /> },
    detail.cycle && detail.cycle.comparison.length > 0 && { key: 'compare', label: '봉 길이 비교', children: <CompareTab rows={detail.cycle.comparison} /> },
    detail.sensitivity && { key: 'sensitivity', label: '민감도 히트맵', children: <SensitivityTab grid={detail.sensitivity} /> },
    detail.walk_forward && { key: 'walk', label: '롤링 검증', children: <WalkForwardTab wf={detail.walk_forward} /> },
  ].filter((item): item is NonNullable<typeof item> => Boolean(item))

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card
        size="small"
        title={
          <Space wrap>
            <span>{title}</span>
            <Tag color="green">완료</Tag>
            <Typography.Text type="secondary">
              {run.start_date} ~ {run.end_date} · {dayjs(run.executed_at).format('YYYY-MM-DD HH:mm')} 실행
            </Typography.Text>
          </Space>
        }
        extra={
          <Space wrap>
            <Button
              icon={<DownloadOutlined />}
              onClick={() => void downloadReport(run.id).catch((e: unknown) => void message.error(errorMessage(e)))}
            >
              리포트 내려받기
            </Button>
            <Popconfirm
              title="이 실행을 삭제할까요?"
              okText="삭제"
              cancelText="취소"
              onConfirm={() => remove.mutate(run.id, { onSuccess: onDeleted, onError: (e) => void message.error(errorMessage(e)) })}
            >
              <Button danger icon={<DeleteOutlined />} loading={remove.isPending}>
                삭제
              </Button>
            </Popconfirm>
          </Space>
        }
      >
        <PresetActions key={run.id} runId={run.id} defaultName={run.name || `백테스트 #${run.id}`} />
      </Card>
      <Tabs items={items} destroyInactiveTabPane />
    </Space>
  )
}
