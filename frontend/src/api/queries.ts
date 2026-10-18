import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  abandonCycle,
  addToWatchlist,
  createBacktest,
  createHolding,
  deleteBacktest,
  fetchBacktest,
  fetchBacktests,
  deletePreset,
  fetchCycles,
  fetchAlerts,
  fetchCandles,
  fetchHoldings,
  fetchIndicators,
  fetchResults,
  fetchWatchlist,
  removeFromWatchlist,
  runScan,
  fetchHealth,
  fetchMe,
  fetchSettings,
  loadPreset,
  login,
  logout,
  markAlertRead,
  recordFill,
  retryCycle,
  saveBacktestPreset,
  saveSettings,
  savePreset,
  sendTestAlert,
  type AlertQuery,
  type ResultsQuery,
} from './endpoints'
import type { BacktestPresetRequest, BacktestRequest, BarLength, FillCreate, HoldingCreate, RunRequest, SettingsDocument, SettingsResponse } from './types'

export const queryKeys = {
  me: ['me'] as const,
  health: ['health'] as const,
  alerts: (query: AlertQuery) => ['alerts', query] as const,
  settings: ['settings'] as const,
  results: (query: ResultsQuery) => ['results', query] as const,
  candles: (code: string, bar: BarLength, limit: number) => ['candles', code, bar, limit] as const,
  indicators: (code: string, bar: BarLength, limit: number) => ['indicators', code, bar, limit] as const,
  watchlist: ['watchlist'] as const,
  holdings: ['holdings'] as const,
  cycles: (holdingId: number) => ['cycles', holdingId] as const,
  backtests: ['backtests'] as const,
  backtest: (id: number) => ['backtest', id] as const,
}

export const DEFAULT_REFRESH_SECONDS = 60

/** The polling period in milliseconds, or ``false`` when polling is switched off (PRD 7장). */
export function pollingInterval(refreshSeconds: number | undefined): number | false {
  if (refreshSeconds === undefined) return DEFAULT_REFRESH_SECONDS * 1000
  return refreshSeconds > 0 ? refreshSeconds * 1000 : false
}

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: fetchSettings })
}

/** Every polled query uses this period; it follows the saved setting (default 60 seconds). */
export function usePollingMs(): number | false {
  const { data } = useSettings()
  return pollingInterval(data?.refresh_seconds)
}

export function useMe() {
  return useQuery({ queryKey: queryKeys.me, queryFn: fetchMe, retry: false, staleTime: Infinity })
}

export function useHealth() {
  const refetchInterval = usePollingMs()
  return useQuery({ queryKey: queryKeys.health, queryFn: fetchHealth, refetchInterval })
}

export function useAlerts(query: AlertQuery = {}) {
  const refetchInterval = usePollingMs()
  return useQuery({
    queryKey: queryKeys.alerts(query),
    queryFn: () => fetchAlerts(query),
    refetchInterval,
    placeholderData: keepPreviousData,
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) => login(username, password),
    onSuccess: (user) => client.setQueryData(queryKeys.me, user),
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => logout(),
    onSuccess: () => {
      client.clear()
      client.setQueryData(queryKeys.me, null)
    },
  })
}

export function useMarkAlertRead() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => markAlertRead(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ['alerts'] }),
  })
}

export function useSendTestAlert() {
  return useMutation({ mutationFn: () => sendTestAlert() })
}

function useStoreSettings() {
  const client = useQueryClient()
  return (settings: SettingsResponse) => {
    client.setQueryData(queryKeys.settings, settings)
    // the polling period and channels may have changed what other screens show
    void client.invalidateQueries({ queryKey: queryKeys.health })
  }
}

export function useSaveSettings() {
  const store = useStoreSettings()
  return useMutation({ mutationFn: (document: SettingsDocument) => saveSettings(document), onSuccess: store })
}

export function useSavePreset() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => savePreset(name),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.settings }),
  })
}

export function useLoadPreset() {
  const store = useStoreSettings()
  return useMutation({ mutationFn: (name: string) => loadPreset(name), onSuccess: store })
}

export function useDeletePreset() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => deletePreset(name),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.settings }),
  })
}

// --- screener, charts, watchlist, holdings ---------------------------------------------------

export function useResults(query: ResultsQuery = {}) {
  return useQuery({
    queryKey: queryKeys.results(query),
    queryFn: () => fetchResults(query),
    placeholderData: keepPreviousData,
  })
}

export function useRunScan() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: RunRequest) => runScan(body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['results'] })
      void client.invalidateQueries({ queryKey: queryKeys.watchlist })
      void client.invalidateQueries({ queryKey: queryKeys.health })
    },
  })
}

