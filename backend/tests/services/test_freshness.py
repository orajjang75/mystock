from datetime import datetime, time, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.market import KST
from app.db.models import Setting
from app.services import status
from app.services.freshness import (
    FreshnessSpec,
    evaluate_freshness,
    expected_daily_run,
    expected_intraday_run,
)

SCAN = time(18, 0)
SPEC = FreshnessSpec()


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


# --- what is expected when ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-16 09:29", None),  # before the first bar closes
        ("2026-10-16 09:30", "2026-10-16 09:30"),
        ("2026-10-16 10:29", "2026-10-16 10:00"),
        ("2026-10-16 10:30", "2026-10-16 10:30"),
        ("2026-10-16 15:30", "2026-10-16 15:30"),
        ("2026-10-16 15:59", "2026-10-16 15:30"),  # the last bar's run may still be late
        ("2026-10-16 16:00", None),  # the session is over
        ("2026-10-17 10:00", None),  # Saturday
        ("2026-10-09 10:00", None),  # 한글날
    ],
)
def test_the_expected_intraday_run(now: str, expected: str | None) -> None:
    assert expected_intraday_run(at(now), SPEC) == (at(expected) if expected else None)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-16 17:59", "2026-10-15 18:00"),  # today's scan is not due yet
        ("2026-10-16 18:00", "2026-10-16 18:00"),
        ("2026-10-17 12:00", "2026-10-16 18:00"),  # the weekend: Friday's
        ("2026-10-19 09:30", "2026-10-16 18:00"),  # Monday morning: still Friday's
        ("2026-10-12 09:30", "2026-10-08 18:00"),  # over the Friday holiday: Thursday's
    ],
)
def test_the_expected_daily_run(now: str, expected: str) -> None:
    assert expected_daily_run(at(now), SCAN) == at(expected)


# --- stale or not ------------------------------------------------------------------------------


def record(
    session: Session, source: str, ok_at: str | None = None, failed_at: str | None = None
) -> None:
    if ok_at:
        status.record_success(session, source, at(ok_at))
    if failed_at:
        status.record_failure(session, source, at(failed_at), "ConnectionError: down")


def judge(session: Session, now: str) -> dict[str, bool]:
    report = evaluate_freshness(session, at(now), SCAN)
    return {name: s.stale for name, s in report.sources.items()}


def test_a_fresh_collection_is_not_stale(session: Session) -> None:
    record(session, "intraday", "2026-10-16 10:00:12")
    record(session, "daily", "2026-10-15 18:00:30")

    assert judge(session, "2026-10-16 10:00:40") == {"intraday": False, "daily": False}


def test_a_missed_bar_is_stale_after_the_grace_period_only(session: Session) -> None:
    record(session, "intraday", "2026-10-16 09:30:12")
    record(session, "daily", "2026-10-15 18:00:30")

    assert judge(session, "2026-10-16 10:04")["intraday"] is False  # within 5 minutes of 10:00
    assert judge(session, "2026-10-16 10:06")["intraday"] is True


def test_a_failed_attempt_is_stale_immediately(session: Session) -> None:
    record(session, "intraday", "2026-10-16 09:30:12", failed_at="2026-10-16 10:00:15")
    record(session, "daily", "2026-10-15 18:00:30")

    assert judge(session, "2026-10-16 10:00:20")["intraday"] is True


def test_a_failure_before_the_expected_run_does_not_count_once_a_later_run_succeeded(
    session: Session,
) -> None:
    record(session, "intraday", failed_at="2026-10-16 10:00:15")
    record(session, "intraday", "2026-10-16 10:30:12")  # recovered
    record(session, "daily", "2026-10-15 18:00:30")

    assert judge(session, "2026-10-16 10:31")["intraday"] is False


def test_nothing_is_expected_of_the_intraday_job_outside_the_session(session: Session) -> None:
    record(session, "daily", "2026-10-15 18:00:30")

    assert judge(session, "2026-10-16 09:20")["intraday"] is False
    assert judge(session, "2026-10-16 17:00")["intraday"] is False
    assert judge(session, "2026-10-17 11:00")["intraday"] is False


