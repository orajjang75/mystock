import { describe, expect, it } from 'vitest'
import { closeTab, openTab, sanitizeTabs } from './tabs'

describe('openTab', () => {
  it('adds a screen once', () => {
    expect(openTab(['/'], '/screener')).toEqual(['/', '/screener'])
    const tabs = ['/', '/screener']
    expect(openTab(tabs, '/screener')).toBe(tabs)
  })

  it('ignores a path that is not a screen', () => {
    const tabs = ['/']
    expect(openTab(tabs, '/nope')).toBe(tabs)
  })
})

describe('closeTab', () => {
  const tabs = ['/', '/screener', '/alerts']

  it('closing the active tab goes to its neighbour', () => {
    expect(closeTab(tabs, '/screener', '/screener')).toEqual({ tabs: ['/', '/alerts'], next: '/alerts' })
    expect(closeTab(tabs, '/alerts', '/alerts')).toEqual({ tabs: ['/', '/screener'], next: '/screener' })
    expect(closeTab(tabs, '/', '/')).toEqual({ tabs: ['/screener', '/alerts'], next: '/screener' })
  })

  it('closing another tab keeps the active one', () => {
    expect(closeTab(tabs, '/alerts', '/')).toEqual({ tabs: ['/', '/screener'], next: '/' })
  })

  it('never closes the last tab', () => {
    expect(closeTab(['/'], '/', '/')).toEqual({ tabs: ['/'], next: '/' })
  })
})

describe('sanitizeTabs', () => {
  it('keeps known screens, drops junk and duplicates, and is never empty', () => {
    expect(sanitizeTabs(['/', '/settings', '/gone', 5, '/settings'])).toEqual(['/', '/settings'])
    expect(sanitizeTabs(null)).toEqual(['/'])
    expect(sanitizeTabs(['/gone'])).toEqual(['/'])
  })
})
