# 신호 대응표: PRD 6장 표 행 → 코드

`backend/app/engine/` 의 함수와 PRD 6장 표의 행을 1:1로 연결한다. 표가 신호 정의의 유일한 기준이며, 표와 코드가 다르면 코드를 고친다. 이 파일의 행은 `tests/engine/test_signal_map.py` 가 PRD 표와 대조하고, 적힌 함수가 실제로 있는지 확인한다.

함수 이름은 "모듈.함수" 형식이다. 모든 함수는 시리즈 한 개(종목 하나) 또는 종목을 열로 둔 DataFrame(여러 종목)을 받고, 같은 모양으로 돌려준다. 기본값은 전부 `engine/params.py` 의 `DEFAULT_PARAMS` 에서 온다.

| 용도 | 신호 | 함수 | 근거 값을 돌려주는 함수 | 메모 |
| --- | --- | --- | --- | --- |
| 스크리너 · 안전 필터 | 거래대금 | `screener_signals.liquidity_ok` | `screener_signals.avg_trading_value` | 20거래일이 모이기 전에는 False |
| 스크리너 · 바닥 게이트 | 52주 고점 대비 낙폭 | `screener_signals.drawdown_52w_ok` | `screener_signals.drawdown_52w_pct` | 최고가는 고가(high)의 252거래일 최댓값. 252봉이 모이기 전에는 False. 완화 기준은 `params.ScreenerParams` 의 `drawdown_relaxed_threshold_pct` |
| 스크리너 · 바닥 게이트 | 이격도 | `screener_signals.disparity_oversold` | `screener_signals.disparity_pct` | |
| 공통 지표 (스크리너·분봉) | 볼린저 %B·밴드폭 | `indicators.bollinger` | `indicators.price_pct_b` | 하단·중심·상단·%B·밴드폭을 한 DataFrame으로. 표준편차는 모집단(ddof=0). 볼린저 신호 4개가 이 결과를 공유 |
| 스크리너 · 바닥 게이트 | 볼린저 하단 이탈 이력 | `screener_signals.bollinger_break_history` | `indicators.bollinger` | %B < 0 (0은 해당 없음) |
| 스크리너 · 반전 | RSI 상향 돌파 | `screener_signals.rsi_cross_up` | `indicators.rsi` | |
| 스크리너 · 반전 | 강세 다이버전스 | `screener_signals.bullish_divergence` | `swings.last_two_swings` | 스윙 저점 확정 기준 `swing_confirm_bars`(기본 3)는 설정. 상태 판정(아래 참고) |
| 스크리너 · 반전 | 볼린저 복귀 | `screener_signals.bollinger_reentry` | `indicators.bollinger` | |
| 스크리너 · 확인 | MACD 골든크로스 | `screener_signals.macd_golden_cross` | `indicators.macd` | `below_zero_only` 옵션 |
| 스크리너 · 확인 | 종가의 20일선 회복 | `screener_signals.close_above_ma` | `indicators.sma` | |
| 스크리너 · 확인 | 5일선 우위 | `screener_signals.ma_short_above_long` | `indicators.sma` | |
| 스크리너 · 확인 | 하락 파동 고점 돌파 | `screener_signals.downwave_high_breakout` | `swings.last_swing_high` | 확정된 최근 스윙 고점 위에 종가가 있는 동안 계속 True (상태) |
| 스크리너 · 확인 | OBV 전환 | `screener_signals.obv_turn_up` | `indicators.obv` | OBV가 20일 평균 위로 올라선 첫 봉만 True (교차 당일) |
| 스크리너 · 거래량 | 평균 대비 거래량 | `screener_signals.volume_surge` | `screener_signals.volume_ratio` | `multiple=2.0`, 3배 가산은 `multiple=3.0` 으로 한 번 더 호출. 평균에 당일 포함 |
| 스크리너 · 수급 | 외국인 연속 순매수 | `screener_signals.consecutive_net_buy` | | 외국인 열을 넘긴다 |
| 스크리너 · 수급 | 기관 연속 순매수 | `screener_signals.consecutive_net_buy` | | 기관 열을 넘긴다 |
| 스크리너 · 수급 | 외국인·기관 순매수 강도 | `screener_signals.net_buy_strength` | `screener_signals.net_buy_strength_pct` | |
| 스크리너 · 수급 | 순매수 전환 | `screener_signals.net_buy_turnaround` | | |
| 매도 (분봉) | RSI 과열 이탈 | `alert_signals.rsi_overbought_exit` | `indicators.rsi` | |
| 매도 (분봉) | 볼린저 상단 복귀 | `alert_signals.bollinger_upper_reentry` | `indicators.bollinger` | |
| 매도 (분봉) | MACD 약화 | `alert_signals.macd_weakening` | `indicators.macd` | 데드크로스 또는 양수 히스토그램 N봉 연속 감소 |
| 매도 (분봉) | 약세 다이버전스 | `alert_signals.bearish_divergence` | `swings.last_two_swings` | RSI 또는 MACD 히스토그램 |
| 매도 (분봉) | ATR 기반 이격도 과열 | `alert_signals.atr_disparity_overheat` | `alert_signals.atr_disparity` | ATR은 `indicators.atr` |
| 매도 (분봉 + 일봉 수급) | 수급 이탈 | `alert_signals.flow_exit` | `alert_signals.flow_exit_at_bars` | 일봉 기준. 분봉에는 `flow_exit_at_bars` 로 직전 확정 일봉 값을 붙인다. `signal` 과 `unreflected`('수급 미반영') 를 돌려준다. 매도 후보 한 개로 센다 (`alert_signals.sell_decision`) |
| 재매수 (분봉) | RSI 반등 | `alert_signals.rsi_rebound` | `indicators.rsi` | |
| 재매수 (분봉) | 볼린저 지지 | `alert_signals.bollinger_support` | `indicators.price_pct_b` | 기준선 기본 0(하단 지지), 0.5(중심선 지지)는 설정 |
| 재매수 (분봉) | MACD 골든크로스 | `screener_signals.macd_golden_cross` | `indicators.macd` | 스크리너와 같은 함수 (`alert_signals` 에서도 import 가능) |
| 재매수 (분봉) | 가격 조건 | `alert_signals.price_condition` | `alert_signals.rebuy_target_price` | 가격 조건만으로는 신호가 아니다. 2개 이상 확인은 `alert_signals.rebuy_decision` |
| 재매수 (분봉 + 일봉 수급) | 수급 필터 | `alert_signals.flow_exit` | `alert_signals.flow_exit_at_bars` | 수급 이탈과 같은 조건. 확인 개수에는 넣지 않고, `alert_signals.rebuy_decision` 이 보류·경고로 바꾼다. 수급 데이터가 없으면 적용하지 않는다 |
| 강제 매도 (일봉) | 보유 종목 5일선 이탈 | `force_sell.ma_breakdown` | `indicators.sma` | 종목 일봉 종가를 넘긴다 |
| 강제 매도 (일봉) | KOSPI 지수 5일선 이탈 | `force_sell.ma_breakdown` | `indicators.sma` | 지수 일봉 종가를 넘긴다. 종목·지수를 함께 보려면 `force_sell.force_sell` |

