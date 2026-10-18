from datetime import datetime

import pandas as pd

from app.core.market import KST
from app.engine.confirmed import confirmed_daily, confirmed_intraday
from app.engine.screener_signals import rsi_cross_up


def daily_frame() -> pd.DataFrame:
    dates = pd.DatetimeIndex(["2026-10-14", "2026-10-15", "2026-10-16"], name="trade_date")
    return pd.DataFrame({"rsi": [20.0, 29.0, 30.0]}, index=dates)  # crosses 30 on the last day


def test_a_daily_bar_is_dropped_until_the_session_has_closed() -> None:
    during = datetime(2026, 10, 16, 15, 29, tzinfo=KST)
    closed = datetime(2026, 10, 16, 15, 30, tzinfo=KST)

    assert len(confirmed_daily(daily_frame(), during)) == 2
    assert len(confirmed_daily(daily_frame(), closed)) == 3


def test_no_signal_comes_from_an_unconfirmed_last_bar() -> None:
    frame = daily_frame()
    midday = datetime(2026, 10, 16, 11, 0, tzinfo=KST)
    after_close = datetime(2026, 10, 16, 16, 0, tzinfo=KST)

    assert not rsi_cross_up(confirmed_daily(frame, midday)["rsi"]).iloc[-1]
    assert rsi_cross_up(confirmed_daily(frame, after_close)["rsi"]).iloc[-1]


def intraday_frame(starts: list[str], span: int | None = None) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(s, tz=KST) for s in starts], name="bar_time")
    frame = pd.DataFrame({"close": range(len(index))}, index=index)
    if span is not None:
        frame["span_minutes"] = span
    return frame


def test_an_intraday_bar_is_final_once_its_end_time_has_passed() -> None:
    bars = intraday_frame(["2026-10-16 14:00", "2026-10-16 14:30", "2026-10-16 15:00"])

    now = datetime(2026, 10, 16, 15, 0, tzinfo=KST)

    # 14:30 ends exactly at 15:00 (kept); 15:00 runs until 15:30 (dropped)
    assert [t.strftime("%H:%M") for t in confirmed_intraday(bars, now).index] == ["14:00", "14:30"]
    assert len(confirmed_intraday(bars, datetime(2026, 10, 16, 14, 59, tzinfo=KST))) == 1


def test_a_60_minute_bar_uses_its_own_span_so_the_last_one_ends_at_1530() -> None:
    hourly = pd.DataFrame(
        {"close": [1, 2], "span_minutes": [60, 30]},
        index=pd.DatetimeIndex(
            [pd.Timestamp("2026-10-16 14:00", tz=KST), pd.Timestamp("2026-10-16 15:00", tz=KST)],
            name="bar_time",
        ),
    )

    assert len(confirmed_intraday(hourly, datetime(2026, 10, 16, 15, 29, tzinfo=KST))) == 1
    assert len(confirmed_intraday(hourly, datetime(2026, 10, 16, 15, 30, tzinfo=KST))) == 2


def test_a_60_minute_bar_with_only_its_first_half_is_never_confirmed() -> None:
    # at 14:45 the 14:00-15:00 bar has only its 14:00 half-hour: it is not a closed hour yet
    hourly = pd.DataFrame(
        {"close": [1, 2], "span_minutes": [60, 30], "is_complete": [True, False]},
        index=pd.DatetimeIndex(
            [pd.Timestamp("2026-10-16 13:00", tz=KST), pd.Timestamp("2026-10-16 14:00", tz=KST)],
            name="bar_time",
        ),
    )

    kept = confirmed_intraday(hourly, datetime(2026, 10, 16, 14, 45, tzinfo=KST))

    assert [t.strftime("%H:%M") for t in kept.index] == ["13:00"]
