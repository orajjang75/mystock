import { Alert, Card, Col, Descriptions, Row, Space, Statistic, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Direction } from '../../components/Direction'
import type { BacktestSummary, EventStats } from '../../features/backtest/result'
import { AdoptionTag } from './AdoptionTag'
import { SERIES_LABELS } from './chartOptions'
import { plainFraction, shares, signedFraction } from './fmt'

interface Row5 {
  key: string
  label: string
  stats: EventStats
}

/** 결과 요약: the headline numbers of each part and whether their samples are big enough. */
export function SummaryTab({ summary }: { summary: BacktestSummary }) {
  const quality = summary.signal_quality
  const cycle = summary.cycle
  const data = summary.data
  const rows: Row5[] = quality
    ? (['strategy', 'universe', 'random', 'kospi'] as const).map((key) => ({ key, label: SERIES_LABELS[key], stats: quality[key] }))
    : []
  const columns: ColumnsType<Row5> = [
    { title: '대상', dataIndex: 'label' },
    { title: '표본(건)', align: 'right', render: (_, r) => r.stats.n_events },
    { title: '신호일', align: 'right', render: (_, r) => r.stats.n_dates },
    { title: '평균', align: 'right', render: (_, r) => <Direction value={r.stats.mean}>{signedFraction(r.stats.mean)}</Direction> },
    { title: '중앙값', align: 'right', render: (_, r) => <Direction value={r.stats.median}>{signedFraction(r.stats.median)}</Direction> },
    { title: '승률', align: 'right', render: (_, r) => plainFraction(r.stats.win_rate) },
  ]
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {quality && (
        <Card
          size="small"
          title={`신호 품질 · 후보 선정 후 ${quality.horizon}거래일 수익률`}
          extra={<AdoptionTag adoption={quality.adoption} />}
        >
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Statistic title="일평균 후보 수" value={quality.candidates.per_day_mean} precision={2} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="후보 0건인 날" value={plainFraction(quality.candidates.zero_days_share)} suffix={`(${quality.candidates.zero_days}일)`} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="신호가 난 날" value={quality.adoption.n_dates ?? 0} suffix="일" />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="계산 엔진" value={quality.engine} />
            </Col>
          </Row>
          <Table<Row5> size="small" style={{ marginTop: 12 }} rowKey="key" dataSource={rows} columns={columns} pagination={false} />
        </Card>
      )}
      {cycle && (
        <Card size="small" title={`수량 늘리기 · ${cycle.headline.bar_length} 사이클`} extra={<AdoptionTag adoption={cycle.adoption} />}>
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Statistic title="사이클 성공률" value={plainFraction(cycle.headline.completion_rate)} suffix={`(${cycle.headline.completed}/${cycle.headline.finished})`} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="사이클당 평균 수량 증가율" value="" formatter={() => <Direction value={cycle.headline.mean_increase_rate}>{signedFraction(cycle.headline.mean_increase_rate)}</Direction>} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="누적 수량 증가" value="" formatter={() => <Direction value={cycle.headline.cumulative_increase}>{shares(cycle.headline.cumulative_increase)}</Direction>} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="최대 낙폭" value="" formatter={() => <Direction value={cycle.headline.max_drawdown}>{signedFraction(cycle.headline.max_drawdown)}</Direction>} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="수익률" value="" formatter={() => <Direction value={cycle.headline.total_return}>{signedFraction(cycle.headline.total_return)}</Direction>} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="매도 없이 보유했다면" value="" formatter={() => <Direction value={cycle.headline.hold_return}>{signedFraction(cycle.headline.hold_return)}</Direction>} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="만료" value={cycle.headline.expired} suffix="건" />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="종목 수" value={cycle.stocks} suffix="개" />
            </Col>
          </Row>
        </Card>
      )}
      {data && (
        <Card size="small" title="데이터">
          <Descriptions size="small" column={{ xs: 1, md: 2 }}>
            <Descriptions.Item label="종목">{data.stocks}개 · 거래일 {data.sessions}일</Descriptions.Item>
            <Descriptions.Item label="수정주가">
              {data.notes.adjusted_prices ? <Tag color="green">사용</Tag> : <Tag color="orange">확인 필요</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="유니버스">{data.notes.universe ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="상장폐지 종목">
              {data.notes.include_delisted === false ? (
                <Tag color="orange">제외 (생존 종목만)</Tag>
              ) : (
                <Tag color="green">포함</Tag>
              )}{' '}
              {data.delisted.length > 0 ? `${data.delisted.length}종목` : '해당 없음'}
            </Descriptions.Item>
            <Descriptions.Item label="분봉 보관 구간">
              {data.notes.intraday_span ? `${data.notes.intraday_span[0].slice(0, 10)} ~ ${data.notes.intraday_span[1].slice(0, 10)}` : '없음'}
            </Descriptions.Item>
            <Descriptions.Item label="평가 구간">
              {summary.period ? `${summary.period.start} ~ ${summary.period.end}` : '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}
      {summary.warnings && summary.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="결과를 읽을 때 주의할 점"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {summary.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          }
        />
      )}
      <Typography.Text type="secondary">
        이 화면은 결과를 보여 주기만 합니다. 6장 기본값은 실데이터 결과를 보고 직접 정하세요.
      </Typography.Text>
    </Space>
  )
}
