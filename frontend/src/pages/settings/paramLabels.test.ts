import { describe, expect, it } from 'vitest'
import { GROUP_ORDER, GROUP_TITLES, PARAM_LABELS, inDisplayOrder } from './paramLabels'
import { defaultSignalParams, signalParamGroups, signalParamLeaves } from './paramSchema'

describe('the settings form follows the backend params model', () => {
  const leaves = signalParamLeaves()

  it('has a Korean label for every field of SignalParams, and no stale ones', () => {
    const fromSchema = leaves.map((leaf) => leaf.key).sort()
    const labelled = Object.keys(PARAM_LABELS).sort()

    expect(labelled).toEqual(fromSchema)
  })

  it('titles every group', () => {
    for (const group of signalParamGroups()) expect(GROUP_TITLES[group], group).toBeTruthy()
    expect(Object.keys(GROUP_TITLES).sort()).toEqual(signalParamGroups().sort())
  })

  it('knows all nine groups of the PRD 6장 defaults, shown in this order', () => {
    expect([...signalParamGroups()].sort()).toEqual([...GROUP_ORDER].sort())
    expect(GROUP_ORDER).toEqual([
      'indicators',
      'screener',
      'score',
      'scan',
      'sell',
      'rebuy',
      'force_sell',
      'trend',
      'stop',
    ])
  })

  it('orders the fields like the label table, group by group', () => {
    const ordered = inDisplayOrder(leaves)
    const groupsSeen = ordered.map((leaf) => leaf.group).filter((g, i, all) => all.indexOf(g) === i)

    expect(groupsSeen).toEqual(GROUP_ORDER)
    expect(ordered[0].key).toBe('indicators.rsi_period')
  })

  it('labels every option of an enum field', () => {
    for (const leaf of leaves.filter((l) => l.kind === 'enum')) {
      for (const option of leaf.options) {
        expect(PARAM_LABELS[leaf.key].options?.[option], `${leaf.key}=${option}`).toBeTruthy()
      }
    }
  })

  it('only marks numeric fields as percent', () => {
    for (const leaf of leaves.filter((l) => PARAM_LABELS[l.key].percent)) {
      expect(leaf.kind).toBe('number')
    }
  })

  it('shows the fee and tax rates in their own card', () => {
    const fees = leaves.filter((leaf) => PARAM_LABELS[leaf.key].card === 'fees').map((leaf) => leaf.key)

    expect(fees).toEqual(['rebuy.round_trip_fee_rate', 'rebuy.sell_tax_rate'])
  })

  it('reads the PRD defaults from the schema', () => {
    const defaults = defaultSignalParams()

    expect(defaults.screener.drawdown_threshold_pct).toBe(-30)
    expect(defaults.screener.disparity_threshold_pct).toBe(-8)
    expect(defaults.screener.flow_consecutive_days).toBe(3)
    expect(defaults.screener.flow_strength_threshold_pct).toBe(2)
    expect(defaults.sell.atr_disparity_multiple).toBe(3)
    expect(defaults.rebuy.expiry_trading_days).toBe(5)
    expect(defaults.rebuy.target_gain).toBe(0.01)
    expect(defaults.score.reversal_points).toBe(30)
  })

  it('reads bounds from the schema', () => {
    const fee = leaves.find((leaf) => leaf.key === 'rebuy.round_trip_fee_rate')
    const rsi = leaves.find((leaf) => leaf.key === 'indicators.rsi_period')
    const fraction = leaves.find((leaf) => leaf.key === 'sell.sell_fraction')

    expect(fee?.min).toBe(0)
    expect(rsi?.min).toBe(2)
    expect(rsi?.kind).toBe('integer')
    expect(fraction?.exclusiveMin).toBe(0)
    expect(fraction?.exclusiveMax).toBe(1)
  })
})
