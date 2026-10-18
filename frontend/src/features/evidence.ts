import dayjs from 'dayjs'
import { formatNumber } from '../lib/format'

/** The signals an alert names, in the words of PRD 6장. */
export const SIGNAL_LABELS: Record<string, string> = {
  rsi_overbought_exit: 'RSI 과매수 이탈',
  bollinger_upper_reentry: '볼린저 상단 재진입',
  macd_weakening: 'MACD 약화',
  bearish_divergence: '약세 다이버전스',
  atr_disparity_overheat: 'ATR 이격 과열',
  flow_exit: '일봉 수급 이탈',
  price_condition: '재매수 목표가 이하',
  rsi_rebound: 'RSI 반등',
  bollinger_support: '볼린저 하단 지지',
  macd_golden_cross: 'MACD 골든크로스',
}

const LABELS: Record<string, string> = {
  signals: '충족한 신호',
  overlap: '겹친 매도 신호 수',
  confirmations: '겹친 재매수 신호 수',
  bar_length: '신호 봉',
  rsi: 'RSI',
  pct_b: '%B',
  quantity_increase: '예상 수량 증가분',
  sold_quantity: '매도 수량',
  held_by_flow_filter: '수급 이탈로 보류',
  flow_unreflected: '수급 미반영',
  stop_price: 'ATR 손절선',
  avg_price: '평균단가',
  daily_atr: '일봉 ATR',
  daily_downtrend: '일봉 하락 추세',
  stock_ma_breakdown: '종목 5일선 이탈',
  kospi_ma_breakdown: 'KOSPI 5일선 이탈',
  latency_seconds: '봉 마감 후 알림까지(초)',
  bar_end: '신호 봉 마감',
  message: '내용',
  sources: '대상',
}

// Internal ids the user has no use for.
const HIDDEN = new Set(['cycle_id', 'choices'])

const BAR_LENGTH: Record<string, string> = { '30m': '30분봉', '60m': '60분봉', '1d': '일봉' }

export interface EvidenceRow {
  key: string
  label: string
  value: string
}

function formatValue(key: string, value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => (key === 'signals' ? (SIGNAL_LABELS[String(v)] ?? String(v)) : String(v))).join(' · ') || '-'
  if (typeof value === 'boolean') return value ? '예' : '아니오'
  if (typeof value === 'number') return Number.isInteger(value) ? formatNumber(value) : formatNumber(value, 2)
  if (value === null || value === undefined) return '-'
  const text = String(value)
  if (key === 'bar_length') return BAR_LENGTH[text] ?? text
  if (key === 'bar_end') return dayjs(text).format('MM-DD HH:mm')
  return text
}

/** The indicator values behind an alert as label/value rows, hiding internal ids. */
export function evidenceRows(evidence: Record<string, unknown>): EvidenceRow[] {
  return Object.entries(evidence)
    .filter(([key]) => !HIDDEN.has(key))
    .map(([key, value]) => ({ key, label: LABELS[key] ?? key, value: formatValue(key, value) }))
}
