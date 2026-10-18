"""In-app alerts: saving, cooldown, latency log, delivery, listing and read marks (PRD A-10, A-12).

``save_drafts`` takes what the alert engine computed and stores it. The same signal on the same
stock stays quiet for ``cooldown_bars`` signal bars (counted in session bars, so the night does
not count), the time between the bar's close and the alert is logged against the one-minute
target, and every alert is also sent to the switched-on outside channels. A channel failing
never loses the alert: the result is kept in ``Alert.delivery``.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.market import KST, bars_between
from app.core.secrets import redact
from app.db.enums import BarLength
from app.db.models import Alert, Instrument
from app.services.alert_engine import AlertDraft
from app.services.notifier import Notification, Notifier, NotifierError

logger = logging.getLogger(__name__)

LATENCY_TARGET_SECONDS = 60  # PRD 성공 지표: 봉 마감 후 1분 이내

KIND_LABELS = {
    "sell": "매도 신호",
    "rebuy": "재매수 신호",
    "rebuy_held": "재매수 보류 경고 (일봉 수급 이탈)",
    "reduce_position": "비중 축소 경고 (일봉 하락 추세)",
    "stop_loss": "손절선 이탈 경고",
    "force_sell": "강제 매도 (5일선 이탈)",
    "expired": "재매수 대기 만료",
    "data_stale": "시세 갱신 지연 경고",
    "test": "시험 알림",
}
WARNING_KINDS = {"rebuy_held", "reduce_position", "stop_loss", "data_stale"}
# These come from confirmed daily bars; the same one must not repeat within the day.
DAILY_KINDS = {"force_sell", "expired"}


def level_of(kind: str) -> str:
    return "warning" if kind in WARNING_KINDS else "signal"


@dataclass(frozen=True, slots=True)
class SaveResult:
    saved: list[Alert]
    suppressed: int  # drafts dropped by the cooldown


def format_message(kind: str, name: str | None, code: str | None, **fields: object) -> str:
    """The summary sent outside the app: stock, kind, suggested quantity, rebuy target."""
    label = KIND_LABELS.get(kind, kind)
    head = f"[{label}]" + (f" {name} ({code})" if code else "")
    lines = [head]
    quantity, price, target = (fields.get(k) for k in ("quantity", "price", "target"))
    if quantity:
        lines.append(f"제안 수량: {quantity:,}주")
    if price:
        lines.append(f"현재가: {float(price):,.0f}원")  # type: ignore[arg-type]
    if target:
        lines.append(f"재매수 목표가: {float(target):,.0f}원")  # type: ignore[arg-type]
    if fields.get("note"):
        lines.append(str(fields["note"]))
    return "\n".join(lines)


def _unit(draft: AlertDraft, fallback: BarLength) -> tuple[BarLength, bool]:
    """The bar length a cooldown is counted in, and whether the cooldown is just "same day"."""
    if draft.kind in DAILY_KINDS:
        return BarLength.D1, True
    return draft.bar_length or fallback, False


def _in_cooldown(
    session: Session, draft: AlertDraft, cooldown_bars: int, fallback: BarLength
) -> bool:
    if draft.bar_time is None:
        return False
    code_match = Alert.code == draft.code if draft.code else Alert.code.is_(None)
    last = session.scalars(
        select(Alert)
        .where(code_match, Alert.kind == draft.kind, Alert.bar_time.is_not(None))
        .order_by(Alert.bar_time.desc())
        .limit(1)
    ).first()
    if last is None or last.bar_time is None:
        return False
    unit, same_day_only = _unit(draft, fallback)
    elapsed = bars_between(last.bar_time, draft.bar_time, unit)
    # Even with the cooldown switched off the same bar must not alert twice.
    return elapsed < (1 if same_day_only else max(1, cooldown_bars))


def _log_latency(draft: AlertDraft, created_at: datetime) -> float | None:
    """Log the time from the bar's close to the alert; only minute-bar signals have a target."""
    if draft.bar_end is None or draft.bar_length in (None, BarLength.D1):
        return None
    latency = (created_at - draft.bar_end).total_seconds()
    log = logger.info if latency <= LATENCY_TARGET_SECONDS else logger.warning
    log(
        "alert latency: kind=%s code=%s bar_end=%s created_at=%s latency=%.1fs (target %ds)%s",
        draft.kind,
        draft.code,
        draft.bar_end.astimezone(KST).isoformat(),
        created_at.astimezone(KST).isoformat(),
        latency,
        LATENCY_TARGET_SECONDS,
        "" if latency <= LATENCY_TARGET_SECONDS else " EXCEEDED",
    )
    return round(latency, 1)


