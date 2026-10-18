import { Alert, Card, Col, Descriptions, Row, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EChart } from '../../components/charts/EChart'
import { Direction } from '../../components/Direction'
import type { EventStats, QualityDetail, QualityEvent, Ratios, SeriesKey } from '../../features/backtest/result'
import { formatNumber } from '../../lib/format'
import { AdoptionTag } from './AdoptionTag'
import { SERIES_COLORS, SERIES_LABELS, horizonOption, lineOption } from './chartOptions'
import { decimal, plainFraction, signedFraction } from './fmt'

const KEYS: SeriesKey[] = ['strategy', 'universe', 'random', 'kospi']
const REGIME_LABEL = { up: '상승', down: '하락', flat: '횡보' } as const

interface HorizonRow {
  key: string
  horizon: string
  series: string
  stats: EventStats
}

function statColumns(): ColumnsType<HorizonRow> {
  return [
    { title: '기간', dataIndex: 'horizon', width: 64 },
    { title: '대상', dataIndex: 'series' },
    { title: '표본(건)', align: 'right', render: (_, r) => formatNumber(r.stats.n_events) },
    { title: '신호일', align: 'right', render: (_, r) => formatNumber(r.stats.n_dates) },
    { title: '평균', align: 'right', render: (_, r) => <Direction value={r.stats.mean}>{signedFraction(r.stats.mean)}</Direction> },
    { title: '중앙값', align: 'right', render: (_, r) => <Direction value={r.stats.median}>{signedFraction(r.stats.median)}</Direction> },
    { title: '승률', align: 'right', render: (_, r) => plainFraction(r.stats.win_rate) },
    { title: '손익비', align: 'right', render: (_, r) => decimal(r.stats.payoff_ratio) },
    { title: 'PF', align: 'right', render: (_, r) => decimal(r.stats.profit_factor) },
    { title: '10~90%', align: 'right', render: (_, r) => (r.stats.p10 === undefined ? '-' : `${signedFraction(r.stats.p10, 1)} ~ ${signedFraction(r.stats.p90, 1)}`) },
  ]
}

function ratioRows(detail: QualityDetail) {
  const p = detail.portfolios
  const rows: { key: string; label: string; ratios: Ratios }[] = [
    { key: 'strategy', label: '후보', ratios: p.strategy },
    { key: 'universe', label: '유니버스 단순 보유', ratios: p.universe },
    { key: 'kospi', label: 'KOSPI', ratios: p.kospi },
    { key: 'random', label: `무작위 진입 (${p.random.trials}회 평균)`, ratios: p.random.mean },
  ]
  return rows
}