export function useCandles(code: string | undefined, bar: BarLength = '1d', limit = 250) {
  return useQuery({
    queryKey: queryKeys.candles(code ?? '', bar, limit),
    queryFn: () => fetchCandles(code as string, bar, limit),
    enabled: Boolean(code),
  })
}

export function useIndicators(code: string | undefined, bar: BarLength = '1d', limit = 250) {
  return useQuery({
    queryKey: queryKeys.indicators(code ?? '', bar, limit),
    queryFn: () => fetchIndicators(code as string, bar, limit),
    enabled: Boolean(code),
  })
}

/** Closing prices for several stocks at once, for the small trend lines. */
export function useSparklines(codes: string[], limit = 40) {
  return useQueries({
    queries: codes.map((code) => ({
      queryKey: queryKeys.candles(code, '1d', limit),
      queryFn: () => fetchCandles(code, '1d', limit),
      staleTime: 60_000,
    })),
  })
}

export function useWatchlist() {
  const refetchInterval = usePollingMs()
  return useQuery({ queryKey: queryKeys.watchlist, queryFn: fetchWatchlist, refetchInterval })
}

/** Adds or removes a stock; the watchlist, the results' stars and the dashboard follow. */
export function useToggleWatch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ code, watched }: { code: string; watched: boolean }) =>
      watched ? removeFromWatchlist(code) : addToWatchlist(code),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.watchlist })
      void client.invalidateQueries({ queryKey: ['results'] })
    },
  })
}

export function useHoldings() {
  const refetchInterval = usePollingMs()
  return useQuery({ queryKey: queryKeys.holdings, queryFn: fetchHoldings, refetchInterval })
}

export function useCycles(holdingId: number | undefined) {
  const refetchInterval = usePollingMs()
  return useQuery({
    queryKey: queryKeys.cycles(holdingId ?? 0),
    queryFn: () => fetchCycles(holdingId as number),
    enabled: holdingId !== undefined,
    refetchInterval,
  })
}

/** Everything a holding's state change touches: its row, cycle history, alerts and the chart's markers. */
function useRefreshHoldings() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: queryKeys.holdings })
    void client.invalidateQueries({ queryKey: ['cycles'] })
    void client.invalidateQueries({ queryKey: ['alerts'] })
  }
}

export function useCreateHolding() {
  const refresh = useRefreshHoldings()
  return useMutation({ mutationFn: (body: HoldingCreate) => createHolding(body), onSuccess: refresh })
}

export function useRecordFill() {
  const refresh = useRefreshHoldings()
  return useMutation({
    mutationFn: ({ holdingId, body }: { holdingId: number; body: FillCreate }) => recordFill(holdingId, body),
    onSuccess: refresh,
  })
}

export function useRetryCycle() {
  const refresh = useRefreshHoldings()
  return useMutation({
    mutationFn: ({ holdingId, cycleId }: { holdingId: number; cycleId: number }) => retryCycle(holdingId, cycleId),
    onSuccess: refresh,
  })
}

export function useAbandonCycle() {
  const refresh = useRefreshHoldings()
  return useMutation({
    mutationFn: ({ holdingId, cycleId }: { holdingId: number; cycleId: number }) => abandonCycle(holdingId, cycleId),
    onSuccess: refresh,
  })
}

// --- backtests -------------------------------------------------------------------------------

const ACTIVE = new Set(['queued', 'running'])
const BACKTEST_POLL_MS = 2000

export function useBacktests() {
  return useQuery({
    queryKey: queryKeys.backtests,
    queryFn: fetchBacktests,
    // a run in progress is watched closely; otherwise nothing changes by itself
    refetchInterval: (query) => (query.state.data?.some((run) => ACTIVE.has(run.status)) ? BACKTEST_POLL_MS : false),
  })
}

export function useBacktest(id: number | undefined) {
  return useQuery({
    queryKey: queryKeys.backtest(id ?? 0),
    queryFn: () => fetchBacktest(id as number),
    enabled: id !== undefined,
    refetchInterval: (query) => (query.state.data && ACTIVE.has(query.state.data.status) ? BACKTEST_POLL_MS : false),
  })
}

export function useCreateBacktest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: BacktestRequest) => createBacktest(body),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.backtests }),
  })
}

export function useDeleteBacktest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteBacktest(id),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.backtests }),
  })
}

/** Keep a run's parameters as a preset; with ``apply`` they become the current settings. */
export function useSaveBacktestPreset() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: BacktestPresetRequest }) => saveBacktestPreset(id, body),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.settings }),
  })
}
