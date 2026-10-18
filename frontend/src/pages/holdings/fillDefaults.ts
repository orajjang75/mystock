import type { AlertOut, HoldingOut } from '../../api/types'
import type { FillSide } from '../../features/alertTargets'

export interface FillDraft {
  side: FillSide
  price: number | null
  quantity: number | null
  forced: boolean
}

/**
 * What the fill form starts with. From an alert it is the alert's suggested quantity and price,
 * so that only the confirm click is left; by hand it is the latest close and the usual
 * third of the position (A-3), or the sold quantity as the break-even rebuy.
 */
export function fillDraft(opts: {
  side: FillSide
  holding: HoldingOut
  alert?: AlertOut
  sellFraction: number
  soldQuantity: number | null
}): FillDraft {
  const { side, holding, alert, sellFraction, soldQuantity } = opts
  const forced = alert?.kind === 'force_sell'
  if (alert && (alert.suggested_quantity || alert.price)) {
    return { side, forced, price: alert.price, quantity: alert.suggested_quantity }
  }
  const price = holding.last_close
  if (side === 'sell') {
    const third = Math.min(Math.max(1, Math.floor(holding.quantity * sellFraction)), holding.quantity - 1)
    return { side, forced, price, quantity: holding.quantity >= 2 ? third : null }
  }
  return { side, forced, price, quantity: soldQuantity }
}
