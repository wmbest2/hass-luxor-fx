"""Shared fixtures."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))

from fake_controller import FakeLuxor, _Status  # noqa: E402

from custom_components.fx_luxor.api import LuxorConnectionError, LuxorStatusError  # noqa: E402

HOST = "192.168.20.160"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def fake() -> FakeLuxor:
    return FakeLuxor()


@pytest.fixture
def mock_controller(fake: FakeLuxor):
    """Route LuxorClient.call into the in-memory fake (no sockets)."""
    fake.offline = False

    async def _call(self, method, payload=None):
        if fake.offline:
            raise LuxorConnectionError("offline")
        try:
            data = fake.handle(method, payload or {})
        except _Status as s:
            data = {"Status": s.status}
        if data["Status"] != 0:
            raise LuxorStatusError(method, data["Status"])
        return data

    with patch("custom_components.fx_luxor.api.LuxorClient.call", _call):
        yield fake
