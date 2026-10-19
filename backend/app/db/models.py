"""PRD 8장 테이블. 컬럼은 "주요 컬럼"을 따르고, 재현성(10장)에 필요한 params 컬럼만 더했다."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, Price, str_enum
from app.db.enums import BarLength, CycleState, FillSide, HoldingState, Market


def _updated_at() -> Mapped[datetime]:
    """시세 테이블의 마지막 갱신 시각. 수집 작업이 upsert 때 갱신하며 /api/health 가 읽는다."""
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Instrument(Base):
    """종목 마스터와 제외 필터."""

    __tablename__ = "instruments"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    market: Mapped[Market] = mapped_column(str_enum(Market, 8))
    # 스캔 대상(universe)의 시장별 시가총액 순위 1..N. 대상이 아니면 NULL.
    market_cap_rank: Mapped[int | None] = mapped_column(Integer)
    is_preferred: Mapped[bool] = mapped_column(server_default=false())  # 우선주
    is_admin_issue: Mapped[bool] = mapped_column(server_default=false())  # 관리종목
    is_halted: Mapped[bool] = mapped_column(server_default=false())  # 거래정지
    is_warning: Mapped[bool] = mapped_column(server_default=false())  # 투자경고·위험


class OhlcvDaily(Base):
    """일봉 시세."""

    __tablename__ = "ohlcv_daily"
    __table_args__ = (Index("ix_ohlcv_daily_trade_date", "trade_date"),)

    code: Mapped[str] = mapped_column(ForeignKey("instruments.code"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    volume: Mapped[int] = mapped_column(BigInteger)
    trading_value: Mapped[int] = mapped_column(BigInteger)  # 거래대금(원)
    updated_at: Mapped[datetime] = _updated_at()


class IndexDaily(Base):
    """KOSPI 지수 일봉 (A-13 강제 매도 신호)."""

    __tablename__ = "index_daily"

    index_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    updated_at: Mapped[datetime] = _updated_at()


class InvestorFlowDaily(Base):
    """투자자별 일별 순매수 금액(원)."""

    __tablename__ = "investor_flow_daily"

    code: Mapped[str] = mapped_column(ForeignKey("instruments.code"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(primary_key=True)
    foreign_net_buy: Mapped[int] = mapped_column(BigInteger)
    institution_net_buy: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = _updated_at()


class OhlcvIntraday(Base):
    """분봉 시세. 30분봉만 저장하고 60분봉은 조회 시 집계한다."""

    __tablename__ = "ohlcv_intraday"

    code: Mapped[str] = mapped_column(ForeignKey("instruments.code"), primary_key=True)
    bar_length: Mapped[BarLength] = mapped_column(str_enum(BarLength, 4), primary_key=True)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    volume: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = _updated_at()


class ScanResult(Base):
    """스크리너 결과 이력. 같은 날 재실행하면 (scan_date, code) 행을 덮어쓴다."""

    __tablename__ = "scan_results"
    __table_args__ = (
        UniqueConstraint("scan_date", "code", name="uq_scan_results_scan_date_code"),
        Index("ix_scan_results_scan_date_score", "scan_date", "score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_date: Mapped[date]
    code: Mapped[str] = mapped_column(ForeignKey("instruments.code"))
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)  # 충족 조건 태그
    indicators: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # 근거 지표 값
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # 사용한 파라미터


class Watchlist(Base):
    """관심종목 (스캔 대상 종목에서만 고를 수 있다: S-11)."""

    __tablename__ = "watchlist"

    code: Mapped[str] = mapped_column(ForeignKey("instruments.code"), primary_key=True)
    added_date: Mapped[date] = mapped_column(server_default=func.current_date())


class Holding(Base):
    """보유 종목."""

    __tablename__ = "holdings"
    __table_args__ = (Index("ix_holdings_code", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(ForeignKey("instruments.code"))
    quantity: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[Decimal] = mapped_column(Price)
    start_quantity: Mapped[int] = mapped_column(Integer)  # 수량 늘리기 기준점
    state: Mapped[HoldingState] = mapped_column(
        str_enum(HoldingState, 16), default=HoldingState.HOLDING
    )


class Cycle(Base):
    """매도·재매수 사이클과 수량 증가분."""

    __tablename__ = "cycles"
    __table_args__ = (Index("ix_cycles_holding_id", "holding_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    holding_id: Mapped[int] = mapped_column(ForeignKey("holdings.id"))
    sell_price: Mapped[Decimal] = mapped_column(Price)
    sell_quantity: Mapped[int] = mapped_column(Integer)
    rebuy_target_price: Mapped[Decimal] = mapped_column(Price)
    rebuy_price: Mapped[Decimal | None] = mapped_column(Price)
    rebuy_quantity: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[CycleState] = mapped_column(
        str_enum(CycleState, 16), default=CycleState.REBUY_WAIT
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    """알림 목록. 근거 지표 값과 사용한 파라미터를 함께 저장한다(재현성)."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_is_read_occurred_at", "is_read", "occurred_at"),
        Index("ix_alerts_code_kind_bar_time", "code", "kind", "bar_time"),
        Index("ix_alerts_holding_id", "holding_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    code: Mapped[str | None] = mapped_column(ForeignKey("instruments.code"))
    holding_id: Mapped[int | None] = mapped_column(ForeignKey("holdings.id"))
    bar_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # evaluated bar
    suggested_quantity: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[Decimal | None] = mapped_column(Price)
    rebuy_target_price: Mapped[Decimal | None] = mapped_column(Price)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # 근거 지표 값
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # 사용한 파라미터
    is_read: Mapped[bool] = mapped_column(server_default=false())
    delivery: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)  # 채널과 상태


