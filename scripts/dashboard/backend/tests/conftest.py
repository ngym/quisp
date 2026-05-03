from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line("markers", "anyio: run test with AnyIO")
    config.addinivalue_line("markers", "e2e: browser-based dashboard tests")


@pytest.fixture
def anyio_backend():
    return "asyncio"
