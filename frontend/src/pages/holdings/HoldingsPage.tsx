import { PlusOutlined } from '@ant-design/icons'
import { Button, Card, Space } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAlerts, useCycles, useHoldings, useSettings } from '../../api/queries'
import type { AlertOut, HoldingOut } from '../../api/types'
import { PageHeader } from '../../components/PageHeader'
import { awaitingReentry, fillSideOf, fitsHolding, type FillSide } from '../../features/alertTargets'
import { FillModal } from './FillModal'
import { HoldingDetail } from './HoldingDetail'
import { HoldingsTable } from './HoldingsTable'
import { RegisterHoldingModal } from './RegisterHoldingModal'
import { fillDraft } from './fillDefaults'

interface FillRequest {
  side: FillSide
  alert?: AlertOut
}

/** The fill form opens once, with its starting values fixed at that moment. */
function FillDialog({
  holding,
  request,
  sellFraction,
  soldQuantity,
  onClose,
}: {
  holding: HoldingOut
  request: FillRequest
  sellFraction: number
  soldQuantity: number | null
  onClose: () => void
}) {
  const [draft] = useState(() =>
    fillDraft({ side: request.side, holding, alert: request.alert, sellFraction, soldQuantity }),
  )
  return <FillModal holding={holding} draft={draft} alert={request.alert} soldQuantity={soldQuantity} onClose={onClose} />
}

export function HoldingsPage() {
  const [params, setParams] = useSearchParams()
  const holdings = useHoldings()
  const settings = useSettings()
  const items = holdings.data ?? []

  const wanted = Number(params.get('holding'))
  const selected = items.find((h) => h.id === wanted) ?? items[0]
  const cycles = useCycles(selected?.id)
  const alerts = useAlerts({ code: selected?.code, limit: 50 })

  const [registering, setRegistering] = useState(false)
  const [manual, setManual] = useState<FillRequest | null>(null)

  // An alert link (?alert=ID) opens the fill form for that alert, if it still applies.
  const alertId = Number(params.get('alert')) || null
  const linked = alertId === null ? undefined : alerts.data?.items.find((a) => a.id === alertId)
  const linkedSide = linked ? fillSideOf(linked) : null
  const cycleList = cycles.data?.cycles ?? []
  const fromAlert: FillRequest | null =
    selected &&
    linked &&
    linkedSide &&
    linked.holding_id === selected.id &&
    fitsHolding(linkedSide, selected, { forced: linked.kind === 'force_sell', reentry: awaitingReentry(cycleList) })
      ? { side: linkedSide, alert: linked }
      : null
  const request = manual ?? fromAlert

  const select = (id: number) => setParams({ holding: String(id) }, { replace: true })
  const closeFill = () => {
    setManual(null)
    if (params.has('alert')) {
      const next = new URLSearchParams(params)
      next.delete('alert')
      setParams(next, { replace: true })
    }
  }

  const lastCycle = cycleList[cycleList.length - 1]
  const soldQuantity = selected?.open_cycle?.sell_quantity ?? (awaitingReentry(cycleList) ? (lastCycle?.sell_quantity ?? null) : null)
  const latestRebuyAlert = alerts.data?.items.find((a) => ['rebuy', 'rebuy_held', 'reduce_position'].includes(a.kind))

  const manualSide = (holding: HoldingOut): FillSide => (holding.state === 'holding' && !awaitingReentry(cycleList) ? 'sell' : 'rebuy')

  return (
    <>
      <PageHeader
        title="보유 종목"
        description="매도·재매수 알림이 오면 증권사 앱에서 직접 거래한 뒤 여기에 체결을 기록합니다. 앱은 주문하지 않습니다."
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setRegistering(true)}>
            보유 종목 등록
          </Button>
        }
      />
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Card size="small" styles={{ body: { padding: 0 } }}>
          <HoldingsTable
            holdings={items}
            selectedId={selected?.id}
            loading={holdings.isPending}
            onSelect={select}
            onRecord={(holding) => {
              select(holding.id)
              setManual({ side: manualSide(holding) })
            }}
          />
        </Card>
        {selected && (
          <HoldingDetail
            key={selected.id}
            holding={selected}
            cycles={cycles.data}
            cyclesLoading={cycles.isPending}
            latestRebuyAlert={latestRebuyAlert}
          />
        )}
      </Space>

      <RegisterHoldingModal
        open={registering}
        onClose={() => setRegistering(false)}
        onCreated={(id) => {
          setRegistering(false)
          select(id)
        }}
      />
      {selected && request && (
        <FillDialog
          key={`${selected.id}-${request.side}-${request.alert?.id ?? 'manual'}`}
          holding={selected}
          request={request}
          sellFraction={settings.data?.signal_params.sell.sell_fraction ?? 1 / 3}
          soldQuantity={soldQuantity}
          onClose={closeFill}
        />
      )}
    </>
  )
}
