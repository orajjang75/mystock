import { Card, Col, Row, Statistic } from 'antd'
import type { TotalsOut } from '../../api/types'
import { Direction } from '../../components/Direction'

/** 수량 증가분 누적: the number this whole strategy is judged by (A-9). */
export function IncreaseCard({ totals }: { totals: TotalsOut | undefined }) {
  const increase = totals?.cumulative_increase ?? 0
  return (
    <Card size="small" title="수량 증가분 누적" aria-label="수량 증가분 누적">
      <Statistic
        title="시작 수량 대비 늘어난 주식 수"
        value={increase}
        prefix={increase > 0 ? '+' : ''}
        suffix="주"
        formatter={(value) => <Direction value={increase}>{String(value)}</Direction>}
        valueStyle={{ fontSize: 30 }}
      />
      <Row gutter={[16, 8]} style={{ marginTop: 12 }}>
        <Col span={12}>
          <Statistic title="시작 수량" value={totals?.start_quantity ?? '-'} valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={12}>
          <Statistic title="현재 수량" value={totals?.current_quantity ?? '-'} valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={12}>
          <Statistic
            title="재매수 완료 / 성공"
            value={`${totals?.completed ?? 0} / ${totals?.successful ?? 0}`}
            valueStyle={{ fontSize: 16 }}
          />
        </Col>
        <Col span={12}>
          <Statistic
            title="재매수 대기 · 미회수"
            value={`${totals?.pending_quantity ?? 0} · ${totals?.unrecovered_quantity ?? 0}`}
            suffix="주"
            valueStyle={{ fontSize: 16 }}
          />
        </Col>
      </Row>
    </Card>
  )
}