def save_drafts(
    session: Session,
    drafts: Sequence[AlertDraft],
    *,
    created_at: datetime,
    cooldown_bars: int,
    signal_length: BarLength,
    notifiers: Sequence[Notifier] = (),
) -> SaveResult:
    """Store the drafts that are not in their cooldown and send them. Flushes, does not commit."""
    saved: list[Alert] = []
    suppressed = 0
    for draft in drafts:
        if _in_cooldown(session, draft, cooldown_bars, signal_length):
            suppressed += 1
            continue
        evidence = dict(draft.evidence)
        latency = _log_latency(draft, created_at)
        if latency is not None:
            evidence["latency_seconds"] = latency
        if draft.bar_end is not None:
            evidence["bar_end"] = draft.bar_end.isoformat()
        alert = Alert(
            kind=draft.kind,
            code=draft.code or None,
            holding_id=draft.holding_id,
            bar_time=draft.bar_time,
            suggested_quantity=draft.suggested_quantity,
            price=None if draft.price is None else Decimal(str(round(draft.price, 4))),
            rebuy_target_price=None
            if draft.rebuy_target_price is None
            else Decimal(str(round(draft.rebuy_target_price, 4))),
            occurred_at=created_at,
            evidence=evidence,
            params=draft.params,
            delivery=[{"channel": "in_app", "status": "stored"}],
        )
        session.add(alert)
        session.flush()
        _deliver(session, alert, notifiers, created_at)
        saved.append(alert)
    return SaveResult(saved, suppressed)


def alert_text(session: Session, alert: Alert) -> str:
    instrument = session.get(Instrument, alert.code) if alert.code else None
    return format_message(
        alert.kind,
        instrument.name if instrument else None,
        alert.code,
        quantity=alert.suggested_quantity,
        price=alert.price,
        target=alert.rebuy_target_price,
        note=alert.evidence.get("message"),
    )


def _deliver(session: Session, alert: Alert, notifiers: Sequence[Notifier], at: datetime) -> None:
    if not notifiers:
        return
    notification = Notification(alert.kind, alert_text(session, alert))
    results = list(alert.delivery)
    for notifier in notifiers:
        try:
            notifier.send(notification)
            results.append({"channel": notifier.name, "status": "sent", "at": at.isoformat()})
        except NotifierError as error:
            logger.warning("sending a %s alert via %s failed: %s", alert.kind, notifier.name, error)
            results.append(
                {
                    "channel": notifier.name,
                    "status": "failed",
                    "at": at.isoformat(),
                    "error": redact(str(error)),
                }
            )
    alert.delivery = results  # a new list, so the change is saved
    session.flush()


def send_test(notifiers: Sequence[Notifier]) -> list[dict[str, str]]:
    """Send a test message through each notifier and report the outcome per channel."""
    text = format_message("test", None, None, note="mystock 알림 채널 시험 메시지입니다.")
    outcomes = []
    for notifier in notifiers:
        try:
            notifier.send(Notification("test", text))
            outcomes.append({"channel": notifier.name, "status": "sent"})
        except NotifierError as error:
            outcomes.append(
                {"channel": notifier.name, "status": "failed", "error": redact(str(error))}
            )
    return outcomes


# --- reading ----------------------------------------------------------------------------------


def list_alerts(
    session: Session,
    *,
    unread_only: bool = False,
    kind: str | None = None,
    code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Alert]:
    """Newest first."""
    query = select(Alert).order_by(Alert.occurred_at.desc(), Alert.id.desc())
    if unread_only:
        query = query.where(Alert.is_read.is_(False))
    if kind:
        query = query.where(Alert.kind == kind)
    if code:
        query = query.where(Alert.code == code)
    return list(session.scalars(query.limit(limit).offset(offset)))


def unread_count(session: Session) -> int:
    return (
        session.scalar(select(func.count()).select_from(Alert).where(Alert.is_read.is_(False))) or 0
    )


def mark_read(session: Session, alert_id: int) -> Alert | None:
    """Mark one alert as read (idempotent). ``None`` if it does not exist."""
    alert = session.get(Alert, alert_id)
    if alert is not None and not alert.is_read:
        alert.is_read = True
        session.flush()
    return alert
