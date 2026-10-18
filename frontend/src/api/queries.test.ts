import { describe, expect, it } from 'vitest'
import { pollingInterval } from './queries'

describe('pollingInterval', () => {
  it('polls every 60 seconds until the settings are known', () => {
    expect(pollingInterval(undefined)).toBe(60_000)
  })

  it('follows the saved period', () => {
    expect(pollingInterval(60)).toBe(60_000)
    expect(pollingInterval(10)).toBe(10_000)
  })

  it('is off (manual refresh only) when the period is 0', () => {
    expect(pollingInterval(0)).toBe(false)
  })
})