표의 행은 아니지만 신호 계산에 필요한 보조 함수:

| 함수 | 용도 |
| --- | --- |
| `confirmed.confirmed_daily`, `confirmed.confirmed_intraday` | 확정되지 않은 봉을 신호 계산 전에 제거 (직전·현재 정의). 60분봉은 앞 30분만 모인 봉(`is_complete` False)도 제거 |
| `holding_rules.daily_downtrend` | A-6 일봉 하락 추세: 종가 < 60일선 이고 60일선이 5거래일 전보다 낮음. 하락이 아니면(횡보 포함) 사이클을 돌린다 |
| `holding_rules.atr_stop_price`, `holding_rules.stop_breached` | A-8 ATR 손절선 = 평균단가 − 2 × 일봉 ATR(14), 현재가가 손절선보다 낮으면 이탈 |
| `force_sell.ma_recovered` | A-13: 5일선이 20일선 위로 회복했는지 (= 5일선 우위) |
| `screener_signals.flow_missing` | '수급 미반영' 판정 |
| `cycle_signals.sell_signals`, `cycle_signals.rebuy_confirmations`, `cycle_signals.rebuy_signals` | A-2·A-5: 매도 후보 6개와 재매수 반전 확인 3개를 모든 봉에 대해 한 번에 계산한다. 알림 엔진은 마지막 행만, 사이클 백테스트는 모든 행을 읽으므로 둘이 같은 판정을 쓴다 |
| `panel.to_wide` | 종목별 DataFrame을 필드별 wide DataFrame으로 변환 |
| `params.SignalParams` | 모든 기본값의 단일 정의. 설정 화면이 같은 모델을 쓴다 |

