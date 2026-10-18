from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import Market
from app.db.models import Instrument, OhlcvDaily
from app.db.upsert import upsert

BAR = {"open": 1, "high": 3, "low": 1, "close": 2, "volume": 10, "trading_value": 20}
COLUMNS = list(BAR)


def test_second_write_updates_the_row_instead_of_failing(session: Session) -> None:
    session.add(Instrument(code="900010", name="모의", market=Market.KOSPI))
    session.commit()
    key = {"code": "900010", "trade_date": date(2026, 10, 16)}

    upsert(
        session, OhlcvDaily, [{**key, **BAR}], conflict_columns=list(key), update_columns=COLUMNS
    )
    upsert(
        session,
        OhlcvDaily,
        [{**key, **BAR, "close": 3}],
        conflict_columns=list(key),
        update_columns=COLUMNS,
        touch_updated_at=True,
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(OhlcvDaily)) == 1
    assert session.scalar(select(OhlcvDaily.close)) == Decimal("3")
    assert session.scalar(select(OhlcvDaily.updated_at)) is not None


def test_empty_input_writes_nothing(session: Session) -> None:
    assert upsert(session, OhlcvDaily, [], conflict_columns=["code"], update_columns=[]) == 0
