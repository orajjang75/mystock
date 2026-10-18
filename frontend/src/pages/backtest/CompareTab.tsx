import { Alert, Card, Select, Space, Table, Typography } from 'antd'
import { useState } from 'react'
import { EChart } from '../../components/charts/EChart'
import { Direction } from '../../components/Direction'
import type { CompareRow } from '../../features/backtest/result'
import { AdoptionTag } from './AdoptionTag'
import { COMPARE_METRICS, compareOption, type CompareMetric } from './chartOptions'
import { plainFraction, shares, signedFraction } from './fmt'

/** 봉 길이 비교: the same signal code over the same period on 30-minute, 60-minute and daily bars. */
export function CompareTab({ rows }: { rows: CompareRow[] }) {
  const [metric, setMetric] = useState<CompareMetric>('mean_increase_rate')
  const thin = rows.filter((r) => !r.adoption.adoptable)
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="봉 길이가 길수록 신호 표본이 줄어듭니다"
        description="같은 기간, 같은 종목, 같은 신호 코드로 돌린 결과입니다. 끝난 매도 수와 신호가 난 날 수를 함께 보고, 표본이 부족한 행은 비교 대상으로 삼지 마세요."
      />
      <Card
        size="small"
        title="비용 반영 후 봉 길이별 비교"
        extra={
          <Select
            aria-label="비교 지표"
            value={metric}
            onChange={setMetric}
            style={{ width: 260 }}
            options={(Object.keys(COMPARE_METRICS) as CompareMetric[]).map((m) => ({ value: m, label: COMPARE_METRICS[m].label }))}
          />
        }
      >
        <EChart option={compareOption(rows, metric)} height={260} label="봉 길이별 비교" />
        <Table<CompareRow>
          size="small"
          rowKey="bar_length"
          dataSource={rows}
          pagination={false}
          scroll={{ x: 900 }}
          columns={[
            { title: '봉', dataIndex: 'bar_length' },
            { title: '끝난 매도', dataIndex: 'finished', align: 'right' },
            { title: '신호 발생일', dataIndex: 'signal_dates', align: 'right' },
            { title: '성공률', align: 'right', render: (_, r) => plainFraction(r.completion_rate) },
            { title: '평균 수량 증가율', align: 'right', render: (_, r) => <Direction value={r.mean_increase_rate}>{signedFraction(r.mean_increase_rate)}</Direction> },
            { title: '누적 수량 증가', align: 'right', render: (_, r) => <Direction value={r.cumulative_increase}>{shares(r.cumulative_increase)}</Direction> },
            { title: '수익률', align: 'right', render: (_, r) => signedFraction(r.total_return) },
            { title: '최대 낙폭', align: 'right', render: (_, r) => signedFraction(r.max_drawdown) },
            { title: '강제 매도', dataIndex: 'forced', align: 'right' },
            { title: '표본', render: (_, r) => <AdoptionTag adoption={r.adoption} /> },
          ]}
        />
        {thin.length > 0 && (
          <Typography.Text type="warning">
            표본 부족: {thin.map((r) => r.bar_length).join(', ')}. 숫자는 보여 주지만 채택 근거로 쓰지 않습니다.
          </Typography.Text>
        )}
      </Card>
    </Space>
  )
}
