import { expect, test } from '@playwright/test'
import { Market, buildHistory, login } from './support.ts'

// Two resolutions: a desktop window and a phone. Screenshots land in e2e-shots/ for a look.
const VIEWPORTS = [
  { name: 'desktop-1440x900', width: 1440, height: 900 },
  { name: 'mobile-390x844', width: 390, height: 844 },
]

for (const viewport of VIEWPORTS) {
  test.describe(`레이아웃 ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    test('보유 종목과 알림 화면이 깨지지 않는다', async ({ page, request }) => {
      const market = new Market(request)
      const { holding_id } = await market.reset()
      await login(page)
      await buildHistory(page, market, holding_id)

      const noOverflow = async (label: string) => {
        const { scrollWidth, innerWidth } = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        }))
        expect(scrollWidth, `${label}: horizontal overflow`).toBeLessThanOrEqual(innerWidth)
      }

      await page.goto('/holdings')
      await expect(page.getByRole('row', { name: /재매수 완료/ })).toBeVisible()
      await expect(page.locator('[data-testid="price-chart"] canvas').first()).toBeVisible()
      await page.waitForTimeout(1200) // the chart draws after the data arrives
      await page.screenshot({ path: `../e2e-shots/${viewport.name}-holdings.png`, fullPage: true })
      await noOverflow('holdings')

      await page.goto('/alerts')
      await expect(page.getByText('일봉 수급 이탈로 보류됨').first()).toBeVisible()
      await page.screenshot({ path: `../e2e-shots/${viewport.name}-alerts.png`, fullPage: true })
      await noOverflow('alerts')

      await page.locator('.ant-table-row-expand-icon').first().click()
      await page.screenshot({ path: `../e2e-shots/${viewport.name}-alerts-evidence.png`, fullPage: true })
      await noOverflow('alerts (evidence)')

      await page.goto('/')
      await expect(page.getByLabel(/보유 상태/).first()).toBeVisible()
      await noOverflow('dashboard')
    })
  })
}

for (const viewport of VIEWPORTS) {
  test.describe(`백테스트 레이아웃 ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    test('백테스트 화면이 깨지지 않는다', async ({ page, request }) => {
      test.setTimeout(240_000)
      await new Market(request).reset()
      await login(page)
      // a finished run to look at, started through the API
      const created = await page.request.post('/api/backtests', {
        data: {
          bar_length: '1d',
          compare_bar_lengths: false,
          signal_quality: { random_trials: 3, horizons: [5], slippages: [0, 0.001] },
          cycle: { max_stocks: 6, slippages: [0, 0.001] },
          sensitivity: { target: 'signal_quality', metric: 'median_return', x: { path: 'screener.drawdown_threshold_pct', values: [-20, -30, -40] } },
        },
      })
      expect(created.ok()).toBeTruthy()
      const { id } = (await created.json()) as { id: number }
      await expect.poll(async () => (await (await page.request.get(`/api/backtests/${id}`)).json()).status, { timeout: 180_000 }).toBe('done')

      const noOverflow = async (label: string) => {
        const { scrollWidth, innerWidth } = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        }))
        expect(scrollWidth, `${label}: horizontal overflow`).toBeLessThanOrEqual(innerWidth)
      }

      await page.goto(`/backtest?run=${id}`)
      await expect(page.getByRole('tab', { name: '신호 품질' })).toBeVisible()
      await noOverflow('backtest (form)')
      await page.getByRole('button', { name: /새 백테스트/ }).click()
      await expect(page.getByRole('button', { name: /백테스트 실행/ })).toBeVisible()
      await page.screenshot({ path: `../e2e-shots/${viewport.name}-backtest-form.png`, fullPage: true })
      await noOverflow('backtest (form open)')
      await page.getByRole('button', { name: /새 백테스트/ }).click()

      for (const tab of ['요약', '신호 품질', '수량 늘리기', '민감도 히트맵']) {
        await page.getByRole('tab', { name: tab }).click()
        await page.waitForTimeout(900) // the charts draw after the tab opens
        await page.screenshot({ path: `../e2e-shots/${viewport.name}-backtest-${tab}.png`, fullPage: true })
        await noOverflow(`backtest (${tab})`)
      }
    })
  })
}
