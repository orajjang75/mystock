from datetime import datetime

from app.adapters.base import MarketDataAdapter
from app.core.config import Settings, get_settings
from app.core.market import KST, last_weekday


def get_adapter(settings: Settings | None = None) -> MarketDataAdapter:
    """Build the adapter chosen by ``ADAPTER`` (mock | pykrx | kis). Imports are lazy."""
    settings = settings or get_settings()
    if settings.adapter == "mock":
        from app.adapters.mock import MockAdapter

        return MockAdapter(seed=settings.mock_seed, end_date=last_weekday(datetime.now(KST).date()))
    if settings.adapter == "pykrx":
        from app.adapters.pykrx_adapter import PykrxAdapter

        return PykrxAdapter(
            krx_id=settings.krx_id,
            krx_pw=settings.krx_pw.get_secret_value() if settings.krx_pw else None,
        )
    from app.adapters.kis_adapter import KisAdapter

    return KisAdapter()