/** 신호 품질: 후보 선정 후 수익률 분포와 비교 대상, 위험 지표, 시장 국면, 슬리피지. */
export function QualityTab({ detail }: { detail: QualityDetail }) {
  const horizons = Object.keys(detail.horizons).sort((a, b) => Number(a) - Number(b))
  const rows: HorizonRow[] = horizons.flatMap((h) =>
    KEYS.map((k) => ({ key: `${h}-${k}`, horizon: `${h}일`, series: SERIES_LABELS[k], stats: detail.horizons[h][k] })),
  )
  const curves = detail.curves
  const events = detail.events
  const regimeRows = (['up', 'down', 'flat'] as const).map((r) => ({ key: r, regime: REGIME_LABEL[r], ...detail.regimes[r] }))
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" title="후보 선정과 체결 가정" extra={<AdoptionTag adoption={detail.adoption} />}>
        <Descriptions size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="평가 구간">{detail.period.start} ~ {detail.period.end} ({detail.period.sessions}거래일)</Descriptions.Item>
          <Descriptions.Item label="체결">신호 다음 거래일 시가 진입 → 보유 기간 뒤 시가 청산</Descriptions.Item>
          <Descriptions.Item label="한쪽 수수료">{plainFraction(detail.costs.fee_per_side, 3)} (거래세 절반 포함)</Descriptions.Item>
          <Descriptions.Item label="기준 슬리피지">{plainFraction(detail.costs.base_slippage, 2)}</Descriptions.Item>
          <Descriptions.Item label="일평균 후보">{decimal(detail.candidates.per_day_mean)}개 (중앙값 {decimal(detail.candidates.per_day_median, 0)})</Descriptions.Item>
          <Descriptions.Item label="후보 0건인 날">{detail.candidates.zero_days}일 ({plainFraction(detail.candidates.zero_days_share)})</Descriptions.Item>
          <Descriptions.Item label="게이트 방식">
            {Object.entries(detail.candidates.gate_modes).map(([mode, n]) => (
              <Tag key={mode}>{mode} {n}일</Tag>
            ))}
          </Descriptions.Item>
          <Descriptions.Item label="계산 엔진">{detail.engine}</Descriptions.Item>
        </Descriptions>
        {!detail.adoption.adoptable && <Alert style={{ marginTop: 8 }} type="warning" showIcon message={detail.adoption.reasons.join(' / ')} />}
      </Card>

      <Card size="small" title="보유 기간별 수익률 (비용 반영)">
        <EChart option={horizonOption(detail.horizons)} height={260} label="보유 기간별 수익률 중앙값" />
        <Table<HorizonRow> size="small" rowKey="key" dataSource={rows} columns={statColumns()} pagination={false} scroll={{ x: 800 }} />
      </Card>

      <Card size="small" title={`같은 기간 자산 곡선 (보유 ${detail.portfolios.horizon}일, 노출 ${plainFraction(detail.portfolios.exposure)})`}>
        <EChart
          option={lineOption(
            curves.dates,
            KEYS.map((k) => ({ name: SERIES_LABELS[k], values: curves[k], color: SERIES_COLORS[k] })),
          )}
          height={300}
          label="후보와 비교 대상의 자산 곡선"
        />
        <Table
          size="small"
          rowKey="key"
          pagination={false}
          dataSource={ratioRows(detail)}
          scroll={{ x: 700 }}
          columns={[
            { title: '대상', dataIndex: 'label' },
            { title: '총수익', align: 'right', render: (_, r) => <Direction value={r.ratios.total_return}>{signedFraction(r.ratios.total_return)}</Direction> },
            { title: '연환산', align: 'right', render: (_, r) => signedFraction(r.ratios.annualized_return) },
            { title: 'Sharpe', align: 'right', render: (_, r) => decimal(r.ratios.sharpe) },
            { title: 'Sortino', align: 'right', render: (_, r) => decimal(r.ratios.sortino) },
            { title: 'Calmar', align: 'right', render: (_, r) => decimal(r.ratios.calmar) },
            { title: '최대 낙폭', align: 'right', render: (_, r) => signedFraction(r.ratios.max_drawdown) },
          ]}
        />
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card size="small" title="시장 국면별 (KOSPI 기준)">
            <Table
              size="small"
              rowKey="key"
              pagination={false}
              dataSource={regimeRows}
              columns={[
                { title: '국면', dataIndex: 'regime' },
                { title: '일수', dataIndex: 'days', align: 'right' },
                { title: '후보 표본', align: 'right', render: (_, r) => r.strategy.n_events },
                { title: '후보 평균', align: 'right', render: (_, r) => signedFraction(r.strategy.mean) },
                { title: '후보 중앙값', align: 'right', render: (_, r) => signedFraction(r.strategy.median) },
                { title: '유니버스 평균', align: 'right', render: (_, r) => signedFraction(r.universe.mean) },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card size="small" title="슬리피지를 올려도 우위가 남는가">
            <Table
              size="small"
              rowKey="slippage"
              pagination={false}
              dataSource={detail.slippage}
              columns={[
                { title: '슬리피지', align: 'right', render: (_, r) => plainFraction(r.slippage, 2) },
                { title: '후보 평균', align: 'right', render: (_, r) => signedFraction(r.mean) },
                { title: '후보 중앙값', align: 'right', render: (_, r) => signedFraction(r.median) },
                { title: '승률', align: 'right', render: (_, r) => plainFraction(r.win_rate) },
                { title: '유니버스 평균', align: 'right', render: (_, r) => signedFraction(r.universe_mean) },
                { title: '차이', align: 'right', render: (_, r) => <Direction value={r.edge}>{signedFraction(r.edge)}</Direction> },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card size="small" title={`후보 이벤트 목록 (최근 ${events.length}건, 기준 ${detail.primary_horizon}일)`}>
        <Table<QualityEvent>
          size="small"
          rowKey={(e) => `${e.signal_date}-${e.code}`}
          dataSource={events}
          pagination={{ pageSize: 10, size: 'small', hideOnSinglePage: true }}
          scroll={{ x: 760 }}
          columns={[
            { title: '신호일', dataIndex: 'signal_date' },
            { title: '종목', render: (_, e) => `${e.name} (${e.code})` },
            { title: '점수', dataIndex: 'score', align: 'right', render: (v: number) => v.toFixed(1) },
            { title: '진입(시가)', align: 'right', render: (_, e) => `${e.entry_date.slice(5)} ${formatNumber(e.entry_price)}` },
            { title: '청산(시가)', align: 'right', render: (_, e) => `${e.exit_date.slice(5)} ${formatNumber(e.exit_price)}` },
            { title: '수익률', align: 'right', render: (_, e) => <Direction value={e.return}>{signedFraction(e.return)}</Direction> },
          ]}
          locale={{ emptyText: '이 구간에는 후보가 없었습니다' }}
        />
        <Typography.Text type="secondary">진입가는 신호가 난 날의 다음 거래일 시가입니다. 신호 당일 종가로는 체결하지 않습니다.</Typography.Text>
      </Card>
    </Space>
  )
}
