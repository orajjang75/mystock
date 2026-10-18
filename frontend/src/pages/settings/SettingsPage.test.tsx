import { AxiosError, AxiosHeaders } from 'axios'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as endpoints from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { makeHealth, makeSettings } from '../../test/fixtures'
import { renderApp } from '../../test/render'
import { GROUP_ORDER, GROUP_TITLES, PARAM_LABELS } from './paramLabels'
import { signalParamLeaves } from './paramSchema'
import { SettingsPage } from './SettingsPage'

vi.mock('../../api/endpoints')

function apiError(status: number, detail: string): AxiosError {
  const config = { headers: new AxiosHeaders(), url: '/api/settings' }
  return new AxiosError(String(status), 'ERR_BAD_REQUEST', config, null, {
    status,
    statusText: '',
    headers: {},
    config,
    data: { detail },
  })
}

async function open(settings: SettingsResponse = makeSettings()) {
  vi.mocked(endpoints.fetchSettings).mockResolvedValue(settings)
  const view = renderApp(<SettingsPage />, { route: '/settings' })
  await screen.findByLabelText('왕복 수수료율')
  return { ...view, user: userEvent.setup({ delay: null, pointerEventsCheck: 0 }) }
}

async function type(user: ReturnType<typeof userEvent.setup>, label: string, value: string) {
  const input = screen.getByLabelText(label)
  await user.clear(input)
  await user.type(input, value)
  await user.tab()
}

/** antd hides the radio input behind its label, so click the label like a user would. */
async function choose(user: ReturnType<typeof userEvent.setup>, name: string) {
  const label = screen.getByRole('radio', { name }).closest('label')
  await user.click(label as HTMLElement)
}

/** Open parameter groups (they render when first opened). */
async function expand(user: ReturnType<typeof userEvent.setup>, ...titles: string[]) {
  for (const title of titles) await user.click(screen.getByText(title))
}

const saved = () => vi.mocked(endpoints.saveSettings).mock.calls[0][0]

