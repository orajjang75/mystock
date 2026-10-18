import { expect, test, type Page } from '@playwright/test'
import { Market, authedJson, login } from './support.ts'

// The e2e market has 500 sessions of daily bars for 25 stocks and no stored minute bars, so the
// cycle runs on daily bars here. The minute-bar comparison is covered by the backend tests.

async function openBacktest(page: Page) {
  await page.goto('/backtest')
  await expect(page.getByRole('button', { name: /백테스트 실행/ })).toBeVisible()
}

async function useDailyBars(page: Page) {
  await page.locator('.ant-radio-button-wrapper', { hasText: '일봉' }).first().click()
  await page.getByRole('checkbox', { name: /같은 기간에 비교/ }).uncheck()
}

/** antd draws the chosen value over the input, so click the select itself, then the option. */
async function pick(page: Page, combobox: string, option: string) {
  await page.locator('.ant-select').filter({ has: page.getByRole('combobox', { name: combobox, exact: true }) }).click()
  await page.keyboard.type(option) // the long parameter lists are virtualized: search for the entry
  const open = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
  await open.locator('.ant-select-item-option-content', { hasText: option }).first().click()
}

async function runAndWait(page: Page) {
  await page.getByRole('button', { name: /백테스트 실행/ }).click()
  await expect(page.getByText('백테스트를 시작했습니다')).toBeVisible()
  await expect(page.getByRole('button', { name: /백테스트 실행/ })).toBeHidden() // the form folded away
  // the run goes queued -> running -> done; the tabs only exist once it is done
  await expect(page.getByRole('tab', { name: '신호 품질' })).toBeVisible({ timeout: 150_000 })
}

