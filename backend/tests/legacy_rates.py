"""Fixed fee and tax rates for tests whose expected numbers were worked out by hand.

The defaults of ``RebuyParams`` follow the current official rates and will change again; a test
that checks a calculation by hand should not move with them. 0.03% round trip, 0.18% sell tax.
"""

from sqlalchemy.orm import Session

from app.engine.params import RebuyParams, SignalParams
from app.services.settings import save_signal_params

HAND_REBUY = RebuyParams(round_trip_fee_rate=0.0003, sell_tax_rate=0.0018)
HAND_PARAMS = SignalParams(rebuy=HAND_REBUY)


def pin_hand_rates(session: Session) -> None:
    """Save the hand-calculation rates as the current settings. Does not commit."""
    save_signal_params(session, HAND_PARAMS)
    session.flush()
