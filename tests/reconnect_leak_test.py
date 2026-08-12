"""Regression test for the reconnect connection-leak.

Before the fix, a single device-initiated disconnect double-fired the
reconnect path (``eof_received`` calls both ``close()`` and
``on_connection_lost``) and raced through the ``self.healthy`` guard in
``_async_reconnect`` (checked before the connect lock was held), so two
connections were opened and one was left **orphaned** - still ESTABLISHED on
the device. On a device with a small connection table (e.g. a TDAI-3400,
control port 84) these accumulate until it refuses all clients.

This test stands a fake asyncio server in for the device and asserts that N
device-initiated drops leave exactly one live connection and open no more
than N+1 in total.
"""

import asyncio

import pytest

from lyngdorf import api as lyngdorf_api
from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel


class _FakeAmp(asyncio.Protocol):
    """Counts connections received and how many are still open."""

    total = 0
    live = 0

    def connection_made(self, transport):
        type(self).total += 1
        type(self).live += 1

    def connection_lost(self, exc):
        type(self).live -= 1

    def data_received(self, data):
        # Swallow the client's setup-command burst. A real device replies,
        # but the reconnect logic under test doesn't depend on replies.
        pass


async def _wait_healthy(api, timeout=2.0):
    elapsed = 0.0
    while not api.healthy and elapsed < timeout:
        await asyncio.sleep(0.02)
        elapsed += 0.02
    assert api.healthy, "client never became healthy"


@pytest.mark.asyncio
async def test_reconnect_does_not_leak_connections(monkeypatch):
    _FakeAmp.total = 0
    _FakeAmp.live = 0

    loop = asyncio.get_running_loop()
    server = await loop.create_server(_FakeAmp, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(lyngdorf_api, "DEFAULT_LYNGDORF_PORT", port)

    api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_3400)
    try:
        await api.async_connect()
        await _wait_healthy(api)
        assert _FakeAmp.live == 1

        n_drops = 3
        for _ in range(n_drops):
            # Simulate the device dropping the link (FIN -> client eof_received)
            assert api._protocol is not None
            api._protocol.eof_received()
            await _wait_healthy(api)

        # Let any stray reconnect tasks / server-side closes settle.
        await asyncio.sleep(0.3)

        assert api.healthy
        assert _FakeAmp.live == 1, (
            f"orphaned/leaked connections left open on device: " f"{_FakeAmp.live - 1}"
        )
        assert _FakeAmp.total <= n_drops + 1, (
            f"opened too many connections: {_FakeAmp.total} "
            f"(expected <= {n_drops + 1})"
        )
    finally:
        await api.async_disconnect()
        server.close()
        # A leak leaves orphaned client sockets open, which would make
        # wait_closed() hang; drop server-side conns and bound the wait so
        # the assertions above surface as a clean failure rather than a hang.
        if hasattr(server, "close_clients"):
            server.close_clients()
        try:
            await asyncio.wait_for(server.wait_closed(), 2.0)
        except TimeoutError:
            pass
