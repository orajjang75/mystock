import { expect, test } from '@playwright/test'
import { Market, buildHistory, login } from './support.ts'

test.describe('알림 화면', () => {
  test.beforeEach(async ({ page, request }) => {
    const market = new Market(request)
    const { holding_id } = await market.reset()
    await login(page)
    await buildHistory(page, market, holding_id) // sell, 보류 경고, rebuy, sell
    await page.goto('/alerts')
    await expect(page.getByRole('row', { name: /매도 신호/ }).first()).toBeVisible()
  })

  test('일봉 수급 이탈로 보류된 알림은 일반 알림과 구분되어 보인다', async ({ page }) => {
    const held = page.getByRole('row', { name: /일봉 수급 이탈로 보류됨/ })
    await expect(held).toHaveClass(/alert-row-warning/)
    await expect(held.getByText('경고', { exact: true })).toBeVisible()
    await expect(held.getByRole('button', { name: '체결 기록' })).toHaveCount(0) // nothing to record

    for (const ordinary of [/매도 신호/, /재매수 신호/]) {
      const normal = page.getByRole('row', { name: ordinary }).first()
      await expect(normal).not.toHaveClass(/alert-row-warning/)
      await expect(normal.getByText('경고', { exact: true })).toHaveCount(0)
    }
  })

  test('종류와 종목으로 거를 수 있다', async ({ page }) => {
    // antd draws the chosen value over the input, so the click goes to the select itself
    const select = (name: string) => page.locator('.ant-select').filter({ has: page.getByRole('combobox', { name }) })
    const pick = async (name: string, option: string) => {
      await select(name).click()
      await page.locator('.ant-select-item-option-content', { hasText: option }).click()
    }

    await pick('신호 종류', '재매수 신호')
    await expect(page.getByRole('row', { name: /재매수 신호/ })).toHaveCount(1)
    await expect(page.getByRole('row', { name: /매도 신호/ })).toHaveCount(0)

    await pick('신호 종류', '재매수 보류 경고')
    await expect(page.getByRole('row', { name: /일봉 수급 이탈로 보류됨/ })).toHaveCount(1)
    await expect(page.getByRole('row', { name: /재매수 신호/ })).toHaveCount(0)

    // clearing the kind and choosing the held stock shows everything of that stock again
    await select('신호 종류').hover()
    await select('신호 종류').locator('.ant-select-clear').click()
    await pick('종목', '모의KOSPI004')
    await expect(page.getByRole('row', { name: /매도 신호/ })).toHaveCount(2)
    await expect(page.getByText(/표시 4건/)).toBeVisible()
  })

  test('행을 펼치면 근거 지표 값이 보이고, 읽음 처리하면 안 읽은 수가 줄어든다', async ({ page }) => {
    const sell = page.getByRole('row', { name: /매도 신호/ }).first()
    await sell.locator('.ant-table-row-expand-icon').click()
    const evidence = page.locator('.alert-evidence').first()
    await expect(evidence).toContainText('RSI 과매수 이탈')
    await expect(evidence).toContainText('겹친 매도 신호 수')
    await expect(evidence).toContainText('60분봉')

    const before = await page.getByText(/읽지 않음 \d+건/).first().innerText()
    await sell.getByRole('button', { name: /읽음 처리/ }).click()
    await expect(page.getByText(/읽지 않음 \d+건/).first()).not.toHaveText(before)

    await page.getByRole('checkbox', { name: '읽지 않은 알림만' }).check()
    await expect(page.getByRole('row', { name: /매도 신호/ })).toHaveCount(1) // the other sell is still unread
  })

  test('체결 기록 버튼이 해당 보유 종목의 입력 창을 미리 채워 연다', async ({ page }) => {
    await page.getByRole('row', { name: /재매수 신호/ }).getByRole('button', { name: '체결 기록' }).click()

    await expect(page).toHaveURL(/\/holdings\?holding=\d+&alert=\d+/)
    await expect(page.getByRole('dialog', { name: /체결 기록/ })).toBeVisible()
  })
})