describe('SettingsPage', { timeout: 20_000 }, () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(makeHealth())
    vi.mocked(endpoints.saveSettings).mockImplementation(async (document) => ({ ...document, presets: [] }))
  })

  it('shows the saved settings', async () => {
    await open(makeSettings({ alert_cooldown_bars: 9 }))

    expect(screen.getByLabelText('왕복 수수료율')).toHaveValue('0.03') // the stored 0.0003 shown as percent
    expect(screen.getByLabelText('매도 거래세율')).toHaveValue('0.18')
    expect(screen.getByLabelText('알림 쿨다운')).toHaveValue('9')
    expect(screen.getByRole('radio', { name: '60분봉' })).toBeChecked()
    expect(screen.getByRole('switch', { name: '자동 갱신' })).toBeChecked()
    expect(screen.getByLabelText('갱신 주기')).toHaveValue('60')
  })

  it('has a field for every backend parameter, grouped like the PRD', async () => {
    const { user } = await open()

    for (const title of ['공통 지표', '스크리너 신호 (일봉)', '스크리너 배점', '스캔 결과 선택', '매도 신호 (분봉)', '재매수 신호와 목표가', '강제 매도 (A-13)', '일봉 추세 필터 (A-6)', 'ATR 손절선 (A-8)']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    await expand(user, '공통 지표', '스크리너 신호 (일봉)')
    expect(screen.getByLabelText('52주 낙폭 기준')).toHaveValue('-30.0')
    expect(screen.getByLabelText('이격도 과매도 기준')).toHaveValue('-8.0')
    expect(screen.getByLabelText('연속 순매수 일수')).toHaveValue('3')
    expect(screen.getByLabelText('RSI 기간')).toHaveValue('14')
  })

  it('renders every group with all of its fields once opened', async () => {
    const { user } = await open()

    await expand(user, ...GROUP_ORDER.map((group) => GROUP_TITLES[group]))

    const generic = signalParamLeaves().filter((leaf) => !PARAM_LABELS[leaf.key].card)
    for (const leaf of generic) {
      expect(document.getElementById(`signal_params_${leaf.group}_${leaf.field}`), leaf.key).toBeInTheDocument()
    }
    expect(generic).toHaveLength(60) // 62 parameters, two of them in the fees card
  })

  it('cannot be saved until something changes', async () => {
    await open()

    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '되돌리기' })).toBeDisabled()
  })

  it('saves a fee typed as percent as a fraction, leaving everything else as it was', async () => {
    const { user } = await open()

    await type(user, '왕복 수수료율', '0.05')
    expect(await screen.findByText('저장하지 않은 변경 있음')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '저장' }))

    await waitFor(() => expect(endpoints.saveSettings).toHaveBeenCalledTimes(1))
    const expected = makeSettings()
    expected.signal_params.rebuy.round_trip_fee_rate = 0.0005
    const { presets, ...document } = expected
    void presets
    expect(saved()).toEqual(document)
    expect(await screen.findByText('설정을 저장했습니다')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()
  })

  it('will not save a field that was left empty', async () => {
    const { user } = await open()
    await expand(user, '공통 지표')

    await user.clear(screen.getByLabelText('RSI 기간'))
    await user.click(screen.getByRole('button', { name: '저장' }))

    expect(await screen.findByText('비어 있는 항목이 있습니다. 값을 입력하세요.')).toBeInTheDocument()
    expect(endpoints.saveSettings).not.toHaveBeenCalled()
  })

  it('can clear a percent field and type a new value', async () => {
    const { user } = await open()
    const fee = screen.getByLabelText('왕복 수수료율')

    await user.clear(fee)
    expect(fee).toHaveValue('') // no stray zero left behind to type after
    await user.type(fee, '0.07')

    expect(fee).toHaveValue('0.07')
  })

  it('edits the indicator parameters', async () => {
    const { user } = await open()
    await expand(user, '공통 지표', '스크리너 신호 (일봉)')

    await type(user, '52주 낙폭 기준', '-25')
    await type(user, 'RSI 기간', '10')
    await user.click(screen.getByRole('button', { name: '저장' }))

    await waitFor(() => expect(endpoints.saveSettings).toHaveBeenCalled())
    expect(saved().signal_params.screener.drawdown_threshold_pct).toBe(-25)
    expect(saved().signal_params.indicators.rsi_period).toBe(10)
  })

  it('chooses the signal bar length', async () => {
    const { user } = await open()

    await choose(user, '일봉')
    await user.click(screen.getByRole('button', { name: '저장' }))

    await waitFor(() => expect(endpoints.saveSettings).toHaveBeenCalled())
    expect(saved().signal_bar_length).toBe('1d')
  })

  it('sets the alert cooldown and switches the Telegram channel on', async () => {
    const { user } = await open()

    await type(user, '알림 쿨다운', '3')
    await user.click(screen.getByRole('switch', { name: '텔레그램 알림' }))
    await user.click(screen.getByRole('button', { name: '저장' }))

    await waitFor(() => expect(endpoints.saveSettings).toHaveBeenCalled())
    expect(saved().alert_cooldown_bars).toBe(3)
    expect(saved().channels).toEqual({ telegram: true })
  })

  it('switches polling off (stored as 0) and back on to the last period', async () => {
    const { user } = await open(makeSettings({ refresh_seconds: 30 }))

    await user.click(screen.getByRole('switch', { name: '자동 갱신' }))
    expect(screen.getByLabelText('갱신 주기')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '저장' }))
    await waitFor(() => expect(endpoints.saveSettings).toHaveBeenCalledTimes(1))
    expect(vi.mocked(endpoints.saveSettings).mock.calls[0][0].refresh_seconds).toBe(0)

    await user.click(screen.getByRole('switch', { name: '자동 갱신' }))
    await user.click(screen.getByRole('button', { name: '저장' }))
    await waitFor(() => expect(endpoints.saveSettings).toHaveBeenCalledTimes(2))
    expect(vi.mocked(endpoints.saveSettings).mock.calls[1][0].refresh_seconds).toBe(30)
  })

  it('goes back to the saved values', async () => {
    const { user } = await open()
    await type(user, '알림 쿨다운', '20')

    await user.click(screen.getByRole('button', { name: '되돌리기' }))

    expect(screen.getByLabelText('알림 쿨다운')).toHaveValue('6')
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()
  })

  it('puts the PRD defaults back into the parameters, to be saved explicitly', async () => {
    const settings = makeSettings()
    settings.signal_params.screener.drawdown_threshold_pct = -45
    const { user } = await open(settings)
    await expand(user, '스크리너 신호 (일봉)')
    expect(screen.getByLabelText('52주 낙폭 기준')).toHaveValue('-45.0')

    await user.click(screen.getByRole('button', { name: '파라미터 기본값' }))
    await user.click(await screen.findByRole('button', { name: /확인|OK/ }))

    await waitFor(() => expect(screen.getByLabelText('52주 낙폭 기준')).toHaveValue('-30.0'))
    expect(endpoints.saveSettings).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '저장' })).toBeEnabled()
  })

  it('shows the server message when a value is rejected', async () => {
    vi.mocked(endpoints.saveSettings).mockRejectedValue(apiError(422, 'refresh_seconds must be 0 or 10-3600'))
    const { user } = await open()
    await type(user, '알림 쿨다운', '2')

    await user.click(screen.getByRole('button', { name: '저장' }))

    expect(await screen.findByText('refresh_seconds must be 0 or 10-3600')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '저장' })).toBeEnabled() // nothing was lost
  })

  it('reports a failure to load and offers a retry', async () => {
    vi.mocked(endpoints.fetchSettings).mockRejectedValue(new Error('down'))
    renderApp(<SettingsPage />)

    expect(await screen.findByText('설정을 불러오지 못했습니다')).toBeInTheDocument()
    vi.mocked(endpoints.fetchSettings).mockResolvedValue(makeSettings())
    await userEvent.setup().click(screen.getByRole('button', { name: '다시 시도' }))

    expect(await screen.findByLabelText('왕복 수수료율')).toBeInTheDocument()
  })

  // --- channels -----------------------------------------------------------------------------

  it('says whether the server has the Telegram credentials', async () => {
    await open()
    expect(await screen.findByText('서버에 토큰이 설정되지 않음')).toBeInTheDocument()
  })

  it('shows the credentials as present when they are', async () => {
    vi.mocked(endpoints.fetchHealth).mockResolvedValue(
      makeHealth({ channels: { telegram: { enabled: true, configured: true } } }),
    )
    await open()

    expect(await screen.findByText('서버에 연결 정보가 있음')).toBeInTheDocument()
  })

  it('sends a test message and reports each channel', async () => {
    vi.mocked(endpoints.sendTestAlert).mockResolvedValue({
      channels: [{ channel: 'telegram', status: 'sent' }],
    })
    const { user } = await open()

    await user.click(screen.getByRole('button', { name: '시험 알림 보내기' }))

    expect(await screen.findByText('telegram: 시험 알림을 보냈습니다')).toBeInTheDocument()
  })

  it('explains why a test message could not be sent', async () => {
    vi.mocked(endpoints.sendTestAlert).mockRejectedValue(apiError(409, 'No outside channel is switched on and configured'))
    const { user } = await open()

    await user.click(screen.getByRole('button', { name: '시험 알림 보내기' }))

    expect(await screen.findByText('No outside channel is switched on and configured')).toBeInTheDocument()
  })

  it('shows a failed delivery with its reason', async () => {
    vi.mocked(endpoints.sendTestAlert).mockResolvedValue({
      channels: [{ channel: 'telegram', status: 'failed', error: 'telegram rejected the message (HTTP 401)' }],
    })
    const { user } = await open()

    await user.click(screen.getByRole('button', { name: '시험 알림 보내기' }))

    expect(await screen.findByText(/telegram rejected the message \(HTTP 401\)/)).toBeInTheDocument()
  })

  // --- presets ------------------------------------------------------------------------------

  const withPresets = () =>
    makeSettings({ presets: [{ name: '공격적', updated_at: '2026-10-16T10:00:00+09:00' }] })

  it('lists the saved presets', async () => {
    await open(withPresets())

    expect(screen.getByText('공격적')).toBeInTheDocument()
    expect(screen.getByText('2026-10-16 10:00')).toBeInTheDocument()
  })

  it('saves the current settings as a preset', async () => {
    vi.mocked(endpoints.savePreset).mockResolvedValue({ name: '보수적', updated_at: '2026-10-17T10:00:00+09:00' })
    const { user } = await open()

    await user.type(screen.getByPlaceholderText('프리셋 이름'), '  보수적 ')
    await user.click(screen.getByRole('button', { name: '현재 설정 저장' }))

    await waitFor(() => expect(endpoints.savePreset).toHaveBeenCalledWith('보수적'))
    expect(await screen.findByText('프리셋 "보수적"을 저장했습니다')).toBeInTheDocument()
  })

  it('will not save a preset while there are unsaved changes', async () => {
    const { user } = await open()
    await type(user, '알림 쿨다운', '2')

    await user.type(screen.getByPlaceholderText('프리셋 이름'), 'x')
    await user.click(screen.getByRole('button', { name: '현재 설정 저장' }))

    expect(await screen.findByText(/저장하지 않은 변경은 프리셋에 담기지 않습니다/)).toBeInTheDocument()
    expect(endpoints.savePreset).not.toHaveBeenCalled()
  })

  it('needs a name', async () => {
    await open()

    expect(screen.getByRole('button', { name: '현재 설정 저장' })).toBeDisabled()
  })

  it('loads a preset into the form', async () => {
    const loaded = makeSettings({ alert_cooldown_bars: 2, signal_bar_length: '30m', presets: withPresets().presets })
    vi.mocked(endpoints.loadPreset).mockResolvedValue(loaded)
    const { user } = await open(withPresets())

    await user.click(screen.getByRole('button', { name: '불러오기' }))

    await waitFor(() => expect(endpoints.loadPreset).toHaveBeenCalledWith('공격적'))
    await waitFor(() => expect(screen.getByLabelText('알림 쿨다운')).toHaveValue('2'))
    expect(screen.getByRole('radio', { name: '30분봉' })).toBeChecked()
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled() // it is already the saved state
  })

  it('asks before a preset replaces unsaved edits', async () => {
    const { user } = await open(withPresets())
    await type(user, '알림 쿨다운', '2')

    await user.click(screen.getByRole('button', { name: '불러오기' }))

    expect(await screen.findByText('저장하지 않은 변경이 사라집니다. 불러올까요?')).toBeInTheDocument()
    expect(endpoints.loadPreset).not.toHaveBeenCalled()
  })

  it('deletes a preset after confirmation', async () => {
    vi.mocked(endpoints.deletePreset).mockResolvedValue()
    const { user } = await open(withPresets())

    await user.click(screen.getByRole('button', { name: '삭제' }))
    await user.click(await screen.findByRole('button', { name: /확인|OK/ }))

    await waitFor(() => expect(endpoints.deletePreset).toHaveBeenCalledWith('공격적'))
  })
})