def test_the_daily_collection_is_stale_when_it_missed_the_scan_time(session: Session) -> None:
    record(session, "daily", "2026-10-14 18:00:30")  # Wednesday's only

    assert judge(session, "2026-10-15 18:30")["daily"] is False  # inside the hour of grace
    assert judge(session, "2026-10-15 19:10")["daily"] is True
    assert judge(session, "2026-10-16 09:30")["daily"] is True  # still missing next morning


def test_a_system_that_never_collected_is_stale(session: Session) -> None:
    assert judge(session, "2026-10-17 12:00") == {"intraday": False, "daily": True}


def test_the_report_lists_warnings_with_the_reason(session: Session) -> None:
    record(session, "intraday", "2026-10-16 09:30:12", failed_at="2026-10-16 10:00:15")
    record(session, "daily", "2026-10-15 18:00:30")

    report = evaluate_freshness(session, at("2026-10-16 10:01"), SCAN)

    assert not report.ok
    (warning,) = report.warnings
    assert warning.source == "intraday"
    assert warning.message is not None
    assert "분봉 시세" in warning.message
    assert "ConnectionError: down" in warning.message
    assert "10-16 09:30" in warning.message  # the last success


def test_everything_fresh_means_ok(session: Session) -> None:
    record(session, "intraday", "2026-10-16 10:00:12")
    record(session, "daily", "2026-10-15 18:00:30")

    report = evaluate_freshness(session, at("2026-10-16 10:01"), SCAN)

    assert report.ok and report.warnings == []


# --- the stored status -------------------------------------------------------------------------


def test_status_round_trips_and_counts_failures(session: Session) -> None:
    status.record_failure(session, "daily", at("2026-10-16 18:00"), "boom")
    status.record_failure(session, "daily", at("2026-10-16 18:05"), "boom again")

    daily = status.load_status(session)["daily"]
    assert daily.consecutive_failures == 2
    assert daily.last_error == "boom again"
    assert daily.last_success is None

    status.record_success(session, "daily", at("2026-10-16 18:10"))
    daily = status.load_status(session)["daily"]
    assert (daily.consecutive_failures, daily.last_error) == (0, None)
    assert daily.last_success == at("2026-10-16 18:10")
    assert status.load_status(session)["intraday"].last_success is None


def test_a_failure_keeps_the_last_success(session: Session) -> None:
    status.record_success(session, "intraday", at("2026-10-16 10:00"))
    status.record_failure(session, "intraday", at("2026-10-16 10:30"), "down")

    intraday = status.load_status(session)["intraday"]

    assert intraday.last_success == at("2026-10-16 10:00")
    assert intraday.last_attempt == at("2026-10-16 10:30")


def test_secrets_in_an_error_are_masked_and_long_errors_cut(session: Session) -> None:
    from app.core.config import get_settings

    password = get_settings().app_password.get_secret_value()

    status.record_failure(
        session, "daily", at("2026-10-16 18:00"), f"login failed for {password} " + "x" * 500
    )

    error = status.load_status(session)["daily"].last_error
    assert error is not None
    assert password not in error
    assert "***" in error
    assert len(error) <= 300


def test_the_status_does_not_touch_the_user_settings_row(session: Session) -> None:
    session.add(Setting(name="current", value={"alert_cooldown_bars": 9}))
    session.flush()

    status.record_success(session, "daily", at("2026-10-16 18:00"))

    row = session.get(Setting, "current")
    assert row is not None and row.value == {"alert_cooldown_bars": 9}
    assert session.get(Setting, status.ROW) is not None


def test_a_custom_grace_changes_when_a_run_counts_as_late(session: Session) -> None:
    record(session, "intraday", "2026-10-16 09:30:12")
    record(session, "daily", "2026-10-15 18:00:30")
    spec = FreshnessSpec(intraday_grace=timedelta(minutes=20))

    report = evaluate_freshness(session, at("2026-10-16 10:15"), SCAN, spec)

    assert report.ok
