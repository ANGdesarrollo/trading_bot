import os
from pathlib import Path

import pytest

_FIXTURE_ENV = "EURUSD_FIXTURE_PATH"


@pytest.fixture(scope="module")
def eurusd_fixture_path() -> Path:
    raw = os.environ.get(_FIXTURE_ENV)
    if not raw:
        pytest.skip(f"{_FIXTURE_ENV} not set or file missing")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"{_FIXTURE_ENV} not set or file missing")
    return path
