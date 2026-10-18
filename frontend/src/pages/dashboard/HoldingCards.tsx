import { Card, Col, Empty, Row, Space, Statistic, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { useHoldings, useSparklines } from '../../api/queries'
import { Sparkline } from '../../components/charts/Sparkline'
import { Direction } from '../../components/Direction'
import { holdingPath } from '../../features/alertTargets'
import { formatNumber, formatPercent } from '../../lib/format'
import { HoldingStateTag } from '../holdings/holdingState'

/** 보유 종목 상태 카드. */
export function HoldingCards() {
  const holdings = useHoldings()
  const items = holdings.data ?? []
  const sparks = useSparklines(items.map((h) => h.code))

  return (
    <Card title="보유 종목 상태" extra={<Typography.Text type="secondary">{items.length}종목</Typography.Text>} loading={holdings.isPending} size="small">
      {items.length === 0 ? (
        <Empty description="등록한 보유 종목이 없습니다. 보유 종목 화면에서 등록하세요." image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Row gutter={[12, 12]}>
          {items.map((holding, index) => {
            const gain = holding.last_close === null ? null : (holding.last_close / holding.avg_price - 1) * 100
            return (
              <Col xs={24} md={12} xl={8} key={holding.id}>
                <Card size="small" type="inner" aria-label={`${holding.name} 보유 상태`}>
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Space wrap size={6}>
                      <Link to={holdingPath(holding.id)}>
                        <Typography.Text strong>{holding.name}</Typography.Text>
                      </Link>
                      <HoldingStateTag state={holding.state} />
                      {holding.daily_downtrend && <Tag color="orange">일봉 하락 추세</Tag>}
                    </Space>
                    <Space size="large" wrap>
                      <Statistic title="수량" value={holding.quantity} suffix={`/ 시작 ${holding.start_quantity}`} valueStyle={{ fontSize: 16 }} />
                      <Statistic
                        title="평균단가 대비"
                        value={gain === null ? '-' : formatPercent(gain)}
                        valueStyle={{ fontSize: 16 }}
                        formatter={(value) => <Direction value={gain}>{String(value)}</Direction>}
                      />
                    </Space>
                    <Space size="middle" wrap>
                      <Typography.Text type="secondary">현재가 {formatNumber(holding.last_close)}</Typography.Text>
                      {holding.stop_price !== null && (
                        <Typography.Text type="secondary">손절선 {formatNumber(holding.stop_price)}</Typography.Text>
                      )}
                      {holding.cumulative_increase !== 0 && (
                        <Direction value={holding.cumulative_increase}>누적 수량 {holding.cumulative_increase > 0 ? '+' : ''}{holding.cumulative_increase}</Direction>
                      )}
                    </Space>
                    <Sparkline values={(sparks[index]?.data ?? []).map((c) => c.close)} width="100%" height={36} />
                  </Space>
                </Card>
              </Col>
            )
          })}
        </Row>
      )}
    </Card>
  )
}
