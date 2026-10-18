import { AxiosError, AxiosHeaders } from 'axios'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../../api/endpoints'
import {
  makeCycle,
  makeDetail,
  makeGrid,
  makeQuality,
  makeRun,
  makeRunSummary,
  makeSummary,
  makeWalkForward,
} from '../../test/backtestFixtures'
import { makeSettings } from '../../test/fixtures'
import { renderApp } from '../../test/render'
import { BacktestPage } from './BacktestPage'

vi.mock('../../api/endpoints')
vi.mock('../../components/charts/EChart', () => ({
  EChart: (props: { option: unknown; label?: string }) => (
    <div data-testid="echart" role="img" aria-label={props.label} data-option={JSON.stringify(props.option)} />
  ),
}))

const user = () => userEvent.setup({ delay: null, pointerEventsCheck: 0 })

function Where() {
  const location = useLocation()
  return <p>at {location.pathname + location.search}</p>
}

function show(route = '/backtest') {
  return renderApp(
    <Routes>
      <Route path="/backtest" element={<BacktestPage />} />
      <Route path="*" element={<Where />} />
    </Routes>,
    { route },
  )
}

function setup(run = makeRun(1), runs = [makeRunSummary(1)]) {
  vi.mocked(endpoints.fetchBacktests).mockResolvedValue(runs)
  vi.mocked(endpoints.fetchBacktest).mockResolvedValue(run)
}

function failure(status: number, detail: string): AxiosError {
  const config = { headers: new AxiosHeaders(), url: '/api/backtests' }
  return new AxiosError(String(status), 'ERR_BAD_REQUEST', config, null, {
    status,
    statusText: '',
    headers: {},
    config,
    data: { detail },
  })
}

