import { Alert, Card, Descriptions, Space, Table, Typography } from 'antd'
import { EChart } from '../../components/charts/EChart'
import type { Fold, WalkForward } from '../../features/backtest/result'
import { GROUP_TITLES, PARAM_LABELS } from '../settings/paramLabels'
import { METRIC_LABELS, walkForwardOption } from './chartOptions'
import { decimal } from './fmt'

const num = (v: number | null) => decimal(v, 4)

/** 롤링(walk-forward) 검증: choose on the training window, judge on the window after it. */
export function WalkForwardTab({ wf }: { wf: WalkForward }) {
  const label = `${GROUP_TITLES[wf.param.split('.')[0]] ?? ''} · ${PARAM_LABELS[wf.param]?.label ?? wf.param}`
  if (wf.folds.length === 0 || !wf.summary) {
    return <Alert type="warning" showIcon message="롤링 검증을 하지 못했습니다" description={wf.reason ?? '기간이 짧습니다'} />
  }
  const s = wf.summary
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" title={`${label} · ${METRIC_LABELS[wf.metric] ?? wf.metric}`}>
        <Descriptions size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="후보 값">{wf.values.join(', ')} (기본 {wf.default})</Descriptions.Item>
          <Descriptions.Item label="창">학습 {wf.train_days}일 · 검증 {wf.test_days}일 · 이동 {wf.step_days}일, {s.folds}구간</Descriptions.Item>
          <Descriptions.Item label="학습 평균(고른 값)">{num(s.mean_train_metric)}</Descriptions.Item>
          <Descriptions.Item label="검증 평균(고른 값)">{num(s.mean_test_metric)}</Descriptions.Item>
          <Descriptions.Item label="검증 평균(기본값 그대로)">{num(s.mean_default_test_metric)}</Descriptions.Item>
          <Descriptions.Item label="고른 값 − 기본값">{num(s.test_minus_default)}</Descriptions.Item>
          <Descriptions.Item label="검증 / 학습">{decimal(s.efficiency)}</Descriptions.Item>
          <Descriptions.Item label="고른 값의 종류">{s.chosen_changes}가지 ({s.chosen_values.join(', ')})</Descriptions.Item>
        </Descriptions>
        <Typography.Text type="secondary">
          검증/학습 비율이 1보다 많이 낮으면 학습 구간에만 맞춘 것입니다. 고른 값이 구간마다 크게 바뀌면 그 파라미터는 믿을 만한 구간이 없다는 뜻입니다.
        </Typography.Text>
      </Card>
      <Card size="small" title="구간별 학습·검증 지표">
        <EChart option={walkForwardOption(wf.folds)} height={260} label="구간별 학습과 검증 지표" />
        <Table<Fold>
          size="small"
          rowKey="fold"
          dataSource={wf.folds}
          pagination={false}
          scroll={{ x: 820 }}
          columns={[
            { title: '구간', dataIndex: 'fold', width: 56 },
            { title: '학습', render: (_, f) => `${f.train[0]} ~ ${f.train[1]}` },
            { title: '검증', render: (_, f) => `${f.test[0]} ~ ${f.test[1]}` },
            { title: '고른 값', align: 'right', render: (_, f) => (f.chosen === null ? '-' : f.chosen) },
            { title: '학습 지표', align: 'right', render: (_, f) => num(f.train_metric) },
            { title: '검증 지표', align: 'right', render: (_, f) => `${num(f.test_metric)} (n=${f.test_samples})` },
            { title: '기본값 검증', align: 'right', render: (_, f) => `${num(f.default_test_metric)} (n=${f.default_test_samples})` },
          ]}
        />
      </Card>
    </Space>
  )
}
