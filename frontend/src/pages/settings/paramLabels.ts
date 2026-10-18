// Korean labels for every field of the backend's SignalParams (docs/PRD.md 6장).
// A test compares this table with the generated schema, so the two cannot drift apart.

export interface ParamMeta {
  label: string
  help?: string
  unit?: string
  /** The API stores a fraction (0.0018); the form shows percent (0.18). */
  percent?: boolean
  /** Fields shown in a dedicated card instead of the generic parameter list. */
  card?: 'fees'
  options?: Record<string, string>
}

export const GROUP_TITLES: Record<string, string> = {
  indicators: '공통 지표',
  screener: '스크리너 신호 (일봉)',
  score: '스크리너 배점',
  scan: '스캔 결과 선택',
  sell: '매도 신호 (분봉)',
  rebuy: '재매수 신호와 목표가',
  force_sell: '강제 매도 (A-13)',
  trend: '일봉 추세 필터 (A-6)',
  stop: 'ATR 손절선 (A-8)',
}

export const PARAM_LABELS: Record<string, ParamMeta> = {
  // 공통 지표
  'indicators.rsi_period': { label: 'RSI 기간', unit: '봉' },
  'indicators.bollinger_window': { label: '볼린저 기간', unit: '봉' },
  'indicators.bollinger_k': { label: '볼린저 표준편차 배수' },
  'indicators.macd_fast': { label: 'MACD 단기 EMA', unit: '봉' },
  'indicators.macd_slow': { label: 'MACD 장기 EMA', unit: '봉' },
  'indicators.macd_signal': { label: 'MACD 시그널', unit: '봉' },
  'indicators.atr_period': { label: 'ATR 기간', unit: '봉' },
  // 스크리너 신호
  'screener.min_avg_trading_value': { label: '최소 일평균 거래대금', unit: '원', help: '안전 필터. 기본 10억 원' },
  'screener.liquidity_window': { label: '거래대금 평균 기간', unit: '거래일' },
  'screener.drawdown_window': { label: '52주 낙폭 기간', unit: '거래일' },
  'screener.drawdown_threshold_pct': { label: '52주 낙폭 기준', unit: '%', help: '고점 대비 이 값 이하일 때 바닥 게이트 통과' },
  'screener.drawdown_relaxed_threshold_pct': { label: '완화한 낙폭 기준', unit: '%', help: '후보가 적을 때 쓰는 기준' },
  'screener.disparity_window': { label: '이격도 이동평균 기간', unit: '거래일' },
  'screener.disparity_threshold_pct': { label: '이격도 과매도 기준', unit: '%' },
  'screener.bollinger_break_lookback': { label: '볼린저 하단 이탈 이력 기간', unit: '거래일' },
  'screener.rsi_cross_level': { label: 'RSI 상향 돌파 기준값' },
  'screener.divergence_lookback': { label: '다이버전스 탐색 기간', unit: '봉' },
  'screener.swing_confirm_bars': { label: '스윙 확정 봉 수', unit: '봉', help: '좌우 이 봉 수보다 낮은(높은) 봉을 스윙으로 인정' },
  'screener.macd_cross_below_zero_only': { label: 'MACD 골든크로스를 0선 아래만 인정' },
  'screener.ma_short_window': { label: '단기 이동평균', unit: '거래일' },
  'screener.ma_long_window': { label: '장기 이동평균', unit: '거래일' },
  'screener.obv_ma_window': { label: 'OBV 평균 기간', unit: '거래일' },
  'screener.volume_window': { label: '평균 거래량 기간', unit: '거래일' },
  'screener.volume_multiple': { label: '거래량 급증 배수', unit: '배' },
  'screener.volume_strong_multiple': { label: '거래량 강한 급증 배수', unit: '배' },
  'screener.flow_consecutive_days': { label: '연속 순매수 일수', unit: '거래일' },
  'screener.flow_strength_window': { label: '순매수 강도 기간', unit: '거래일' },
  'screener.flow_strength_threshold_pct': { label: '순매수 강도 기준', unit: '%' },
  'screener.flow_turnaround_window': { label: '순매수 전환 비교 기간', unit: '거래일' },
  // 스크리너 배점
  'score.reversal_points': { label: '반전 신호 배점', unit: '점' },
  'score.confirmation_points': { label: '확인 신호 배점', unit: '점' },
  'score.volume_points': { label: '거래량 배점', unit: '점' },
  'score.flow_points': { label: '수급 배점', unit: '점' },
  'score.volume_multiple_points': { label: '거래량 2배 득점', unit: '점', help: '3배 득점 대비 비율로 반영' },
  'score.volume_strong_multiple_points': { label: '거래량 3배 득점', unit: '점' },
  // 스캔 결과 선택
  'scan.min_score': { label: '최소 점수 컷', unit: '점' },
  'scan.few_candidates_threshold': { label: '후보가 적다고 보는 개수', unit: '개' },
  'scan.few_candidates_action': {
    label: '후보가 적을 때',
    options: { none: '변경 없음', relax_drawdown: '낙폭 기준 완화', rank_by_decline: '하락률 순위로 전환' },
  },
  'scan.decline_rank_top_n': { label: '하락률 순위 후보 수', unit: '개' },
  // 매도 신호
  'sell.rsi_overbought': { label: 'RSI 과열 기준값' },
  'sell.bollinger_upper_level': { label: '볼린저 상단 기준 (%B)' },
  'sell.macd_weak_bars': { label: 'MACD 히스토그램 연속 감소 봉 수', unit: '봉' },
  'sell.divergence_lookback': { label: '약세 다이버전스 탐색 기간', unit: '봉' },
  'sell.swing_confirm_bars': { label: '스윙 확정 봉 수', unit: '봉' },
  'sell.atr_disparity_window': { label: 'ATR 이격도 이동평균', unit: '봉' },
  'sell.atr_disparity_multiple': { label: 'ATR 이격도 과열 배수', unit: '배' },
  'sell.flow_exit_days': { label: '수급 이탈 연속 일수', unit: '거래일' },
  'sell.min_overlap': { label: '매도 알림에 필요한 겹침 개수', unit: '개' },
  'sell.sell_fraction': { label: '매도 제안 비율', unit: '%', percent: true, help: '보유량 대비. 전량은 제안하지 않음' },
  // 재매수
  'rebuy.rsi_rebound_low': { label: 'RSI 반등 하한' },
  'rebuy.rsi_rebound_high': { label: 'RSI 반등 상한' },
  'rebuy.bollinger_support_level': { label: '볼린저 지지 기준선 (%B)', help: '0 = 하단 지지, 0.5 = 중심선 지지' },
  'rebuy.min_confirmations': { label: '재매수 알림에 필요한 확인 개수', unit: '개' },
  'rebuy.expiry_trading_days': { label: '재매수 대기 만료', unit: '거래일' },
  'rebuy.target_gain': { label: '재매수 목표 이득', unit: '%', percent: true },
  'rebuy.round_trip_fee_rate': { label: '왕복 수수료율', unit: '%', percent: true, card: 'fees' },
  'rebuy.sell_tax_rate': { label: '매도 거래세율', unit: '%', percent: true, card: 'fees' },
  // 강제 매도, 추세, 손절
  'force_sell.ma_short_window': { label: '단기 이동평균', unit: '거래일' },
  'force_sell.ma_long_window': { label: '장기 이동평균', unit: '거래일' },
  'trend.ma_window': { label: '추세 이동평균', unit: '거래일' },
  'trend.slope_bars': { label: '기울기 비교 간격', unit: '거래일' },
  'stop.atr_multiple': { label: '손절선 ATR 배수', unit: '배', help: '손절선 = 평균단가 − 배수 × 일봉 ATR' },
}

/** The groups in display order. */
export const GROUP_ORDER = Object.keys(GROUP_TITLES)

/** ``items`` (each with a "group.field" key) in the order of the label table. */
export function inDisplayOrder<T extends { key: string }>(items: T[]): T[] {
  const order = Object.keys(PARAM_LABELS)
  return [...items].sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key))
}
