import { describe, expect, it } from 'vitest'
import { makeAlert, makeCycle, makeHolding } from '../test/fixtures'
import { alertPath, awaitingReentry, fillSideOf, fitsHolding, holdingPath } from './alertTargets'

describe('fillSideOf', () => {
  it('knows which alerts ask for a fill to be recorded', () => {
    expect(fillSideOf({ kind: 'sell' })).toBe('sell')
    expect(fillSideOf({ kind: 'force_sell' })).toBe('sell')
    expect(fillSideOf({ kind: 'rebuy' })).toBe('rebuy')
    for (const kind of ['rebuy_held', 'reduce_position', 'stop_loss', 'expired', 'data_stale']) {
      expect(fillSideOf({ kind })).toBeNull()
    }
  })
})

describe('alertPath', () => {
  it('opens the holding with the alert for the alerts that are acted on at the broker', () => {
    expect(alertPath(makeAlert(7, { kind: 'sell', holding_id: 3 }))).toBe('/holdings?holding=3&alert=7')
    expect(alertPath(makeAlert(8, { kind: 'rebuy', holding_id: 3 }))).toBe('/holdings?holding=3&alert=8')
    expect(alertPath(makeAlert(9, { kind: 'force_sell', holding_id: 3 }))).toBe('/holdings?holding=3&alert=9')
  })

  it('opens just the holding for warnings and the expiry choice', () => {
    for (const kind of ['rebuy_held', 'reduce_position', 'stop_loss', 'expired']) {
      expect(alertPath(makeAlert(1, { kind, holding_id: 3 }))).toBe('/holdings?holding=3')
    }
  })

  it('falls back to the alerts screen when there is no holding or it is not about one', () => {
    expect(alertPath(makeAlert(1, { kind: 'sell', holding_id: null }))).toBe('/alerts')
    expect(alertPath(makeAlert(1, { kind: 'data_stale', holding_id: 3 }))).toBe('/alerts')
  })

  it('builds the holding link', () => {
    expect(holdingPath(5)).toBe('/holdings?holding=5')
    expect(holdingPath(5, 12)).toBe('/holdings?holding=5&alert=12')
  })
})

describe('awaitingReentry', () => {
  it('is true only after a forced sale that was not bought back', () => {
    expect(awaitingReentry([])).toBe(false)
    expect(awaitingReentry([makeCycle(1, { state: 'force_closed', rebuy_quantity: null })])).toBe(true)
    expect(awaitingReentry([makeCycle(1, { state: 'force_closed', rebuy_quantity: 90 })])).toBe(false)
    expect(awaitingReentry([makeCycle(1, { state: 'force_closed' }), makeCycle(2, { state: 'rebuy_wait' })])).toBe(false)
  })
})

describe('fitsHolding', () => {
  const holding = (state: 'holding' | 'rebuy_wait' | 'expired') => makeHolding(1, { state })

  it('lets a sale through only from the plain holding state, a forced one from any', () => {
    expect(fitsHolding('sell', holding('holding'), { forced: false, reentry: false })).toBe(true)
    expect(fitsHolding('sell', holding('rebuy_wait'), { forced: false, reentry: false })).toBe(false)
    expect(fitsHolding('sell', holding('expired'), { forced: false, reentry: false })).toBe(false)
    expect(fitsHolding('sell', holding('rebuy_wait'), { forced: true, reentry: false })).toBe(true)
  })

  it('lets a rebuy through while waiting or expired, or when re-entering after a forced sale', () => {
    expect(fitsHolding('rebuy', holding('rebuy_wait'), { forced: false, reentry: false })).toBe(true)
    expect(fitsHolding('rebuy', holding('expired'), { forced: false, reentry: false })).toBe(true)
    expect(fitsHolding('rebuy', holding('holding'), { forced: false, reentry: false })).toBe(false)
    expect(fitsHolding('rebuy', holding('holding'), { forced: false, reentry: true })).toBe(true)
  })
})
