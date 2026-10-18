import { Alert, Card, Col, Row, Segmented, Skeleton, Space, Typography } from 'antd'
import { useState } from 'react'
import { useCandles, useIndicators, useSettings } from '../../api/queries'
import type { AlertOut, BarLength, CyclesResponse, HoldingOut } from '../../api/types'
import { PriceChart } from '../../components/charts/PriceChart'
import { CycleTable } from './CycleTable'
import { ExpiredActions } from './ExpiredActions'
import { IncreaseCard } from './IncreaseCard'
import { cycleMarkers, holdingPriceLines } from './chartLayers'

const BAR_OPTIONS: { value: BarLength; label: string }[] = [
  { value: '30m', label: '30분' },
  { value: '60m', label: '60분' },
  { value: '1d', label: '일봉' },
]
const BARS_SHOWN: Record<BarLength, number> = { '30m': 260, '60m': 200, '1d': 250 }

interface Props {
  holding: HoldingOut
  cycles: CyclesResponse | undefined
  cyclesLoading: boolean
  /** The newest rebuy-related alert of this holding, if any. */
  latestRebuyAlert: AlertOut | undefined
}

/** The selected holding: chart with fills and lines, the expiry choice, cycles and the total. */
export function HoldingDetail({ holding, cycles, cyclesLoading, latestRebuyAlert }: Props) {
  const settings = useSettings()
  const [picked, setPicked] = useState<BarLength | null>(null)
  const bar = picked ?? settings.data?.signal_bar_length ?? '60m'
  const candles = useCandles(holding.code, bar, BARS_SHOWN[bar])
  const indicators = useIndicators(holding.code, bar, BARS_SHOWN[bar])

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {holding.state === 'expired' && holding.open_cycle && (
        <ExpiredActions
          holdingId={holding.id}
          name={holding.name}
          cycleId={holding.open_cycle.id}
          rebuyTargetPrice={holding.open_cycle.rebuy_target_price}
          expiresAt={holding.open_cycle.expires_at}
        />
      )}
      {latestRebuyAlert?.kind === 'rebuy_held' && (
        <Alert
          type="warning"
          showIcon
          message="일봉 수급 이탈로 보류됨"
          description="재매수 조건은 맞았지만 외국인·기관의 일봉 수급이 빠져나가는 중이라 재매수 알림을 보류했습니다. 수급이 돌아오면 다시 알립니다."
        />
      )}
      <Card
        size="small"
        title={`${holding.name} 차트`}
        extra={
          <Segmented<BarLength>
            aria-label="봉 길이"
            value={bar}
            onChange={setPicked}
            options={BAR_OPTIONS}
          />
        }
      >
        {candles.isError || indicators.isError ? (
          <Alert type="error" showIcon message="차트 데이터를 불러오지 못했습니다" />
        ) : candles.data && indicators.data ? (
          <>
            <PriceChart
              candles={candles.data}
              indicators={indicators.data.points}
              markers={cycleMarkers(cycles?.cycles ?? [], candles.data)}
              priceLines={holdingPriceLines(holding)}
              height={560}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              ▼ 매도 · ▲ 재매수 체결 위치 · 보라 점선은 재매수 목표가, 주황 점선은 ATR 손절선
            </Typography.Text>
          </>
        ) : (
          <Skeleton active paragraph={{ rows: 10 }} />
        )}
      </Card>
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={16}>
          <Card size="small" title="사이클 이력">
            <CycleTable cycles={cycles?.cycles ?? []} loading={cyclesLoading} />
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <IncreaseCard totals={cycles?.totals} />
        </Col>
      </Row>
    </Space>
  )
}
