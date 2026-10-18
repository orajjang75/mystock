import { Alert, Card, Col, Descriptions, Row, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { EChart } from '../../components/charts/EChart'
import { Direction } from '../../components/Direction'
import type { CycleDetail, CycleRow, CycleState } from '../../features/backtest/result'
import { formatNumber } from '../../lib/format'
import { SERIES_COLORS, lineOption } from './chartOptions'
import { decimal, plainFraction, shares, signedFraction, won } from './fmt'

const STATE: Record<CycleState, { label: string; color: string }> = {
  done: { label: '재매수 완료', color: 'green' },
  open: { label: '대기 중', color: 'gold' },
  expired: { label: '만료', color: 'orange' },
  abandoned: { label: '포기', color: 'default' },
  forced: { label: '강제 매도', color: 'purple' },
}

const when = (value: string | null) => (value ? dayjs(value).format('MM-DD HH:mm') : '-')

const columns: ColumnsType<CycleRow> = [
  { title: '종목', render: (_, r) => `${r.name}`, width: 130 },
  { title: '상태', dataIndex: 'state', render: (s: CycleState, r) => <Space size={2}><Tag color={STATE[s].color}>{STATE[s].label}</Tag>{r.expired && s !== 'expired' && <Tag color="orange">만료됨</Tag>}</Space> },
  {
    title: '매도',
    render: (_, r) => (
      <div>
        <div>
          {formatNumber(r.sell_price)} × {formatNumber(r.sell_quantity)}주
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {when(r.sold_at)}
        </Typography.Text>
      </div>
    ),
  },
  { title: '재매수 목표가', dataIndex: 'rebuy_target_price', align: 'right', render: (v: number) => formatNumber(v) },
  {
    title: '재매수',
    render: (_, r) =>
      r.rebuy_price === null ? (
        '-'
      ) : (
        <div>
          <div>
            {formatNumber(r.rebuy_price)} × {formatNumber(r.rebuy_quantity)}주
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {when(r.rebought_at)}
          </Typography.Text>
        </div>
      ),
  },
  { title: '소요', dataIndex: 'wait_sessions', align: 'right', render: (v: number | null) => (v === null ? '-' : `${v}거래일`) },
  {
    title: '수량 증가분',
    dataIndex: 'quantity_increase',
    align: 'right',
    render: (v: number | null, r) => (v === null ? '-' : <Direction value={v}><strong>{shares(v)}</strong> ({signedFraction(r.increase_rate)})</Direction>),
  },
  { title: '현금 결과', dataIndex: 'net_cash', align: 'right', render: (v: number | null) => (v === null ? '-' : <Direction value={v}>{formatNumber(Math.round(v))}</Direction>) },
  { title: '비용', dataIndex: 'costs', align: 'right', render: (v: number) => formatNumber(Math.round(v)) },
]

/** 사이클: 수량 늘리기 지표, 자산 곡선과 수량 증가 추이, 거래 목록. */
export function CycleTab({ detail }: { detail: CycleDetail }) {
  const m = detail.metrics
  const [state, setState] = useState<CycleState | 'all'>('all')
  const rows = useMemo(() => detail.cycles.filter((c) => state === 'all' || c.state === state), [detail.cycles, state])
  const curves = detail.curves
  const after = Object.entries(m.forced.after)
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" title={`사이클 지표 · ${m.bar_length} · ${detail.period.start} ~ ${detail.period.end}`}>
        <Descriptions size="small" column={{ xs: 1, md: 2, xl: 3 }}>
          <Descriptions.Item label="종목 / 매도">{m.stocks}개 / {m.sells}건 (끝난 {m.finished}, 대기 중 {m.open_at_end})</Descriptions.Item>
          <Descriptions.Item label="사이클 성공률">{plainFraction(m.completion_rate)} ({m.completed}/{m.finished})</Descriptions.Item>
          <Descriptions.Item label="수량이 늘어난 비율">{plainFraction(m.gain_rate)}</Descriptions.Item>
          <Descriptions.Item label="사이클당 수량 증가율">평균 {signedFraction(m.increase_rate.mean)} · 중앙값 {signedFraction(m.increase_rate.median)}</Descriptions.Item>
          <Descriptions.Item label="누적 수량 증가"><Direction value={m.cumulative_increase}>{shares(m.cumulative_increase)}</Direction> (시작 수량 대비 {decimal(m.cumulative_increase_pct)}%)</Descriptions.Item>
          <Descriptions.Item label="평균 재매수 소요">{decimal(m.wait_sessions.mean)}거래일 (중앙값 {decimal(m.wait_sessions.median)})</Descriptions.Item>
          <Descriptions.Item label="만료">{m.expired}건 ({plainFraction(m.expired_share)})</Descriptions.Item>
          <Descriptions.Item label="만료 건의 기회손실">평균 {decimal(m.missed_pct.mean)}% 상승을 놓침 · 합계 {won(m.missed_value)}</Descriptions.Item>
          <Descriptions.Item label="강제 매도(5일선 이탈)">{m.forced.count}회 ({m.forced.stocks}종목)</Descriptions.Item>
          <Descriptions.Item label="수익률 / 보유 대비">
            <Direction value={m.total_return}>{signedFraction(m.total_return)}</Direction> / <Direction value={m.excess_return}>{signedFraction(m.excess_return)}</Direction>
          </Descriptions.Item>
          <Descriptions.Item label="최대 낙폭">{signedFraction(m.max_drawdown)} (보유 {signedFraction(m.hold_max_drawdown)})</Descriptions.Item>
          <Descriptions.Item label="수수료·거래세">{won(m.costs)}</Descriptions.Item>
        </Descriptions>
        {detail.notes.skipped.length > 0 && (
          <Alert style={{ marginTop: 8 }} type="info" showIcon message={`분봉이나 시세가 모자라 건너뛴 종목 ${detail.notes.skipped.length}개: ${detail.notes.skipped.join(', ')}`} />
        )}
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card size="small" title="자산 곡선 (시작 = 100)">
            <EChart
              option={lineOption(curves.times.map((t) => dayjs(t).format('MM-DD HH:mm')), [
                { name: '사이클 전략', values: curves.strategy, color: SERIES_COLORS.strategy },
                { name: '매도 없이 보유', values: curves.hold, color: SERIES_COLORS.hold, dashed: true },
              ])}
              height={280}
              label="사이클 전략과 보유의 자산 곡선"
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card size="small" title="수량 증가 추이 (시작 수량 대비 %)">
            <EChart
              option={lineOption(
                curves.times.map((t) => dayjs(t).format('MM-DD HH:mm')),
                [{ name: '수량 증가', values: curves.quantity_gain_pct, color: SERIES_COLORS.strategy }],
                { unit: '%' },
              )}
              height={280}
              label="시작 수량 대비 수량 증가 추이"
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card size="small" title="슬리피지를 올려도 수량 증가가 유지되는가">
            <Table
              size="small"
              rowKey="slippage"
              pagination={false}
              dataSource={detail.slippage}
              columns={[
                { title: '슬리피지', align: 'right', render: (_, r) => plainFraction(r.slippage, 2) },
                { title: '끝난 매도', dataIndex: 'finished', align: 'right' },
                { title: '성공률', align: 'right', render: (_, r) => plainFraction(r.completion_rate) },
                { title: '평균 증가율', align: 'right', render: (_, r) => signedFraction(r.mean_increase_rate) },
                { title: '누적 증가', align: 'right', render: (_, r) => <Direction value={r.cumulative_increase}>{shares(r.cumulative_increase)}</Direction> },
                { title: '수익률', align: 'right', render: (_, r) => signedFraction(r.total_return) },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card size="small" title="강제 매도 이후 (매도가 대비)">
            <Table
              size="small"
              rowKey="horizon"
              pagination={false}
              dataSource={after.map(([horizon, v]) => ({ horizon, ...v }))}
              locale={{ emptyText: '강제 매도가 없었습니다' }}
              columns={[
                { title: '이후', render: (_, r) => `${r.horizon}거래일` },
                { title: '표본', dataIndex: 'n', align: 'right' },
                { title: '평균', align: 'right', render: (_, r) => signedFraction(r.mean) },
                { title: '중앙값', align: 'right', render: (_, r) => signedFraction(r.median) },
              ]}
            />
            <Typography.Text type="secondary">
              강제 매도 뒤에 오르는 일이 잦다면 휩쏘로 비용만 쌓였다는 뜻입니다 (PRD 10장 리스크 표).
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        title={`거래 목록 (${rows.length}건)`}
        extra={
          <Select
            aria-label="상태 필터"
            value={state}
            onChange={setState}
            style={{ width: 160 }}
            options={[{ value: 'all', label: '전체 상태' }, ...(Object.keys(STATE) as CycleState[]).map((s) => ({ value: s, label: STATE[s].label }))]}
          />
        }
      >
        <Table<CycleRow>
          size="small"
          rowKey={(r) => `${r.code}-${r.sold_at}`}
          dataSource={rows}
          columns={columns}
          pagination={{ pageSize: 15, size: 'small', hideOnSinglePage: true }}
          scroll={{ x: 980 }}
          locale={{ emptyText: '이 조건의 거래가 없습니다' }}
        />
      </Card>
    </Space>
  )
}
