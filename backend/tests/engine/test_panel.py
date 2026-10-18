import pandas as pd

from app.engine.panel import to_wide


def frame(offset: float) -> pd.DataFrame:
    index = pd.date_range("2026-10-12", periods=3, name="trade_date")
    return pd.DataFrame(
        {"close": [1 + offset, 2 + offset, 3 + offset], "volume": [10, 20, 30]}, index=index
    )


def test_to_wide_has_one_column_per_stock_for_each_field() -> None:
    wide = to_wide({"A": frame(0), "B": frame(100)})

    assert set(wide) == {"close", "volume"}
    assert list(wide["close"].columns) == ["A", "B"]
    assert wide["close"]["B"].tolist() == [101, 102, 103]
    assert wide["volume"]["A"].tolist() == [10, 20, 30]


def test_to_wide_unions_the_calendars_and_leaves_gaps_as_nan() -> None:
    shorter = frame(0).iloc[1:]

    wide = to_wide({"A": frame(0), "B": shorter})

    assert len(wide["close"]) == 3
    assert pd.isna(wide["close"]["B"].iloc[0])


def test_to_wide_frames_are_a_single_block_so_later_math_stays_fast() -> None:
    wide = to_wide({str(i): frame(i) for i in range(50)})

    assert wide["close"]._mgr.nblocks == 1
