import { expect, test } from '@playwright/test'
import { Market, authedJson, login } from './support.ts'

test.describe('보유 종목 화면', () => {
  test.beforeEach(async ({ page, request }) => {
    await new Market(request).reset()
    await login(page)
    await page.goto('/holdings')
  })

  test('보유 종목을 등록하면 시작 수량과 함께 표에 나타난다', async ({ page }) => {
    await page.getByRole('button', { name: /보유 종목 등록/ }).click()
    const dialog = page.getByRole('dialog', { name: '보유 종목 등록' })

    await dialog.getByLabel('종목 코드').fill('12')
    await dialog.getByLabel('수량 (주)').fill('10')
    await dialog.getByLabel('평균단가 (원)').fill('50000')
    await dialog.getByRole('button', { name: '등록' }).click()
    await expect(dialog.getByText('종목 코드는 6자리입니다')).toBeVisible()

    await dialog.getByLabel('종목 코드').fill('999999')
    await dialog.getByRole('button', { name: '등록' }).click()
    await expect(dialog.getByRole('alert')).toContainText('Unknown stock') // the server's refusal is shown

    await dialog.getByLabel('종목 코드').fill('900010')
    await dialog.getByRole('button', { name: '등록' }).click()
    await expect(dialog).toBeHidden()

    const row = page.getByRole('row', { name: /900010/ })
    await expect(row).toBeVisible()
    await expect(row).toContainText('시작 10')
    await expect(row.getByText('보유', { exact: true })).toBeVisible()
    const holdings = await authedJson<{ code: string; start_quantity: number }[]>(page, '/api/holdings')
    expect(holdings.map((h) => [h.code, h.start_quantity])).toContainEqual(['900010', 10])
  })

  test('봉 길이를 30분·60분·일봉으로 바꾸면 그 봉으로 차트를 다시 그린다', async ({ page }) => {
    await expect(page.locator('[data-testid="price-chart"] canvas').first()).toBeVisible()

    for (const [label, bar] of [['30분', '30m'], ['일봉', '1d']] as const) {
      const loaded = page.waitForResponse((r) => r.url().includes('/candles') && r.url().includes(`bar=${bar}`))
      await page.locator('.ant-segmented-item', { hasText: label }).click()
      await loaded
      await expect(page.locator('.ant-segmented-item-selected')).toHaveText(label)
      await expect(page.locator('[data-testid="price-chart"] canvas').first()).toBeVisible()
    }
    // back to 60분: the bars are still cached from the first visit, so nothing is fetched again
    await page.locator('.ant-segmented-item', { hasText: '60분' }).click()
    await expect(page.locator('.ant-segmented-item-selected')).toHaveText('60분')
    await expect(page.locator('[data-testid="price-chart"] canvas').first()).toBeVisible()
  })

  test('체결 기록은 표의 버튼으로도 열 수 있고, 고칠 수 없는 값은 이유와 함께 거절된다', async ({ page }) => {
    await page.getByRole('button', { name: /체결 기록$/ }).click()
    const dialog = page.getByRole('dialog', { name: /매도 체결 기록/ })
    await expect(dialog.getByLabel('수량 (주)')).toHaveValue('100') // a third of 300

    await dialog.getByLabel('수량 (주)').fill('301')
    await dialog.getByRole('button', { name: '기록', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('only 300 held')

    await dialog.getByRole('button', { name: '취소' }).click()
    await expect(dialog).toBeHidden()
    const holdings = await authedJson<{ state: string }[]>(page, '/api/holdings')
    expect(holdings[0].state).toBe('holding') // nothing was recorded
  })
})
