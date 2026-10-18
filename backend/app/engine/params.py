"""Every default of PRD 6장 in one pydantic model.

The settings screen and API (PRD 7장, 9장) edit this same model, and every engine function takes
its default arguments from here, so a default is defined exactly once. Percentages are in
percent units (-30.0 means -30%); rates such as fees are fractions (0.0018 means 0.18%).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class IndicatorParams(_Params):
    """공통 지표 (스크리너·분봉)."""

    rsi_period: int = Field(14, ge=2)
    bollinger_window: int = Field(20, ge=2)
    bollinger_k: float = Field(2.0, gt=0)
    macd_fast: int = Field(12, ge=1)
    macd_slow: int = Field(26, ge=2)
    macd_signal: int = Field(9, ge=1)
    atr_period: int = Field(14, ge=1)


class ScreenerParams(_Params):
    """스크리너 신호 (일봉)."""

    # 안전 필터
    min_avg_trading_value: int = Field(1_000_000_000, ge=0)  # 10억 원
    liquidity_window: int = Field(20, ge=1)
    # 바닥 게이트
    drawdown_window: int = Field(252, ge=2)
    drawdown_threshold_pct: float = -30.0
    drawdown_relaxed_threshold_pct: float = -20.0  # 후보가 너무 적을 때 (S-2)
    disparity_window: int = Field(20, ge=2)
    disparity_threshold_pct: float = -8.0
    bollinger_break_lookback: int = Field(10, ge=1)
    # 반전
    rsi_cross_level: float = 30.0
    divergence_lookback: int = Field(30, ge=2)
    swing_confirm_bars: int = Field(3, ge=1)  # 스윙 확정: 좌우 N봉보다 낮(높)은 봉, N봉 뒤 확정
    # 확인
    macd_cross_below_zero_only: bool = False
    ma_short_window: int = Field(5, ge=1)
    ma_long_window: int = Field(20, ge=2)
    obv_ma_window: int = Field(20, ge=2)
    # 거래량
    volume_window: int = Field(20, ge=1)
    volume_multiple: float = Field(2.0, gt=0)
    volume_strong_multiple: float = Field(3.0, gt=0)
    # 수급
    flow_consecutive_days: int = Field(3, ge=1)
    flow_strength_window: int = Field(5, ge=1)
    flow_strength_threshold_pct: float = 2.0
    flow_turnaround_window: int = Field(5, ge=1)


class ScoreParams(_Params):
    """스크리너 배점 (초안, S-6: 화면에서 바꿀 수 있다).

    Each section's weight is split equally over its signals (반전 3개, 확인 5개, 수급 4개).
    거래량 earns ``volume_points`` at 3x and ``volume_points * volume_multiple_points /
    volume_strong_multiple_points`` (14 of 20) at 2x. The total is always shown on a 0-100
    scale: the earned points are divided by the sum of the weights that applied.
    """

    reversal_points: float = Field(30, ge=0)
    confirmation_points: float = Field(30, ge=0)
    volume_points: float = Field(20, ge=0)
    flow_points: float = Field(20, ge=0)
    volume_multiple_points: float = Field(14, ge=0)  # 2배 이상
    volume_strong_multiple_points: float = Field(20, gt=0)  # 3배 이상


class ScanParams(_Params):
    """스캔 결과 선택 옵션 (S-2, S-6)."""

    min_score: float = Field(0.0, ge=0, le=100)  # 최소 점수 컷
    # 바닥 게이트 통과 종목이 ``few_candidates_threshold`` 개보다 적을 때 (S-2).
    few_candidates_threshold: int = Field(5, ge=1)
    few_candidates_action: Literal["none", "relax_drawdown", "rank_by_decline"] = "none"
    decline_rank_top_n: int = Field(10, ge=1)  # rank_by_decline: 52주 낙폭이 큰 순서로 N개


class TrendParams(_Params):
    """A-6 일봉 추세 필터 (PRD 6장 표 밖, 사용자 확인 정의)."""

    ma_window: int = Field(60, ge=2)
    slope_bars: int = Field(5, ge=1)  # 기울기: 오늘 이동평균과 N거래일 전 이동평균의 차


class StopParams(_Params):
    """A-8 ATR 기반 손절선 (PRD 6장 표 밖, 사용자 확인 정의)."""

    atr_multiple: float = Field(2.0, gt=0)  # 손절선 = 평균단가 − 배수 × 일봉 ATR


class SellParams(_Params):
    """매도 신호 (분봉 + 일봉 수급)."""

    rsi_overbought: float = 70.0
    bollinger_upper_level: float = 1.0  # %B 기준
    macd_weak_bars: int = Field(2, ge=1)  # 히스토그램 연속 감소 봉 수
    divergence_lookback: int = Field(30, ge=2)
    swing_confirm_bars: int = Field(3, ge=1)
    atr_disparity_window: int = Field(20, ge=2)
    atr_disparity_multiple: float = Field(3.0, gt=0)
    flow_exit_days: int = Field(3, ge=1)
    min_overlap: int = Field(2, ge=1)  # A-2: 매도 후보 중 겹쳐야 하는 개수
    sell_fraction: float = Field(1 / 3, gt=0, lt=1)  # A-3: 보유량 대비 제안 수량


class RebuyParams(_Params):
    """재매수 신호 (분봉 + 일봉 수급)와 재매수 목표가."""

    rsi_rebound_low: float = 30.0
    rsi_rebound_high: float = 50.0
    bollinger_support_level: float = 0.0  # 0 = 하단 지지, 0.5 = 중심선 지지
    min_confirmations: int = Field(2, ge=1)  # 반전 확인 3개 중 겹쳐야 하는 개수
    expiry_trading_days: int = Field(5, ge=1)  # A-7: 재매수 대기 만료
    target_gain: float = Field(0.01, ge=0)  # 목표 이득 1%
    # 임시 기본값. 구현 시점의 공식 수수료율·거래세율로 11단계에서 확정한다 (PRD 10장 오픈 이슈).
    round_trip_fee_rate: float = Field(0.0003, ge=0)  # 왕복 수수료
    sell_tax_rate: float = Field(0.0018, ge=0)  # 매도 거래세

    @property
    def cost(self) -> float:
        """재매수 목표가의 비용: 왕복 수수료 + 매도 거래세."""
        return self.round_trip_fee_rate + self.sell_tax_rate


class ForceSellParams(_Params):
    """A-13 5일선 이탈 강제 매도."""

    ma_short_window: int = Field(5, ge=1)
    ma_long_window: int = Field(20, ge=2)


class SignalParams(_Params):
    indicators: IndicatorParams = IndicatorParams()
    screener: ScreenerParams = ScreenerParams()
    score: ScoreParams = ScoreParams()
    scan: ScanParams = ScanParams()
    sell: SellParams = SellParams()
    rebuy: RebuyParams = RebuyParams()
    force_sell: ForceSellParams = ForceSellParams()
    trend: TrendParams = TrendParams()
    stop: StopParams = StopParams()


DEFAULT_PARAMS = SignalParams()
