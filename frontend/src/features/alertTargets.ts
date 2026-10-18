import type { AlertOut, CycleOut, HoldingOut } from '../api/types'

export type FillSide = 'sell' | 'rebuy'

/** The alerts that ask the user to trade at the broker and then record the fill here. */
export function fillSideOf(alert: Pick<AlertOut, 'kind'>): FillSide | null {
  if (alert.kind === 'sell' || alert.kind === 'force_sell') return 'sell'
  if (alert.kind === 'rebuy') return 'rebuy'
  return null
}

// Every alert about one holding opens that holding's screen.
const HOLDING_KINDS = new Set(['sell', 'rebuy', 'rebuy_held', 'reduce_position', 'stop_loss', 'force_sell', 'expired'])

export function holdingPath(holdingId: number, alertId?: number): string {
  const params = new URLSearchParams({ holding: String(holdingId) })
  if (alertId !== undefined) params.set('alert', String(alertId))
  return `/holdings?${params.toString()}`
}

/**
 * Where a click on an alert goes. A sell or rebuy alert lands on its holding with the fill form
 * already open (``alert`` in the URL); the others just show the holding; the rest the alerts list.
 */
export function alertPath(alert: Pick<AlertOut, 'id' | 'kind' | 'holding_id'>): string {
  if (alert.holding_id === null || !HOLDING_KINDS.has(alert.kind)) return '/alerts'
  return holdingPath(alert.holding_id, fillSideOf(alert) ? alert.id : undefined)
}

/** A cycle ended by a forced sale and not bought back yet: the next rebuy is a re-entry. */
export function awaitingReentry(cycles: CycleOut[]): boolean {
  const latest = cycles[cycles.length - 1]
  return latest !== undefined && latest.state === 'force_closed' && latest.rebuy_quantity === null
}

/** Whether recording ``side`` still fits the holding (an alert link may be stale). */
export function fitsHolding(side: FillSide, holding: Pick<HoldingOut, 'state'>, opts: { forced: boolean; reentry: boolean }): boolean {
  if (side === 'sell') return opts.forced || holding.state === 'holding'
  return holding.state !== 'holding' || opts.reentry
}
