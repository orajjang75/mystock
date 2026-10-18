// Real-browser check of the screener / dashboard (PRD 7장). Needs `make dev` running on mock data.
//   make e2e-screener   (or: node e2e/screener.mjs <screenshot-dir>)
import { chromium, request } from 'playwright'

const base = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const login = { username: process.env.E2E_USER ?? 'admin', password: process.env.E2E_PASSWORD ?? 'dev-password' }
const shots = process.argv[2] ?? 'e2e-shots'
const viewports = [
  { name: 'desktop-1440x900', width: 1440, height: 900 },
  { name: 'mobile-390x844', width: 390, height: 844 },
]
const failures = []
const check = (name, ok, extra = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`)
  if (!ok) failures.push(name)
}

// start from an empty watchlist so that the run can be repeated
const api = await request.newContext({ baseURL: base })
await api.post('/api/auth/login', { data: login })
for (const w of await (await api.get('/api/watchlist')).json()) await api.delete(`/api/watchlist/${w.code}`)

const browser = await chromium.launch()
for (const vp of viewports) {
  console.log(`\n== ${vp.name}`)
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
  const page = await context.newPage()
  page.setDefaultTimeout(15000)
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  // the 401 of the signed-out visit (/api/auth/me) is expected
  page.on('console', (m) => m.type() === 'error' && !m.text().includes('401') && errors.push(m.text()))
  const noOverflow = async (label) => {
    const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }))
    check(`${label}: no horizontal overflow`, o.sw <= o.iw, `${o.sw}/${o.iw}`)
  }

  await page.goto(base)
  await page.getByLabel('아이디').fill(login.username)
  await page.getByLabel('비밀번호').fill(login.password)
  await page.getByRole('button', { name: /로그인/ }).click()
  await page.getByText('오늘의 상위 후보', { exact: true }).waitFor()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${shots}/${vp.name}-1-dashboard.png`, fullPage: true })
  await noOverflow('dashboard')
  check('dashboard: watchlist empty message', await page.getByText(/★로 관심종목을 추가하세요/).waitFor().then(() => true, () => false))

  // scan from the screen
  await page.goto(`${base}/screener`)
  await page.getByRole('button', { name: /^스캔 실행|스캔 실행$/ }).first().click()
  await page.getByRole('table').first().waitFor()
  const rows = page.locator('.ant-table-tbody tr.ant-table-row')
  await rows.first().waitFor()
  check('screener: results table has rows', (await rows.count()) > 0, `rows=${await rows.count()}`)
  await page.screenshot({ path: `${shots}/${vp.name}-2-screener.png`, fullPage: true })
  await noOverflow('screener')

  // add to the watchlist with the star, then open the drawer
  const firstName = (await rows.first().locator('td').nth(1).innerText()).split('\n')[0]
  await page.getByRole('button', { name: /관심종목 추가$/ }).first().click()
  await page.getByRole('button', { name: /관심종목 제외$/ }).first().waitFor()
  check('screener: star toggles to "제외"', true)

  await rows.first().locator('td').nth(1).click()
  const drawer = page.locator('.ant-drawer-content')
  await drawer.waitFor()
  const chart = drawer.getByTestId('price-chart')
  await chart.waitFor()
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="price-chart"] canvas').length >= 4)
  await page.waitForTimeout(1200)
  await drawer.getByText('근거 지표').first().waitFor().catch(() => {})
  await page.screenshot({ path: `${shots}/${vp.name}-3-drawer.png`, fullPage: false })
  await noOverflow('drawer')

  // pixel checks on the chart canvases: red + blue candles, and panes lined up
  const analysis = await page.evaluate(() => {
    const root = document.querySelector('[data-testid="price-chart"]')
    const canvases = [...root.querySelectorAll('canvas')].filter((c) => c.width > 100 && c.height > 20)
    const out = canvases.map((c) => {
      const { width: w, height: h } = c
      const data = c.getContext('2d').getImageData(0, 0, w, h).data
      let red = 0, blue = 0
      const redCols = new Uint8Array(w), blueCols = new Uint8Array(w)
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4
        const r = data[i], g = data[i + 1], b = data[i + 2], a = data[i + 3]
        if (a < 25) continue // volume bars are translucent
        if (r > g + 50 && r > b + 50) { red++; redCols[x] = 1 }
        if (b > r + 50 && b > g + 20) { blue++; blueCols[x] = 1 }
      }
      const rect = c.getBoundingClientRect()
      return { w, h, red, blue, top: Math.round(rect.top), left: Math.round(rect.left), cssW: Math.round(rect.width), cssH: Math.round(rect.height), cols: Array.from(redCols.map((v, x) => v | blueCols[x])) }
    })
    return out
  })
  // one pane = the canvas with the most coloured pixels among those sharing a top edge
  const byTop = new Map()
  for (const a of analysis.filter((c) => c.cssH > 40 && c.cssW > 0.6 * (analysis[0]?.cssW ?? 0))) {
    const prev = byTop.get(a.top)
    if (!prev || a.red + a.blue > prev.red + prev.blue) byTop.set(a.top, a)
  }
  const panes = [...byTop.entries()].sort((x, y) => x[0] - y[0]).map(([, a]) => a)
  const price = panes[0]
  check('drawer: price pane draws red and blue candles', !!price && price.red > 50 && price.blue > 50, price ? `red=${price.red} blue=${price.blue}` : 'no canvas')
  check('drawer: price, volume, RSI and MACD panes are stacked', panes.length >= 4, `panes=${panes.length}`)
  check('drawer: panes share the same left edge and width', new Set(panes.map((p) => p.left)).size === 1 && new Set(panes.map((p) => p.cssW)).size === 1)
  const volume = panes[1]
  if (price && volume) {
    const first = (v) => v.indexOf(1), last = (v) => v.lastIndexOf(1)
    const scale = price.w / price.cssW
    const dFirst = Math.abs(first(price.cols) - first(volume.cols)) / scale
    const dLast = Math.abs(last(price.cols) - last(volume.cols)) / scale
    check('drawer: first and last volume bar line up with the first and last candle (<= 6px)', dFirst <= 6 && dLast <= 6, `first ${dFirst.toFixed(1)}px, last ${dLast.toFixed(1)}px`)
  }
  check('drawer: flow panel rendered', await drawer.getByText(/외국인/).first().isVisible().catch(() => false))
  check('drawer: evidence values shown', await drawer.getByText(/RSI/).first().isVisible().catch(() => false))

  // close the drawer, the dashboard must now show the watched stock
  await page.keyboard.press('Escape')
  await drawer.waitFor({ state: 'hidden' })
  await page.goto(base)
  await page.getByText('오늘의 상위 후보', { exact: true }).waitFor()
  check('dashboard: added stock appears in the watchlist card', await page.locator('.ant-card', { hasText: '관심종목 점수 변화' }).getByText(firstName).waitFor().then(() => true, () => false))
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${shots}/${vp.name}-4-dashboard-watch.png`, fullPage: true })
  await noOverflow('dashboard (watching)')

  // remove again from the watchlist view and see the dashboard follow
  await page.goto(`${base}/screener?view=watchlist`)
  await page.getByRole('button', { name: '제외' }).first().click()
  await page.getByText(/관심종목이 없습니다|비어 있습니다|추가하세요/).first().waitFor().catch(() => {})
  await page.screenshot({ path: `${shots}/${vp.name}-5-watchlist.png`, fullPage: true })
  await page.goto(base)
  await page.getByText(/★로 관심종목을 추가하세요/).waitFor()
  check('dashboard: removed stock disappears', true)

  check('no console / page errors', errors.length === 0, errors.slice(0, 3).join(' | '))
  await context.close()
}
for (const w of await (await api.get('/api/watchlist')).json()) await api.delete(`/api/watchlist/${w.code}`)
await api.dispose()
await browser.close()
console.log(failures.length ? `\n${failures.length} FAILED: ${failures.join('; ')}` : '\nall checks passed')
process.exit(failures.length ? 1 : 0)
