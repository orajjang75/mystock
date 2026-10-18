import { describe, expect, it } from 'vitest'
import { makeAlert, makeHolding } from '../../test/fixtures'
import { fillDraft } from './fillDefaults'

const holding = makeHolding(1, { quantity: 300, last_close: 50_000 })

describe('fillDraft', () => {
  it('starts from the alert, so only the confirmation is left', () => {
    const alert = makeAlert(1, { kind: 'sell', suggested_quantity: 100, price: 291_546 })

    expect(fillDraft({ side: 'sell', holding, alert, sellFraction: 1 / 3, soldQuantity: null })).toEqual({
      side: 'sell',
      forced: false,
      price: 291_546,
      quantity: 100,
    })
  })

  it('marks a forced sale from its alert', () => {
    const alert = makeAlert(1, { kind: 'force_sell', suggested_quantity: 300, price: 40_000 })

    expect(fillDraft({ side: 'sell', holding, alert, sellFraction: 1 / 3, soldQuantity: null }).forced).toBe(true)
  })

  it('suggests a third of the position and the last close when filling in by hand', () => {
    expect(fillDraft({ side: 'sell', holding, sellFraction: 1 / 3, soldQuantity: null })).toEqual({
      side: 'sell',
      forced: false,
      price: 50_000,
      quantity: 100,
    })
  })

  it('never suggests selling everything, and nothing for a single share', () => {
    expect(fillDraft({ side: 'sell', holding: makeHolding(1, { quantity: 2 }), sellFraction: 0.9, soldQuantity: null }).quantity).toBe(1)
    expect(fillDraft({ side: 'sell', holding: makeHolding(1, { quantity: 1 }), sellFraction: 1 / 3, soldQuantity: null }).quantity).toBeNull()
  })

  it('suggests buying back the sold quantity by hand', () => {
    expect(fillDraft({ side: 'rebuy', holding, sellFraction: 1 / 3, soldQuantity: 100 })).toMatchObject({ side: 'rebuy', quantity: 100, price: 50_000 })
  })
})
