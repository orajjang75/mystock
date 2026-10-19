import subprocess
import sys
from datetime import date
from importlib.util import find_spec

import pytest

from app.adapters.base import AdapterUnavailableError
from app.adapters.factory import get_adapter
from app.adapters.kis_adapter import KisAdapter
from app.adapters.mock import MockAdapter
from app.adapters.pykrx_adapter import PykrxAdapter
from app.core.config import Settings
from tests.pg import BACKEND_DIR

DAY = date(2026, 10, 16)


def test_adapter_env_var_selects_the_adapter() -> None:
    assert isinstance(get_adapter(Settings(adapter="mock")), MockAdapter)
    assert isinstance(get_adapter(Settings(adapter="pykrx")), PykrxAdapter)
    assert isinstance(get_adapter(Settings(adapter="kis")), KisAdapter)


def test_unknown_adapter_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="adapter"):
        Settings(adapter="nope")


def test_importing_the_pykrx_adapter_does_not_import_pykrx() -> None:
    code = "import app.adapters.pykrx_adapter, sys; assert 'pykrx' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(find_spec("pykrx") is not None, reason="pykrx is installed")
def test_pykrx_adapter_explains_how_to_install_pykrx() -> None:
    with pytest.raises(AdapterUnavailableError, match="--extra pykrx"):
        PykrxAdapter().fetch_listings(DAY)


def test_pykrx_has_no_intraday_bars() -> None:
    with pytest.raises(NotImplementedError):
        PykrxAdapter().fetch_intraday_30m("005930", DAY, DAY)
