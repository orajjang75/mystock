import { http, isUnauthorized } from './client'
import type {
  AlertsResponse,
  BacktestPresetRequest,
  BacktestPresetResult,
  BacktestRequest,
  BacktestRun,
  BacktestRunSummary,
  BarLength,
  Candle,
  CycleOut,
  CyclesResponse,
  FillCreate,
  FillResponse,
  HealthResponse,
  HoldingCreate,
  HoldingOut,
  IndicatorsResponse,
  PresetInfo,
  ResultsResponse,
  RunRequest,
  RunResponse,
  SettingsDocument,
  SettingsResponse,
  TestResponse,
  UserResponse,
  WatchlistItem,
} from './types'

export async function fetchMe(): Promise<UserResponse | null> {
  try {
    return (await http.get<UserResponse>('/api/auth/me')).data
  } catch (error) {
    if (isUnauthorized(error)) return null
    throw error
  }
}

export async function login(username: string, password: string): Promise<UserResponse> {
  return (await http.post<UserResponse>('/api/auth/login', { username, password })).data
}

export async function logout(): Promise<void> {
  await http.post('/api/auth/logout')
}

export async function fetchHealth(): Promise<HealthResponse> {
  // 503 carries a usable body too (the database is down): keep it instead of throwing.
  const response = await http.get<HealthResponse>('/api/health', { validateStatus: (s) => s === 200 || s === 503 })
  return response.data
}

export interface AlertQuery {
  unread_only?: boolean
  kind?: string
  code?: string
  limit?: number
  offset?: number
}

export async function fetchAlerts(params: AlertQuery = {}): Promise<AlertsResponse> {
  return (await http.get<AlertsResponse>('/api/alerts', { params })).data
}

export async function markAlertRead(id: number): Promise<void> {
  await http.post(`/api/alerts/${id}/read`)
}

export async function sendTestAlert(): Promise<TestResponse> {
  return (await http.post<TestResponse>('/api/alerts/test')).data
}

export async function fetchSettings(): Promise<SettingsResponse> {
  return (await http.get<SettingsResponse>('/api/settings')).data
}

export async function saveSettings(document: SettingsDocument): Promise<SettingsResponse> {
  return (await http.put<SettingsResponse>('/api/settings', document)).data
}

export async function savePreset(name: string): Promise<PresetInfo> {
  return (await http.post<PresetInfo>('/api/settings/presets', { name })).data
}

export async function loadPreset(name: string): Promise<SettingsResponse> {
  return (await http.post<SettingsResponse>(`/api/settings/presets/${encodeURIComponent(name)}/load`)).data
}

export async function deletePreset(name: string): Promise<void> {
  await http.delete(`/api/settings/presets/${encodeURIComponent(name)}`)
}

// --- screener, stocks, watchlist, holdings ---------------------------------------------------

export interface ResultsQuery {
  scan_date?: string
  min_score?: number
}

export async function fetchResults(params: ResultsQuery = {}): Promise<ResultsResponse> {
  return (await http.get<ResultsResponse>('/api/screener/results', { params })).data
}

export async function runScan(body: RunRequest = {}): Promise<RunResponse> {
  return (await http.post<RunResponse>('/api/screener/run', body)).data
}

export async function fetchCandles(code: string, bar: BarLength = '1d', limit = 250): Promise<Candle[]> {
  return (await http.get<Candle[]>(`/api/stocks/${code}/candles`, { params: { bar, limit } })).data
}

export async function fetchIndicators(
  code: string,
  bar: BarLength = '1d',
  limit = 250,
): Promise<IndicatorsResponse> {
  return (await http.get<IndicatorsResponse>(`/api/stocks/${code}/indicators`, { params: { bar, limit } })).data
}

export async function fetchWatchlist(): Promise<WatchlistItem[]> {
  return (await http.get<WatchlistItem[]>('/api/watchlist')).data
}

export async function addToWatchlist(code: string): Promise<void> {
  await http.post('/api/watchlist', { code })
}

export async function removeFromWatchlist(code: string): Promise<void> {
  await http.delete(`/api/watchlist/${code}`)
}

export async function fetchHoldings(): Promise<HoldingOut[]> {
  return (await http.get<HoldingOut[]>('/api/holdings')).data
}

export async function createHolding(body: HoldingCreate): Promise<HoldingOut> {
  return (await http.post<HoldingOut>('/api/holdings', body)).data
}

export async function fetchCycles(holdingId: number): Promise<CyclesResponse> {
  return (await http.get<CyclesResponse>(`/api/holdings/${holdingId}/cycles`)).data
}

export async function recordFill(holdingId: number, body: FillCreate): Promise<FillResponse> {
  return (await http.post<FillResponse>(`/api/holdings/${holdingId}/fills`, body)).data
}

export async function retryCycle(holdingId: number, cycleId: number): Promise<CycleOut> {
  return (await http.post<CycleOut>(`/api/holdings/${holdingId}/cycles/${cycleId}/retry`)).data
}

export async function abandonCycle(holdingId: number, cycleId: number): Promise<CycleOut> {
  return (await http.post<CycleOut>(`/api/holdings/${holdingId}/cycles/${cycleId}/abandon`)).data
}

// --- backtests -------------------------------------------------------------------------------

export async function createBacktest(body: BacktestRequest): Promise<BacktestRunSummary> {
  return (await http.post<BacktestRunSummary>('/api/backtests', body)).data
}

export async function fetchBacktests(): Promise<BacktestRunSummary[]> {
  return (await http.get<BacktestRunSummary[]>('/api/backtests')).data
}

export async function fetchBacktest(id: number): Promise<BacktestRun> {
  return (await http.get<BacktestRun>(`/api/backtests/${id}`)).data
}

export async function deleteBacktest(id: number): Promise<void> {
  await http.delete(`/api/backtests/${id}`)
}

export async function fetchBacktestReport(id: number): Promise<string> {
  return (await http.get<string>(`/api/backtests/${id}/report`, { responseType: 'text' })).data
}

export async function saveBacktestPreset(id: number, body: BacktestPresetRequest): Promise<BacktestPresetResult> {
  return (await http.post<BacktestPresetResult>(`/api/backtests/${id}/preset`, body)).data
}
