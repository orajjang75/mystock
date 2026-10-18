import { describe, expect, it } from 'vitest'
import { makeAlert } from '../test/fixtures'
import { describeAlert, detectNewAlerts } from './newAlerts'

describe('detectNewAlerts', () => {
  it('does not treat the existing alerts as new on the first visit', () => {
    const result = detectNewAlerts([makeAlert(3), makeAlert(7)], null)

    expect(result.fresh).toEqual([])
    expect(result.nextSeen).toBe(7)
  })

  it('returns only alerts newer than the last one seen, oldest first', () => {
    const items = [makeAlert(9), makeAlert(8), makeAlert(5)]

    const result = detectNewAlerts(items, 7)

    expect(result.fresh.map((a) => a.id)).toEqual([8, 9])
    expect(result.nextSeen).toBe(9)
  })

  it('keeps the last seen id when nothing is new', () => {
    expect(detectNewAlerts([makeAlert(2)], 5)).toEqual({ fresh: [], nextSeen: 5 })
    expect(detectNewAlerts([], 5)).toEqual({ fresh: [], nextSeen: 5 })
    expect(detectNewAlerts([], null)).toEqual({ fresh: [], nextSeen: 0 })
  })
})

describe('describeAlert', () => {
  it('names the signal, the stock and the suggested quantity', () => {
    expect(describeAlert(makeAlert(1))).toBe('매도 신호 모의KOSPI001 · 제안 33주')
  })

  it('leaves out what is missing', () => {
    const alert = makeAlert(1, { name: null, suggested_quantity: null, label: '시세 갱신 지연 경고' })

    expect(describeAlert(alert)).toBe('시세 갱신 지연 경고')
  })
})
