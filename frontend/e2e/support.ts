import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const SELL_TIME = '2026-10-16T11:00:10+09:00' // the 10:00 bar of the 60-minute signals has just closed
export const REBUY_TIME = '2026-10-16T13:00:10+09:00' // the 12:00 bar, after the stock dropped 5 %
export const EXPIRY_TIME = '2026-10-23T18:00:10+09:00' // after the close of the 5th trading day

export interface Scenario {
  holding_id: number
  code: string
  name: string
}

/** The test controls of the e2e backend (see backend/e2e/server.py), through the Vite proxy. */
export class Market {
  private readonly request: APIRequestContext

  constructor(request: APIRequestContext) {
    this.request = request
  }

  private async post<T>(path: string, data?: object): Promise<T> {
    const response = await this.request.post(`/api/_e2e${path}`, { data })
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy()
    return (await response.json()) as T
  }

  reset() {
    return this.post<Scenario>('/reset')
  }

  /** Move the clock and run the intraday (or daily) job as the scheduler would at that moment. */
  async at(now: string, job: 'intraday' | 'daily' = 'intraday') {
    await this.post('/clock', { now })
    return this.post<{ saved: number; stale: string[]; skipped: string | null }>('/tick', { job })
  }

  signals(pins: { sell?: boolean; rebuy?: boolean; flow?: 'off' | 'exit' | 'missing'; force_sell?: boolean }) {
    return this.post('/signals', pins)
  }
}

export async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('아이디').fill('e2e')
  await page.getByLabel('비밀번호').fill('e2e-password')
  await page.getByRole('button', { name: /로그인/ }).click()
  await expect(page.getByRole('navigation', { name: '주 메뉴' })).toBeVisible()
}

/** Count every click from now on, to prove how many clicks a task takes. */
export async function countClicks(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __clicks: number; __counting?: boolean }
    w.__clicks = 0
    if (w.__counting) return
    w.__counting = true
    document.addEventListener('click', () => (w.__clicks += 1), true)
  })
}

export async function clicks(page: Page): Promise<number> {
  return page.evaluate(() => (window as unknown as { __clicks: number }).__clicks)
}

export async function authedJson<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(path)
  expect(response.ok(), path).toBeTruthy()
  return (await response.json()) as T
}

interface AlertRow {
  id: number
  kind: string
  suggested_quantity: number | null
  price: number | null
}

/** The newest alert of a kind, read through the API as the signed-in user. */
export async function newestAlert(page: Page, kind: string): Promise<AlertRow> {
  const body = await authedJson<{ items: AlertRow[] }>(page, '/api/alerts?limit=200')
  const alert = body.items.find((a) => a.kind === kind)
  expect(alert, `an alert of kind ${kind}`).toBeTruthy()
  return alert as AlertRow
}

/** Record a fill as the alert suggested it (what the form does when the user only confirms). */
export async function fillFromAlert(page: Page, holdingId: number, side: 'sell' | 'rebuy', alert: AlertRow) {
  const response = await page.request.post(`/api/holdings/${holdingId}/fills`, {
    data: { side, price: alert.price, quantity: alert.suggested_quantity },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

/**
 * A day with a little of everything: a sell, a rebuy held back by the flow filter, the rebuy,
 * and a second sell that is still waiting. Leaves the first cycle done and the second open.
 */
export async function buildHistory(page: Page, market: Market, holdingId: number) {
  await market.at(SELL_TIME)
  await fillFromAlert(page, holdingId, 'sell', await newestAlert(page, 'sell'))
  await market.signals({ flow: 'exit' })
  await market.at(REBUY_TIME)
  await market.signals({ flow: 'off' })
  await market.at('2026-10-16T14:00:10+09:00')
  await fillFromAlert(page, holdingId, 'rebuy', await newestAlert(page, 'rebuy'))
  await market.at('2026-10-16T15:00:10+09:00')
  await fillFromAlert(page, holdingId, 'sell', await newestAlert(page, 'sell'))
}