class Setting(Base):
    """사용자 설정. name='current' 가 현재 설정, is_preset=true 인 행이 프리셋이다."""

    __tablename__ = "settings"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    is_preset: Mapped[bool] = mapped_column(server_default=false())
    updated_at: Mapped[datetime] = _updated_at()


class Fill(Base):
    """사용자가 직접 기록한 체결."""

    __tablename__ = "fills"
    __table_args__ = (
        Index("ix_fills_holding_id", "holding_id"),
        Index("ix_fills_cycle_id", "cycle_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    holding_id: Mapped[int] = mapped_column(ForeignKey("holdings.id"))
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("cycles.id"))
    forced: Mapped[bool] = mapped_column(server_default=false())  # A-13 강제 매도 체결
    side: Mapped[FillSide] = mapped_column(str_enum(FillSide, 8))
    price: Mapped[Decimal] = mapped_column(Price)
    quantity: Mapped[int] = mapped_column(Integer)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fee: Mapped[Decimal] = mapped_column(Price, server_default="0")
    tax: Mapped[Decimal] = mapped_column(Price, server_default="0")


class JobRun(Base):
    """한 번의 예약 작업 실행 기록. 모의 운영 리포트(봉 누락, 수집 실패, 알림 지연)의 원자료."""

    __tablename__ = "job_runs"
    __table_args__ = (Index("ix_job_runs_job_scheduled_for", "job", "scheduled_for"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(10))  # intraday | daily
    # The bar close (intraday) or the scan time (daily) this run was for.
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(10))  # ok | skipped | stale | failed
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class UniverseSnapshot(Base):
    """시점별 스캔 대상 (시가총액 순위). 백테스트가 과거 시점 기준 유니버스를 쓰도록 쌓아 둔다."""

    __tablename__ = "universe_snapshots"
    __table_args__ = (Index("ix_universe_snapshots_as_of", "as_of"),)

    as_of: Mapped[date] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(ForeignKey("instruments.code"), primary_key=True)
    market: Mapped[Market] = mapped_column(str_enum(Market, 8))
    rank: Mapped[int] = mapped_column(Integer)  # 그 시점 시장별 시가총액 순위 1..N
    market_cap: Mapped[int] = mapped_column(BigInteger)  # 원


class BacktestRun(Base):
    """백테스트 실행과 결과. params=요청 전체, summary=요약, detail=표와 곡선."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    start_date: Mapped[date]
    end_date: Mapped[date]
    bar_length: Mapped[BarLength] = mapped_column(str_enum(BarLength, 4))
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    name: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(10), server_default="done"
    )  # queued|running|done|failed
    progress: Mapped[float] = mapped_column(Float, server_default="1")  # 0..1
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


__all__ = [
    "Alert",
    "BacktestRun",
    "Cycle",
    "Fill",
    "Holding",
    "IndexDaily",
    "Instrument",
    "InvestorFlowDaily",
    "JobRun",
    "OhlcvDaily",
    "OhlcvIntraday",
    "ScanResult",
    "Setting",
    "UniverseSnapshot",
    "Watchlist",
]