## 표에 없어서 정한 해석

표의 정의는 바꾸지 않았다. 표가 말하지 않는 부분만 아래처럼 정했고, 바꾸려면 먼저 확인이 필요하다.

- **기간 창**: "최근 N거래일"은 모두 현재 봉을 포함한다 (거래대금, 이전 N일 합, 거래량 평균 등).
- **상태와 이벤트**: 표에 "직전 … 이고 현재 …"가 적힌 행만 한 봉짜리 이벤트이고, 나머지는 조건이 유지되는 동안 True인 상태다. 사용자 확인: 하락 파동 고점 돌파는 상태, OBV 전환은 교차 당일, 볼린저 지지 기준선은 0.
- **다이버전스**: 최근 확정 스윙 두 개를 비교하고, 두 스윙이 모두 최근 30봉 안에 있을 때 True이며 그 상태가 이어진다. 같은 신호의 반복 알림은 A-10 쿨다운이 막는다. 4장 S-3은 "RSI·MACD 저점"이라 쓰지만 6장 표는 RSI만 적어서 표를 따랐다.
- **스윙 확정**: 좌우 `k`봉보다 낮은(높은) 봉은 `k`봉이 지난 뒤에 확정되고, 그 전에는 신호에 쓰지 않는다.
- **52주 최고가**: 고가(high)의 최댓값. 종가가 아니다.
- **볼린저**: 표준편차는 모집단(ddof=0), %B는 밴드 폭이 0이면 NaN.
- **RSI·ATR·EMA**: 첫 `N`봉의 단순 평균을 시드로 쓰는 Wilder/EMA 평활. 손실이 없으면 RSI는 100.
- **이동평균·지표 준비 기간**: 창이 다 차기 전에는 NaN이고, NaN이 들어간 조건은 False다.
- **수급 미반영**: 최근 N일에 외국인·기관 값이 비었거나 이력이 N일보다 짧으면 True. 이때 수급 이탈은 False(건너뜀), 수급 필터는 적용하지 않는다.
- **부동소수 오차**: 비율로 계산한 비교(낙폭, 이격도, 거래량 배수, 순매수 강도, ATR 이격)는 소수 8자리로 반올림한 뒤 기준과 비교한다. 기준값과 정확히 같은 값이 오차 때문에 빠지지 않게 하려는 것이다.
- **수수료·거래세 기본값**: 왕복 수수료 0.03%, 매도 거래세 0.18%는 임시값이다. 11단계에서 공식 자료로 확정한다.
- **A-6, A-8 정의**: PRD 6장 표에 없는 두 규칙은 사용자와 확인한 정의를 따른다. 추세는 60일선·5거래일 기울기(`params.TrendParams`), 손절선은 평균단가 − 2×일봉 ATR(`params.StopParams`)이다.
- **미구현**: S-5의 선택 옵션 "전일 대비 거래량 배수"는 6장 표에 없어 만들지 않았다.
