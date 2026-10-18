import { expect, test } from '@playwright/test'
import { REBUY_TIME, SELL_TIME, Market, authedJson, clicks, countClicks, login } from './support.ts'

interface AlertsBody {
  items: { id: number; kind: string; suggested_quantity: number | null; price: number | null; rebuy_target_price: number | null }[]
}
interface CyclesBody {
  cycles: { state: string; sell_quantity: number; rebuy_quantity: number | null; quantity_increase: number | null }[]
  totals: { cumulative_increase: number; current_quantity: number; start_quantity: number }
}

test('매도 신호 → 알림 → 체결 기록 → 재매수 신호 → 체결 기록 → 수량 증가분', async ({ page, request }) => {
  const market = new Market(request)
  const { holding_id, name } = await market.reset()
  await login(page)
  await page.goto('/holdings')

  const row = page.getByRole('row', { name: new RegExp(name) })
  await expect(row.getByText('보유', { exact: true })).toBeVisible()
  await expect(row).toContainText('300주')

  // 1. the 10:00 bar closes and the sell alert arrives with the suggested quantity and target
  const sell = await market.at(SELL_TIME)
  expect(sell.saved).toBe(1)
  const notice = page.locator('.ant-notification-notice', { hasText: '매도 신호' })
  await expect(notice).toBeVisible()
  await expect(page.getByText(/새 알림 1건/)).toBeVisible() // the banner
  const alerts = await authedJson<AlertsBody>(page, '/api/alerts')
  const sellAlert = alerts.items.find((a) => a.kind === 'sell')
  expect(sellAlert?.suggested_quantity).toBe(100) // a third of 300

  // 2. two clicks: the notification opens the holding with the form filled in, then 기록
  await countClicks(page)
  await notice.click()
  const sellDialog = page.getByRole('dialog', { name: /매도 체결 기록/ })
  await expect(sellDialog).toBeVisible()
  await expect(sellDialog.getByLabel('체결가 (원)')).toHaveValue(new RegExp(String(sellAlert?.price).replace(/(\d)(?=(\d{3})+$)/g, '$1,?')))
  await expect(sellDialog.getByLabel('수량 (주)')).toHaveValue('100')
  await page.screenshot({ path: '../e2e-shots/fill-modal-sell.png' })
  await sellDialog.getByRole('button', { name: '기록', exact: true }).click()
  await expect(sellDialog).toBeHidden()
  expect(await clicks(page)).toBe(2)

  // the state moved at once, without a reload
  await expect(row.getByText('재매수 대기', { exact: true })).toBeVisible()
  await expect(row).toContainText('200주')
  const afterSell = await authedJson<CyclesBody>(page, `/api/holdings/${holding_id}/cycles`)
  expect(afterSell.cycles).toHaveLength(1)
  expect(afterSell.cycles[0].state).toBe('rebuy_wait')
  const cycleRows = page.getByRole('row', { name: /재매수 대기.*100주/ })
  await expect(cycleRows.first()).toBeVisible()

  // 3. a bar later the price is below the target and the reversal signals overlap: rebuy alert
  const rebuy = await market.at(REBUY_TIME)
  expect(rebuy.saved).toBe(1)
  const rebuyNotice = page.locator('.ant-notification-notice', { hasText: '재매수 신호' })
  await expect(rebuyNotice).toBeVisible()
  const rebuyAlert = (await authedJson<AlertsBody>(page, '/api/alerts')).items.find((a) => a.kind === 'rebuy')
  expect(rebuyAlert?.suggested_quantity).toBeGreaterThan(100)

  await countClicks(page)
  await rebuyNotice.click()
  const rebuyDialog = page.getByRole('dialog', { name: /재매수 체결 기록/ })
  await expect(rebuyDialog).toBeVisible()
  await expect(rebuyDialog.getByLabel('수량 (주)')).toHaveValue(String(rebuyAlert?.suggested_quantity))
  const increase = (rebuyAlert?.suggested_quantity ?? 0) - 100
  await expect(rebuyDialog).toContainText(`예상 수량 증가분 +${increase}주`)
  await page.screenshot({ path: '../e2e-shots/fill-modal-rebuy.png' })
  await rebuyDialog.getByRole('button', { name: '기록', exact: true }).click()
  await expect(rebuyDialog).toBeHidden()
  expect(await clicks(page)).toBe(2)

  // 4. back to 보유, with the gain in shares on the card and in the cycle history
  await expect(row.getByText('보유', { exact: true })).toBeVisible()
  await expect(row).toContainText(`${300 + increase}주`)
  const card = page.getByLabel('수량 증가분 누적')
  await expect(card).toContainText(`+${increase}`)
  await expect(page.getByRole('row', { name: /재매수 완료/ })).toContainText(`+${increase}주`)
  const done = await authedJson<CyclesBody>(page, `/api/holdings/${holding_id}/cycles`)
  expect(done.cycles[0].state).toBe('rebuy_done')
  expect(done.cycles[0].quantity_increase).toBe(increase)
  expect(done.totals).toMatchObject({ cumulative_increase: increase, current_quantity: 300 + increase, start_quantity: 300 })
  expect(increase).toBeGreaterThan(0)
})
