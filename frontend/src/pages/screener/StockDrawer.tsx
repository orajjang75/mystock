import { Alert, Drawer, Skeleton, Space, Tag, Typography } from 'antd'
import { useCandles, useIndicators } from '../../api/queries'
import type { ResultItem, WatchlistItem } from '../../api/types'
import { PriceChart } from '../../components/charts/PriceChart'
import { FlowBarChart } from '../../components/charts/FlowBarChart'
import { Direction } from '../../components/Direction'
import { formatPercent, formatScore } from '../../lib/format'
import { EvidencePanel } from './EvidencePanel'
import { WatchButton } from './WatchButton'

interface Props {
  code: string | null
  scanDate: string | null | undefined
  results: ResultItem[]
  watchlist: WatchlistItem[]
  onClose: () => void
}

/** 종목 상세: daily chart with indicators, evidence, and the foreign/institution flow. */
export function StockDrawer({ code, scanDate, results, watchlist, onClose }: Props) {
  const candles = useCandles(code ?? undefined)
  const indicators = useIndicators(code ?? undefined)
  const item = results.find((r) => r.code === code)
  const watched = watchlist.some((w) => w.code === code)
  const name = item?.name ?? watchlist.find((w) => w.code === code)?.name ?? code

  return (
    <Drawer
      open={Boolean(code)}
      onClose={onClose}
      width="min(960px, 100vw)"
      destroyOnHidden
      title={
        <Space wrap>
          <span>{name}</span>
          <Typography.Text type="secondary">{code}</Typography.Text>
          {item && <Tag color="purple">{formatScore(item.score)}점</Tag>}
          {item && <Direction value={item.change_pct}>{formatPercent(item.change_pct)}</Direction>}
          {code && <WatchButton code={code} watched={item?.in_watchlist ?? watched} />}
        </Space>
      }
    >
      {code && (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {candles.isError || indicators.isError ? (
            <Alert type="error" showIcon message="차트 데이터를 불러오지 못했습니다" />
          ) : candles.data && indicators.data ? (
            <PriceChart candles={candles.data} indicators={indicators.data.points} height={560} />
          ) : (
            <Skeleton active paragraph={{ rows: 10 }} />
          )}

          {item ? (
            <EvidencePanel item={item} />
          ) : (
            <Alert
              type="info"
              showIcon
              message={`${scanDate ?? '선택한'} 일자의 스캔 결과에는 없는 종목입니다`}
              description="바닥 게이트를 통과하지 못했거나 최소 점수에 못 미쳤습니다. 차트와 수급은 그대로 볼 수 있습니다."
            />
          )}

          <div>
            <Typography.Text strong>외국인·기관 순매수</Typography.Text>
            {indicators.data ? (
              indicators.data.flow.length > 0 ? (
                <FlowBarChart flow={indicators.data.flow} />
              ) : (
                <Typography.Paragraph type="secondary">수급 데이터가 없습니다.</Typography.Paragraph>
              )
            ) : (
              <Skeleton active paragraph={{ rows: 3 }} />
            )}
          </div>
        </Space>
      )}
    </Drawer>
  )
}
