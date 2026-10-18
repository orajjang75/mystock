from sqlalchemy.orm import Session

from app.db.models import Setting
from app.engine.params import DEFAULT_PARAMS, SignalParams
from app.services.settings import CURRENT, load_signal_params, save_signal_params


def test_defaults_apply_until_something_is_saved(session: Session) -> None:
    assert load_signal_params(session) == DEFAULT_PARAMS


def test_saved_parameters_round_trip(session: Session) -> None:
    changed = SignalParams.model_validate(
        {
            "scan": {"min_score": 40},
            "score": {"flow_points": 10},
            "screener": {"drawdown_threshold_pct": -25},
        }
    )

    save_signal_params(session, changed)
    session.commit()

    assert load_signal_params(session) == changed
    assert load_signal_params(session) != DEFAULT_PARAMS


def test_saving_twice_replaces_the_previous_value_and_keeps_other_keys(session: Session) -> None:
    save_signal_params(session, SignalParams.model_validate({"scan": {"min_score": 40}}))
    row = session.get(Setting, CURRENT)
    assert row is not None
    row.value = {**row.value, "channels": {"telegram": True}}  # some other part of the settings
    session.commit()

    save_signal_params(session, SignalParams.model_validate({"scan": {"min_score": 70}}))
    session.commit()

    assert load_signal_params(session).scan.min_score == 70
    assert session.get(Setting, CURRENT).value["channels"] == {"telegram": True}  # type: ignore[union-attr]
