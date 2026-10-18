import { PlayCircleOutlined } from '@ant-design/icons'
import { App as AntdApp, Alert, Button, Card, Empty, Segmented, Select, Space, Typography } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { errorMessage } from '../../api/client'
import { useResults, useRunScan, useSettings, useWatchlist } from '../../api/queries'
import { PageHeader } from '../../components/PageHeader'
import { ConditionBar } from './ConditionBar'
import { ResultsTable } from './ResultsTable'
import { StockDrawer } from './StockDrawer'
import { WatchlistTable } from './WatchlistTable'

type View = 'results' | 'watchlist'

export function ScreenerPage() {
  const { message } = AntdApp.useApp()
  const [params, setParams] = useSearchParams()
  const view: View = params.get('view') === 'watchlist' ? 'watchlist' : 'results'
  const stock = params.get('stock')
  const [date, setDate] = useState<string | undefined>()

  const settings = useSettings()
  const results = useResults({ scan_date: date })
  const watchlist = useWatchlist()
  const run = useRunScan()

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  const onRun = () =>
    run.mutate(date ? { scan_date: date } : {}, {
      onSuccess: (summary) => {
        setDate(summary.scan_date)
        void message.success(
          `스캔 완료: ${summary.universe_size}종목 중 ${summary.gated}개가 게이트를 통과했고 ${summary.saved}개를 저장했습니다 (${summary.elapsed_seconds.toFixed(1)}초)`,
        )
      },
      onError: (e) => void message.error(errorMessage(e)),
    })

  const data = results.data
  const dates = data?.scan_dates ?? []
  const watchItems = watchlist.data ?? []

  return (
    <>
      <PageHeader
        title="스크리너"
        description="바닥을 다지고 반등하는 후보를 점수순으로 보여 줍니다. 신호는 참고 정보이며 주문은 하지 않습니다."
      />
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Space wrap className="screener-toolbar">
          <Segmented<View>
            value={view}
            onChange={(next) => update({ view: next === 'watchlist' ? 'watchlist' : null })}
            options={[
              { value: 'results', label: '전체 결과' },
              { value: 'watchlist', label: `관심종목 ${watchItems.length}` },
            ]}
          />
          {view === 'results' && (
            <Select
              style={{ width: 160 }}
              aria-label="스캔 일자"
              placeholder="스캔 일자"
              disabled={dates.length === 0}
              value={date ?? data?.scan_date ?? undefined}
              onChange={setDate}
              options={dates.map((d) => ({ value: d, label: dayjs(d).format('YYYY-MM-DD (dd)') }))}
            />
          )}
          <Button type="primary" icon={<PlayCircleOutlined />} loading={run.isPending} onClick={onRun}>
            {date && date !== dates[0] ? '이 날짜로 스캔 실행' : '스캔 실행'}
          </Button>
          <Typography.Text type="secondary">보관된 시세로 지금 다시 계산합니다.</Typography.Text>
        </Space>

        <ConditionBar settings={settings.data} results={data} />

        {results.isError && <Alert type="error" showIcon message="스캔 결과를 불러오지 못했습니다" description={errorMessage(results.error)} />}

        <Card styles={{ body: { padding: 0 } }}>
          {view === 'results' ? (
            data && data.scan_date === null ? (
              <Empty
                style={{ padding: 48 }}
                description="아직 스캔한 결과가 없습니다. 스캔을 실행해 보세요."
              />
            ) : (
              <ResultsTable
                items={data?.items ?? []}
                loading={results.isPending}
                onOpen={(code) => update({ stock: code })}
              />
            )
          ) : (
            <WatchlistTable items={watchItems} loading={watchlist.isPending} onOpen={(code) => update({ stock: code })} />
          )}
        </Card>
      </Space>

      <StockDrawer
        code={stock}
        scanDate={data?.scan_date}
        results={data?.items ?? []}
        watchlist={watchItems}
        onClose={() => update({ stock: null })}
      />
    </>
  )
}
