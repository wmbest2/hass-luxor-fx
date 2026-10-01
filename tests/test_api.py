"""Client tests against the fake controller over real HTTP."""

from __future__ import annotations

import aiohttp
import pytest
import pytest_socket
from aiohttp.test_utils import TestServer
from fake_controller import FakeLuxor, make_app

from custom_components.fx_luxor.api import (
    ControllerType,
    LuxorClient,
    LuxorConnectionError,
    LuxorStatusError,
    dedicated_color_slot,
)


@pytest.fixture(autouse=True)
def _real_sockets():
    """These tests talk HTTP to a local fake; HA's harness blocks sockets by default."""
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)
    yield


@pytest.fixture
async def server(fake: FakeLuxor):
    srv = TestServer(make_app(fake), host="127.0.0.1")
    await srv.start_server()
    yield srv
    await srv.close()


@pytest.fixture
async def client(server):
    async with aiohttp.ClientSession() as session:
        yield LuxorClient(f"127.0.0.1:{server.port}", session, min_gap=0)


async def test_state_snapshot(client: LuxorClient) -> None:
    state = await client.state()
    assert state.info.name == "lxtwo-000000001"
    assert state.info.type is ControllerType.ZDTWO
    assert state.info.rssi == 44
    assert [g.name for g in state.groups.values()] == ["Group 1", "Group 2", "Group 3"]
    assert state.groups[3].intensity == 100
    assert state.themes[0].name == "Nighttime" and state.themes[0].on
    assert state.colors[4].hue == 0 and state.colors[4].saturation == 100


async def test_theme_groups(client: LuxorClient) -> None:
    groups = await client.theme_groups(0)
    assert [(g.group, g.intensity, g.color) for g in groups] == [(1, 10, 0), (2, 10, 0), (3, 100, 0)]


async def test_illuminate_and_color(client: LuxorClient, fake: FakeLuxor) -> None:
    await client.illuminate_group(2, 150)  # clamped
    assert fake.groups[2]["Inten"] == 100
    groups = await client.groups()
    slot = dedicated_color_slot(2)
    assert slot == 249
    await client.set_color(slot, 359.6, 80.2)
    await client.assign_group_color(groups[2], slot)
    assert fake.colors[249] == {"C": 249, "Hue": 0, "Sat": 80}
    assert fake.groups[2]["Colr"] == 249 and fake.groups[2]["Name"] == "Group 2"


async def test_status_error(client: LuxorClient) -> None:
    with pytest.raises(LuxorStatusError) as err:
        await client.illuminate_theme(9, True)
    assert err.value.status == 243
    with pytest.raises(LuxorStatusError):
        await client.call("NoSuchMethod")


async def test_connection_error() -> None:
    async with aiohttp.ClientSession() as session:
        client = LuxorClient("127.0.0.1:1", session, timeout=1, attempts=2)
        with pytest.raises(LuxorConnectionError):
            await client.controller_info()


async def test_retries_transient_failures(client: LuxorClient, fake: FakeLuxor) -> None:
    fake.drop_next = 2
    info = await client.controller_info()
    assert info.name == "lxtwo-000000001"
    assert len(fake.connections) == 3


async def test_gives_up_after_attempts(client: LuxorClient, fake: FakeLuxor) -> None:
    fake.drop_next = 3
    with pytest.raises(LuxorConnectionError):
        await client.controller_info()


async def test_no_keep_alive(client: LuxorClient, fake: FakeLuxor) -> None:
    await client.groups()
    await client.themes()
    assert fake.connections == ["close", "close"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("luxor-123", ControllerType.ZD),
        ("lxzdc-1", ControllerType.ZDC),
        ("lxtwo-650715048", ControllerType.ZDTWO),
    ],
)
def test_controller_type(name: str, expected: ControllerType) -> None:
    assert ControllerType.from_name(name) is expected
    assert expected.supports_color is (expected is not ControllerType.ZD)