test.describe('백테스트 화면', () => {
  test.beforeEach(async ({ page, request }) => {
    await new Market(request).reset()
    await login(page)
  })

  test('모의 데이터로 끝까지 돌고 결과의 모든 부분이 채워진다', async ({ page }) => {
    await openBacktest(page)
    await useDailyBars(page)
    await runAndWait(page)

    // 요약: both parts, with the verdict on the sample size
    await expect(page.getByText(/후보 선정 후 5거래일 수익률/)).toBeVisible()
    await expect(page.getByText(/수량 늘리기 · 1d 사이클/)).toBeVisible()
    await expect(page.getByText('수정주가', { exact: true })).toBeVisible()
    await page.screenshot({ path: '../e2e-shots/backtest-summary.png', fullPage: true })

    // 신호 품질: the picks against the three baselines, with charts drawn
    await page.getByRole('tab', { name: '신호 품질' }).click()
    await expect(page.getByText('보유 기간별 수익률 (비용 반영)')).toBeVisible()
    for (const baseline of ['유니버스 전체', '무작위 진입', 'KOSPI']) {
      await expect(page.getByRole('row', { name: new RegExp(`5일 ${baseline}`) })).toBeVisible()
    }
    await expect(page.locator('[data-testid="echart"] canvas').first()).toBeVisible()
    await expect(page.getByText('시장 국면별 (KOSPI 기준)')).toBeVisible()
    await expect(page.getByText(/신호 당일 종가로는 체결하지 않습니다/)).toBeVisible()
    await page.screenshot({ path: '../e2e-shots/backtest-quality.png', fullPage: true })

    // 수량 늘리기: curves and the trade list
    await page.getByRole('tab', { name: '수량 늘리기' }).click()
    await expect(page.getByText('자산 곡선 (시작 = 100)')).toBeVisible()
    await expect(page.getByText('수량 증가 추이 (시작 수량 대비 %)')).toBeVisible()
    await expect(page.getByText(/거래 목록 \(\d+건\)/)).toBeVisible()
    await expect(page.locator('[data-testid="echart"] canvas').first()).toBeVisible()
    await page.screenshot({ path: '../e2e-shots/backtest-cycle.png', fullPage: true })

    // the run is stored with its parameters and a summary
    const runs = await authedJson<{ id: number; status: string; summary: Record<string, unknown> }[]>(page, '/api/backtests')
    expect(runs).toHaveLength(1)
    expect(runs[0].status).toBe('done')
    expect(runs[0].summary).toHaveProperty('signal_quality')
    expect(runs[0].summary).toHaveProperty('cycle')
    const run = await authedJson<{ params: { params: unknown } }>(page, `/api/backtests/${runs[0].id}`)
    expect(run.params.params).toBeTruthy()
  })

  test('결과를 프리셋으로 저장해 스크리너에 적용할 수 있다', async ({ page }) => {
    await openBacktest(page)
    await useDailyBars(page)
    await page.getByRole('checkbox', { name: /사이클 시뮬레이션/ }).uncheck() // faster: the quality part is enough
    // change one parameter for this run only
    await page.getByText('스크리너 신호 (일봉)').click()
    const threshold = page.getByLabel('52주 낙폭 기준')
    await threshold.fill('-25')
    await runAndWait(page)

    // the settings still hold the PRD value
    const before = await authedJson<{ signal_params: { screener: { drawdown_threshold_pct: number } } }>(page, '/api/settings')
    expect(before.signal_params.screener.drawdown_threshold_pct).toBe(-30)

    await page.getByLabel('프리셋 이름').fill('낙폭 -25 시험')
    await page.getByRole('button', { name: '프리셋으로 저장' }).click()
    await expect(page.getByText(/프리셋 "낙폭 -25 시험"을 저장했습니다/)).toBeVisible()
    const saved = await authedJson<{ presets: { name: string }[]; signal_params: { screener: { drawdown_threshold_pct: number } } }>(page, '/api/settings')
    expect(saved.presets.map((p) => p.name)).toContain('낙폭 -25 시험')
    expect(saved.signal_params.screener.drawdown_threshold_pct).toBe(-30) // saving does not apply

    // apply: after a confirmation the screener's settings are the run's
    await page.getByRole('button', { name: '스크리너에 적용' }).click()
    await expect(page.locator('.ant-modal-confirm')).toBeVisible()
    await page.locator('.ant-modal-confirm').getByRole('button', { name: '적용' }).click()
    await expect(page.getByText(/현재 설정에 적용했습니다/)).toBeVisible()
    const after = await authedJson<{ signal_params: { screener: { drawdown_threshold_pct: number } } }>(page, '/api/settings')
    expect(after.signal_params.screener.drawdown_threshold_pct).toBe(-25)

    // and the screener's condition bar shows it
    await page.getByRole('link', { name: '스크리너로 이동' }).click()
    await expect(page).toHaveURL(/\/screener/)
    await expect(page.getByLabel('조건 요약')).toContainText('-25%')
    await page.screenshot({ path: '../e2e-shots/backtest-applied-screener.png', fullPage: true })
  })

  test('민감도 히트맵과 롤링 검증이 나온다', async ({ page }) => {
    test.setTimeout(240_000)
    await openBacktest(page)
    await useDailyBars(page)
    await page.getByRole('checkbox', { name: /사이클 시뮬레이션/ }).uncheck()

    await page.getByRole('switch', { name: '파라미터 민감도' }).click()
    await pick(page, '민감도 평가 대상', '신호 품질')
    await pick(page, '가로축', '52주 낙폭 기준')
    await page.getByLabel('가로축 값').fill('-20, -30, -40')

    await page.getByRole('switch', { name: '롤링 검증' }).click()
    await pick(page, '고를 파라미터', '52주 낙폭 기준')
    await page.getByLabel('고를 파라미터 값').fill('-20, -30')

    await runAndWait(page)

    await page.getByRole('tab', { name: '민감도 히트맵' }).click()
    await expect(page.getByText(/가장 높은 칸:/)).toBeVisible()
    await expect(page.locator('[data-testid="echart"] canvas').first()).toBeVisible()
    await page.getByText('주변 3×3 평균').click()
    await expect(page.getByText(/주변까지 고르게 좋은 칸:/)).toBeVisible()
    await page.screenshot({ path: '../e2e-shots/backtest-heatmap.png', fullPage: true })

    await page.getByRole('tab', { name: '롤링 검증' }).click()
    await expect(page.getByText('구간별 학습·검증 지표')).toBeVisible()
    await expect(page.getByRole('row', { name: /2026-/ }).first()).toBeVisible()
    await page.screenshot({ path: '../e2e-shots/backtest-walkforward.png', fullPage: true })
  })

  test('리포트를 내려받을 수 있고 실행 목록에서 다시 열 수 있다', async ({ page }) => {
    await openBacktest(page)
    await useDailyBars(page)
    await page.getByRole('checkbox', { name: /사이클 시뮬레이션/ }).uncheck()
    await runAndWait(page)

    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /리포트 내려받기/ }).click()])
    expect(download.suggestedFilename()).toMatch(/^backtest-\d+\.md$/)
    const stream = await download.createReadStream()
    const chunks: Buffer[] = []
    for await (const chunk of stream) chunks.push(chunk as Buffer)
    const text = Buffer.concat(chunks).toString('utf-8')
    expect(text).toContain('# 백테스트 리포트')
    expect(text).toContain('## 1. 신호 품질')
    expect(text).toContain('6장 기본값을 정하는 일은 하지 않습니다')

    // leave and come back: the run is in the list and opens again
    await page.goto('/')
    await page.goto('/backtest')
    await expect(page.getByRole('row', { name: /완료/ }).first()).toBeVisible()
    await expect(page.getByRole('tab', { name: '신호 품질' })).toBeVisible()
  })
})
