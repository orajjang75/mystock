from datetime import date, datetime

from app.core.market import KST, add_trading_days, rebuy_expiry


def test_five_trading_days_after_a_friday_is_the_next_friday() -> None:
    assert add_trading_days(date(2026, 10, 16), 5) == date(2026, 10, 23)


def test_weekends_do_not_count() -> None:
    assert add_trading_days(date(2026, 10, 15), 1) == date(2026, 10, 16)  # Thu -> Fri
    assert add_trading_days(date(2026, 10, 16), 1) == date(2026, 10, 19)  # Fri -> Mon
    assert add_trading_days(date(2026, 10, 17), 1) == date(2026, 10, 19)  # Sat -> Mon


def test_holidays_do_not_count() -> None:
    # Oct 9 2026 is 한글날: Wed Oct 7 + 5 trading days = Thu 8, Mon 12, Tue 13, Wed 14, Thu 15
    assert add_trading_days(date(2026, 10, 7), 5) == date(2026, 10, 15)


def test_zero_days_is_the_same_day() -> None:
    assert add_trading_days(date(2026, 10, 16), 0) == date(2026, 10, 16)


def test_the_rebuy_window_closes_at_the_market_close_of_the_last_day() -> None:
    sold = datetime(2026, 10, 16, 10, 30, tzinfo=KST)

    assert rebuy_expiry(sold, 5) == datetime(2026, 10, 23, 15, 30, tzinfo=KST)


# --- counting session bars (the alert cooldown is measured in them) ---------------------------


def kst(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


def test_bars_between_counts_session_bars_not_clock_time() -> None:
    from app.core.market import bars_between
    from app.db.enums import BarLength

    same = kst("2026-10-16 10:00")
    assert bars_between(same, same, BarLength.M60) == 0
    assert bars_between(kst("2026-10-16 09:00"), kst("2026-10-16 14:00"), BarLength.M60) == 5
    assert bars_between(kst("2026-10-16 09:00"), kst("2026-10-16 15:00"), BarLength.M30) == 12


def test_the_night_and_the_weekend_do_not_count() -> None:
    from app.core.market import bars_between
    from app.db.enums import BarLength

    # the last 60-minute bar of Friday to the first of Monday is one bar apart
    assert bars_between(kst("2026-10-16 15:00"), kst("2026-10-19 09:00"), BarLength.M60) == 1
    assert bars_between(kst("2026-10-16 15:00"), kst("2026-10-19 09:00"), BarLength.M30) == 1
    assert bars_between(kst("2026-10-16 14:00"), kst("2026-10-19 09:00"), BarLength.M60) == 2


def test_a_holiday_does_not_count_either() -> None:
    from app.core.market import bars_between
    from app.db.enums import BarLength

    # Thursday Oct 8 to Monday Oct 12 over the 한글날 holiday on Friday: one trading day apart
    assert bars_between(kst("2026-10-08 09:00"), kst("2026-10-12 09:00"), BarLength.M60) == 7
    assert bars_between(kst("2026-10-07 09:00"), kst("2026-10-12 09:00"), BarLength.D1) == 2


def test_daily_bars_count_trading_days() -> None:
    from app.core.market import bars_between
    from app.db.enums import BarLength

    assert bars_between(datetime(2026, 10, 15), datetime(2026, 10, 16), BarLength.D1) == 1
    assert (
        bars_between(datetime(2026, 10, 16), datetime(2026, 10, 19), BarLength.D1) == 1
    )  # naive = KST
    assert bars_between(datetime(2026, 10, 16), datetime(2026, 10, 16), BarLength.D1) == 0


def test_a_later_time_gives_a_negative_count() -> None:
    from app.core.market import bars_between
    from app.db.enums import BarLength

    assert bars_between(kst("2026-10-16 11:00"), kst("2026-10-16 10:00"), BarLength.M60) == -1
