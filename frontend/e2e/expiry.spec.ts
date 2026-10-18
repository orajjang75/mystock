import { expect, test } from '@playwright/test'
import { EXPIRY_TIME, Market, SELL_TIME, authedJson, fillFromAlert, login, newestAlert } from './support.ts'

interface HoldingBody {
  state: string
  open_cycle: { id: number; state: string; expires_at: string } | null
}

/** A sale was recorded and no rebuy signal came for five trading days. */
async function expiredCycle(page: import('@playwright/test').Page, market: Market) {
  const { holding_id, name } = await market.reset()
  await login(page)
  await market.at(SELL_TIME)
  await fillFromAlert(page, holding_id, 'sell', await newestAlert(page, 'sell'))
  // five trading days later, after the close: the daily job notices the wait ran out
  const daily = await market.at(EXPIRY_TIME, 'daily')
  expect(daily.saved).toBeGreaterThanOrEqual(1)
  return { holding_id, name }
}

test.describe('재매수 대기 만료 (A-7)', () => {
  test('알림에서 사이클 포기를 고르면 보유로 돌아간다', async ({ page, request }) => {
    const market = new Market(request)
    const { holding_id, name } = await expiredCycle(page, market)

    await page.goto('/alerts')
    const row = page.getByRole('row', { name: /재매수 대기 만료/ })
    await expect(row).toBeVisible()
    await expect(row.getByRole('button', { name: '재매수 시도' })).toBeVisible()
    await row.getByRole('button', { name: '사이클 포기' }).click()
    await page.getByRole('button', { name: '포기', exact: true }).click() // the confirmation

    await expect(row.getByRole('button', { name: '재매수 시도' })).toBeHidden() // handled: no choice left
    const holdings = await authedJson<HoldingBody[]>(page, '/api/holdings')
    expect(holdings[0].state).toBe('holding')
    const cycles = await authedJson<{ cycles: { state: string }[] }>(page, `/api/holdings/${holding_id}/cycles`)
    expect(cycles.cycles[0].state).toBe('abandoned')

    await page.goto(`/holdings?holding=${holding_id}`)
    await expect(page.getByRole('row', { name: new RegExp(name) }).getByText('보유', { exact: true })).toBeVisible()
    await expect(page.getByRole('row', { name: /포기/ })).toBeVisible() // the cycle history keeps it
  })

  test('보유 종목 화면에서 재매수 시도를 고르면 다시 대기한다', async ({ page, request }) => {
    const market = new Market(request)
    const { holding_id, name } = await expiredCycle(page, market)

    await page.goto(`/holdings?holding=${holding_id}`)
    const row = page.getByRole('row', { name: new RegExp(name) })
    await expect(row.getByText('만료', { exact: true })).toBeVisible()
    const notice = page.getByText('재매수 대기가 만료되었습니다')
    await expect(notice).toBeVisible()

    await page.getByRole('button', { name: '재매수 시도' }).click()

    await expect(row.getByText('재매수 대기', { exact: true })).toBeVisible()
    await expect(notice).toBeHidden()
    const holdings = await authedJson<HoldingBody[]>(page, '/api/holdings')
    expect(holdings[0].open_cycle?.state).toBe('rebuy_wait')
    // a fresh five-trading-day window, counted from the (mock) now
    expect(holdings[0].open_cycle?.expires_at.slice(0, 10)).toBe('2026-10-30')
  })
})