describe('BacktestPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings({ refresh_seconds: 0, signal_bar_length: '60m' }))
    setup()
  })

  describe('running a backtest', () => {
    it('starts from the current settings and sends them with the request', async () => {
      vi.mocked(endpoints.createBacktest).mockResolvedValue(makeRunSummary(2, { status: 'queued', progress: 0 }))
      show()

      await user().click(await screen.findByRole('button', { name: /백테스트 실행/ }))

      await waitFor(() => expect(endpoints.createBacktest).toHaveBeenCalledTimes(1))
      const request = vi.mocked(endpoints.createBacktest).mock.calls[0][0]
      expect(request.bar_length).toBe('60m')
      expect(request.params).toEqual(makeSettings().signal_params)
      expect(request.signal_quality?.primary_horizon).toBe(5)
      expect(request.cycle?.max_stocks).toBe(30)
      expect(request.universe).toEqual({ point_in_time: true, include_delisted: true })
      expect(await screen.findByText('백테스트를 시작했습니다')).toBeInTheDocument()
      // the form folds away so that the run is in view
      expect(await screen.findByRole('button', { name: /새 백테스트/, expanded: false })).toBeInTheDocument()
    })

    it('runs only what is ticked, with the data options as switched', async () => {
      vi.mocked(endpoints.createBacktest).mockResolvedValue(makeRunSummary(2))
      show()
      const u = user()

      await u.click(await screen.findByRole('checkbox', { name: /사이클 시뮬레이션/ }))
      await u.click(screen.getByRole('switch', { name: '상장폐지 종목 포함' }))
      await u.click(screen.getByRole('switch', { name: '시점별 시가총액 순위' }))
      await u.type(screen.getByLabelText('이름 (선택)'), '생존편향 시험')
      await u.click(screen.getByRole('button', { name: /백테스트 실행/ }))

      await waitFor(() => expect(endpoints.createBacktest).toHaveBeenCalled())
      const request = vi.mocked(endpoints.createBacktest).mock.calls[0][0]
      expect(request.cycle).toBeNull()
      expect(request.compare_bar_lengths).toBe(false)
      expect(request.signal_quality).not.toBeNull()
      expect(request.universe).toEqual({ point_in_time: false, include_delisted: false })
      expect(request.name).toBe('생존편향 시험')
    })

    it('asks for something to run before sending anything', async () => {
      show()
      const u = user()

      await u.click(await screen.findByRole('checkbox', { name: /사이클 시뮬레이션/ }))
      await u.click(screen.getByRole('checkbox', { name: /신호 품질/ }))
      await u.click(screen.getByRole('button', { name: /백테스트 실행/ }))

      expect(await screen.findByText('실행할 항목을 하나 이상 고르세요')).toBeInTheDocument()
      expect(endpoints.createBacktest).not.toHaveBeenCalled()
    })

    it('adds a sensitivity grid and checks its values', async () => {
      vi.mocked(endpoints.createBacktest).mockResolvedValue(makeRunSummary(2))
      show()
      const u = user()

      await u.click(await screen.findByRole('switch', { name: '파라미터 민감도' }))
      const values = await screen.findByLabelText('가로축 값')
      await u.clear(values)
      await u.type(values, '0.01')
      await u.click(screen.getByRole('button', { name: /백테스트 실행/ }))
      expect(await screen.findByText(/숫자를 두 개 이상/)).toBeInTheDocument()
      expect(endpoints.createBacktest).not.toHaveBeenCalled()

      await u.clear(values)
      await u.type(values, '0.01, 0.02, 0.03')
      await u.click(screen.getByRole('button', { name: /백테스트 실행/ }))

      await waitFor(() => expect(endpoints.createBacktest).toHaveBeenCalled())
      expect(vi.mocked(endpoints.createBacktest).mock.calls[0][0].sensitivity).toMatchObject({
        target: 'cycle',
        x: { path: 'rebuy.target_gain', values: [0.01, 0.02, 0.03] },
      })
    })

    it('fills the values around the current parameter on request', async () => {
      show()
      const u = user()
      await u.click(await screen.findByRole('switch', { name: '파라미터 민감도' }))

      await u.click((await screen.findAllByRole('button', { name: '현재 값 주변으로 채우기' }))[0])

      expect(screen.getByLabelText('가로축 값')).toHaveValue('0.005, 0.0075, 0.01, 0.0125, 0.015')
    })

    it('shows the reason when the server refuses the request', async () => {
      vi.mocked(endpoints.createBacktest).mockRejectedValue(failure(422, 'start_date must be before end_date'))
      show()

      await user().click(await screen.findByRole('button', { name: /백테스트 실행/ }))

      expect(await screen.findByText('start_date must be before end_date')).toBeInTheDocument()
    })
  })

  describe('the run list', () => {
    it('lists the runs with their headline numbers and selects the newest', async () => {
      setup(makeRun(2), [makeRunSummary(2, { name: '둘째' }), makeRunSummary(1, { name: '첫째' })])
      show()

      expect(await screen.findByText('둘째')).toBeInTheDocument()
      expect(screen.getByText('첫째')).toBeInTheDocument()
      await waitFor(() => expect(endpoints.fetchBacktest).toHaveBeenCalledWith(2))
      const row = screen.getByRole('row', { name: /둘째/ })
      expect(within(row).getByText('완료')).toBeInTheDocument()
      expect(within(row).getByText(/52\.6% · \+14주/)).toBeInTheDocument() // 사이클 성공률, 누적 증가
    })

    it('opens the run that is clicked and keeps it in the address', async () => {
      setup(makeRun(1), [makeRunSummary(2, { name: '둘째' }), makeRunSummary(1, { name: '첫째' })])
      show()
      await screen.findByText('둘째')

      await user().click(screen.getByRole('row', { name: /첫째/ }))

      await waitFor(() => expect(endpoints.fetchBacktest).toHaveBeenCalledWith(1))
    })

    it('says so when nothing was run yet', async () => {
      vi.mocked(endpoints.fetchBacktests).mockResolvedValue([])

      show()

      expect(await screen.findByText(/아직 실행한 백테스트가 없습니다/)).toBeInTheDocument()
    })

    it('flags a run whose samples are too small', async () => {
      const thin = makeSummary({ cycle: { ...makeSummary().cycle!, adoption: { adoptable: false, reasons: ['끝난 사이클 8건 < 최소 30건: 표본 부족'] } } })
      setup(makeRun(1), [makeRunSummary(1, { summary: thin as never })])
      show()

      expect(await screen.findByText('표본 부족 · 채택 불가')).toBeInTheDocument()
    })
  })

  describe('a run that is not finished', () => {
    it('shows the progress and what it is doing', async () => {
      setup(makeRun(1, { status: 'running', progress: 0.4, summary: { message: 'cycle: slippage 0.100%' } }), [makeRunSummary(1, { status: 'running', progress: 0.4 })])
      show()

      expect(await screen.findByText('cycle: slippage 0.100%')).toBeInTheDocument()
      expect(screen.getAllByRole('progressbar').length).toBeGreaterThan(0)
    })

    it('shows a queued run as waiting', async () => {
      setup(makeRun(1, { status: 'queued', progress: 0, summary: {} }), [makeRunSummary(1, { status: 'queued', progress: 0 })])
      show()

      expect(await screen.findByText('순서를 기다리는 중입니다')).toBeInTheDocument()
    })

    it('shows why a run failed', async () => {
      setup(makeRun(1, { status: 'failed', error: 'BacktestDataError: No daily bars are stored; run the ingest job first.' }, {}), [makeRunSummary(1, { status: 'failed' })])
      show()

      expect(await screen.findByText(/No daily bars are stored/)).toBeInTheDocument()
      expect(screen.getByText('백테스트를 끝내지 못했습니다')).toBeInTheDocument()
    })
  })

  describe('a finished run', () => {
    it('summarises both parts and their sample sizes', async () => {
      show()

      expect(await screen.findByText(/후보 선정 후 5거래일 수익률/)).toBeInTheDocument()
      expect(screen.getByText('일평균 후보 수')).toBeInTheDocument()
      expect(screen.getByText('후보 0건인 날')).toBeInTheDocument()
      expect(screen.getAllByText('표본 기준 충족').length).toBe(3) // the list row and the two cards
      const quality = screen.getByText(/후보 선정 후 5거래일/).closest('.ant-card') as HTMLElement
      for (const label of ['후보', '유니버스 전체', '무작위 진입', 'KOSPI']) {
        expect(within(quality).getByText(label)).toBeInTheDocument()
      }
      expect(screen.getByText(/수량 늘리기 · 60m 사이클/)).toBeInTheDocument()
      expect(screen.getByText('사이클 성공률')).toBeInTheDocument()
      expect(screen.getByText('수정주가')).toBeInTheDocument()
    })

    it('warns about what weakens the result', async () => {
      const summary = makeSummary({ warnings: ['생존 종목만 썼습니다: 상장폐지 종목이 빠져 결과가 실제보다 좋게 보입니다.'] })
      setup(makeRun(1, { summary: summary as never }))
      show()

      expect(await screen.findByText('결과를 읽을 때 주의할 점')).toBeInTheDocument()
      expect(screen.getByText(/생존 종목만 썼습니다/)).toBeInTheDocument()
    })

    it('shows the signal quality: distributions, ratios, regimes, slippage and the events', async () => {
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '신호 품질' }))

      expect(await screen.findByText('보유 기간별 수익률 (비용 반영)')).toBeInTheDocument()
      expect(screen.getByText(/같은 기간 자산 곡선/)).toBeInTheDocument()
      expect(screen.getAllByText('Sharpe').length).toBeGreaterThan(0)
      expect(screen.getByText('시장 국면별 (KOSPI 기준)')).toBeInTheDocument()
      expect(screen.getByText('슬리피지를 올려도 우위가 남는가')).toBeInTheDocument()
      expect(screen.getByText('모의KOSPI014 (900140)')).toBeInTheDocument()
      expect(screen.getByText(/신호 당일 종가로는 체결하지 않습니다/)).toBeInTheDocument()
      const charts = screen.getAllByTestId('echart')
      expect(charts.map((c) => c.getAttribute('aria-label'))).toContain('후보와 비교 대상의 자산 곡선')
    })

    it('says plainly when the signal-quality sample is too small', async () => {
      const detail = makeDetail({ signal_quality: makeQuality({ adoption: { adoptable: false, reasons: ['신호가 난 날 12일 < 최소 30일: 표본 부족'] } }) })
      setup(makeRun(1, {}, detail))
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '신호 품질' }))

      expect(await screen.findByText(/신호가 난 날 12일 < 최소 30일/)).toBeInTheDocument()
      expect(screen.getByText('표본 부족 · 채택 불가')).toBeInTheDocument()
    })

    it('shows the cycle: metrics, curves, the slippage check and the trade list', async () => {
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '수량 늘리기' }))

      expect(await screen.findByText(/사이클 지표/)).toBeInTheDocument()
      expect(screen.getByText('자산 곡선 (시작 = 100)')).toBeInTheDocument()
      expect(screen.getByText('수량 증가 추이 (시작 수량 대비 %)')).toBeInTheDocument()
      expect(screen.getByText('슬리피지를 올려도 수량 증가가 유지되는가')).toBeInTheDocument()
      expect(screen.getByText('거래 목록 (3건)')).toBeInTheDocument()
      const done = screen.getByRole('row', { name: /재매수 완료/ })
      expect(within(done).getByText('47,000 × 74주')).toBeInTheDocument()
      expect(within(done).getByText('46,000 × 76주')).toBeInTheDocument()
      expect(within(done).getByText(/\+2주/)).toBeInTheDocument()
      expect(screen.getByText(/분봉이나 시세가 모자라 건너뛴 종목 1개: 900060/)).toBeInTheDocument()
    })

    it('filters the trade list by state', async () => {
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)
      await user().click(screen.getByRole('tab', { name: '수량 늘리기' }))
      await screen.findByText('거래 목록 (3건)')

      await user().click(screen.getByRole('combobox', { name: '상태 필터' }))
      await user().click(await screen.findByText('강제 매도', { selector: '.ant-select-item-option-content' }))

      expect(await screen.findByText('거래 목록 (1건)')).toBeInTheDocument()
      expect(screen.getByRole('row', { name: /모의KOSPI009/ })).toBeInTheDocument()
    })

    it('compares the bar lengths and marks the one with too few samples', async () => {
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '봉 길이 비교' }))

      expect(await screen.findByText('봉 길이가 길수록 신호 표본이 줄어듭니다')).toBeInTheDocument()
      const daily = screen.getByRole('row', { name: /^1d/ })
      expect(within(daily).getByText('표본 부족 · 채택 불가')).toBeInTheDocument()
      expect(screen.getByText(/표본 부족: 1d/)).toBeInTheDocument()
      const option = JSON.parse(screen.getByLabelText('봉 길이별 비교').getAttribute('data-option') ?? '{}')
      expect(option.xAxis.data).toEqual(['30m', '60m', '1d'])
    })

    it('shows the heatmap and which cell is the best and which is good all around', async () => {
      setup(makeRun(1, {}, makeDetail({ sensitivity: makeGrid() })))
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '민감도 히트맵' }))

      expect(await screen.findByText(/가장 높은 칸: rebuy\.target_gain = 0\.01, sell\.min_overlap = 2/)).toBeInTheDocument()
      expect(screen.getByText(/가장 높은 칸과 주변이 고른 칸이 다릅니다/)).toBeInTheDocument()
      expect(screen.getByLabelText('파라미터 민감도 히트맵')).toBeInTheDocument()

      await user().click(screen.getByText('주변 3×3 평균'))

      expect(await screen.findByText(/주변까지 고르게 좋은 칸: rebuy\.target_gain = 0\.02, sell\.min_overlap = 2/)).toBeInTheDocument()
    })

    it('leaves the heatmap out when no cell has enough samples', async () => {
      const empty = makeGrid({ cells: [[null, null, null], [null, null, null]], smoothed: [[null, null, null], [null, null, null]], best: null, robust_best: null })
      setup(makeRun(1, {}, makeDetail({ sensitivity: empty })))
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '민감도 히트맵' }))

      expect(await screen.findByText('모든 칸이 표본 부족이라 보여 줄 값이 없습니다')).toBeInTheDocument()
    })

    it('shows the walk-forward folds and how the choice held up on unseen windows', async () => {
      setup(makeRun(1, {}, makeDetail({ walk_forward: makeWalkForward() })))
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '롤링 검증' }))

      expect(await screen.findByText('구간별 학습·검증 지표')).toBeInTheDocument()
      expect(screen.getByText('검증/학습 비율이 1보다 많이 낮으면 학습 구간에만 맞춘 것입니다', { exact: false })).toBeInTheDocument()
      expect(screen.getAllByText('2026-01-01 ~ 2026-04-30', { selector: 'td' })).toHaveLength(2)
      expect(screen.getByText(/2가지 \(-30, -20\)/)).toBeInTheDocument()
    })

    it('explains why a walk-forward could not run', async () => {
      setup(makeRun(1, {}, makeDetail({ walk_forward: makeWalkForward({ folds: [], summary: null, reason: 'the period has 60 sessions; one fold needs 160' }) })))
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      await user().click(screen.getByRole('tab', { name: '롤링 검증' }))

      expect(await screen.findByText('롤링 검증을 하지 못했습니다')).toBeInTheDocument()
      expect(screen.getByText(/one fold needs 160/)).toBeInTheDocument()
    })

    it('has no tab for what was not run', async () => {
      setup(makeRun(1, {}, makeDetail({ cycle: undefined })))
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      const tabs = screen.getAllByRole('tab').map((t) => t.textContent)

      expect(tabs).toEqual(['요약', '신호 품질'])
    })

    it('has no bar-length tab when the bars were not compared', async () => {
      setup(makeRun(1, {}, makeDetail({ cycle: makeCycle({ comparison: [] }) })))
      show()
      await screen.findByText(/후보 선정 후 5거래일 수익률/)

      expect(screen.queryByRole('tab', { name: '봉 길이 비교' })).not.toBeInTheDocument()
    })
  })

  describe('keeping and using the result', () => {
    it('saves the parameters as a preset without touching the current settings', async () => {
      vi.mocked(endpoints.saveBacktestPreset).mockResolvedValue({ name: '실행 1', applied: false })
      show()

      await user().click(await screen.findByRole('button', { name: '프리셋으로 저장' }))

      await waitFor(() => expect(endpoints.saveBacktestPreset).toHaveBeenCalledWith(1, { name: '실행 1', apply: false }))
      expect(await screen.findByText(/프리셋 "실행 1"을 저장했습니다/)).toBeInTheDocument()
    })

    it('takes the preset name from the box', async () => {
      vi.mocked(endpoints.saveBacktestPreset).mockResolvedValue({ name: '목표이득 1.5%', applied: false })
      show()
      const u = user()
      const name = await screen.findByLabelText('프리셋 이름')

      await u.clear(name)
      await u.type(name, '목표이득 1.5%')
      await u.click(screen.getByRole('button', { name: '프리셋으로 저장' }))

      await waitFor(() => expect(endpoints.saveBacktestPreset).toHaveBeenCalledWith(1, { name: '목표이득 1.5%', apply: false }))
    })

    it('applies it to the screener only after a confirmation', async () => {
      vi.mocked(endpoints.saveBacktestPreset).mockResolvedValue({ name: '실행 1', applied: true })
      show()
      const u = user()

      await u.click(await screen.findByRole('button', { name: '스크리너에 적용' }))
      expect(endpoints.saveBacktestPreset).not.toHaveBeenCalled()
      expect((await screen.findAllByText('스크리너에 적용할까요?')).length).toBeGreaterThan(0)
      const dialog = document.querySelector('.ant-modal-confirm') as HTMLElement
      await u.click(within(dialog).getByRole('button', { name: '적용' }))

      await waitFor(() => expect(endpoints.saveBacktestPreset).toHaveBeenCalledWith(1, { name: '실행 1', apply: true }))
      expect(await screen.findByText(/현재 설정에 적용했습니다/)).toBeInTheDocument()
      const link = screen.getByRole('link', { name: '스크리너로 이동' })
      expect(link).toHaveAttribute('href', '/screener')

      await u.click(link)

      expect(await screen.findByText('at /screener')).toBeInTheDocument()
    })

    it('shows why a preset could not be saved', async () => {
      vi.mocked(endpoints.saveBacktestPreset).mockRejectedValue(failure(422, 'The name is empty'))
      show()

      await user().click(await screen.findByRole('button', { name: '프리셋으로 저장' }))

      expect(await screen.findByText('The name is empty')).toBeInTheDocument()
    })

    it('downloads the report as a Markdown file', async () => {
      vi.mocked(endpoints.fetchBacktestReport).mockResolvedValue('# 백테스트 리포트')
      const createObjectURL = vi.fn(() => 'blob:report')
      const revokeObjectURL = vi.fn()
      Object.assign(URL, { createObjectURL, revokeObjectURL })
      const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
      show()

      await user().click(await screen.findByRole('button', { name: /리포트 내려받기/ }))

      await waitFor(() => expect(click).toHaveBeenCalled())
      expect(endpoints.fetchBacktestReport).toHaveBeenCalledWith(1)
      expect(createObjectURL).toHaveBeenCalledTimes(1)
      const blob = (createObjectURL.mock.calls[0] as unknown as [Blob])[0]
      expect(blob.type).toContain('text/markdown')
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:report')
      click.mockRestore()
    })

    it('deletes a run after a confirmation', async () => {
      vi.mocked(endpoints.deleteBacktest).mockResolvedValue()
      show()
      const u = user()

      await u.click(await screen.findByRole('button', { name: /삭제/ }))
      const popup = await waitFor(() => {
        const element = document.querySelector('.ant-popover:not(.ant-popover-hidden)') as HTMLElement
        expect(element).toBeTruthy()
        return element
      })
      await u.click(within(popup).getByRole('button', { name: '삭제' }))

      await waitFor(() => expect(vi.mocked(endpoints.deleteBacktest).mock.calls[0][0]).toBe(1))
    })
  })
})
