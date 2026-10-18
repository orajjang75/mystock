from datetime import date

import pandas as pd

from app.core.market import KST
from app.services.bars import aggregate_60m


def make_bars(day: str, starts: list[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex([f"{day} {start}" for start in starts], name="bar_time", tz=KST)
    n = len(index)
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(n)],
            "high": [110.0 + i for i in range(n)],
            "low": [90.0 + i for i in range(n)],
            "close": [105.0 + i for i in range(n)],
            "volume": [10 * (i + 1) for i in range(n)],
        },
        index=index,
    )


FULL_DAY = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)][:-1]  # 09:00 .. 15:00


def test_full_day_gives_seven_bars_and_the_last_one_is_30_minutes() -> None:
    assert len(FULL_DAY) == 13

    hourly = aggregate_60m(make_bars("2026-10-16", FULL_DAY))

    assert len(hourly) == 7
    assert [ts.strftime("%H:%M") for ts in hourly.index] == [
        "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00",
    ]  # fmt: skip
    assert list(hourly["span_minutes"]) == [60, 60, 60, 60, 60, 60, 30]
    assert list(hourly["n_bars"]) == [2, 2, 2, 2, 2, 2, 1]
    assert hourly["is_complete"].all()


def test_ohlcv_of_an_hour_combines_its_two_half_hours() -> None:
    bars = make_bars("2026-10-16", FULL_DAY)

    first = aggregate_60m(bars).iloc[0]

    assert first["open"] == 100.0  # open of 09:00
    assert first["close"] == 106.0  # close of 09:30
    assert first["high"] == 111.0
    assert first["low"] == 90.0
    assert first["volume"] == 30


def test_an_hour_with_only_its_first_half_is_not_complete() -> None:
    # The 14:30 bar has not closed yet, so the 14:00 hour is still in progress.
    bars = make_bars("2026-10-16", [*FULL_DAY[:10], "14:00"][:11])

    hourly = aggregate_60m(bars)

    assert hourly.index[-1].strftime("%H:%M") == "14:00"
    assert hourly["n_bars"].iloc[-1] == 1
    assert not hourly["is_complete"].iloc[-1]
    assert hourly["is_complete"].iloc[:-1].all()


def test_bars_outside_the_regular_session_are_ignored() -> None:
    bars = make_bars("2026-10-16", ["08:30", "09:00", "09:30", "15:00", "15:30", "16:00"])

    hourly = aggregate_60m(bars)

    assert [ts.strftime("%H:%M") for ts in hourly.index] == ["09:00", "15:00"]


def test_days_are_not_merged_so_indicators_can_run_across_days() -> None:
    two_days = pd.concat([make_bars("2026-10-15", FULL_DAY), make_bars("2026-10-16", FULL_DAY)])

    hourly = aggregate_60m(two_days)

    assert len(hourly) == 14
    assert {ts.date() for ts in hourly.index} == {date(2026, 10, 15), date(2026, 10, 16)}
    assert (hourly[pd.DatetimeIndex(hourly.index).hour == 15]["span_minutes"] == 30).all()
