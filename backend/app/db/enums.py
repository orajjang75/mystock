from enum import StrEnum


class Market(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class BarLength(StrEnum):
    M30 = "30m"
    M60 = "60m"
    D1 = "1d"


class HoldingState(StrEnum):
    """보유 종목 한 건의 상태 (PRD 5장, 7장 보유 종목 표)."""

    HOLDING = "holding"
    REBUY_WAIT = "rebuy_wait"
    EXPIRED = "expired"


class CycleState(StrEnum):
    """매도·재매수 사이클의 상태 (PRD 5장 상태 흐름, A-7, A-13)."""

    REBUY_WAIT = "rebuy_wait"
    REBUY_DONE = "rebuy_done"
    EXPIRED = "expired"
    ABANDONED = "abandoned"
    FORCE_CLOSED = "force_closed"


class FillSide(StrEnum):
    SELL = "sell"
    REBUY = "rebuy"
