"""Tests for transport control (writes to the :8080 API).

No device required: the fake server from streaming_test stands in.
"""

# `fake_server` is a fixture imported from streaming_test and used as a test
# parameter of the same name in every test below - pyflakes reads each of
# those parameters as a redefinition of the (already "used") import, hence
# the blanket suppression rather than per-line noqa comments.
# ruff: noqa: F811

import json
from urllib.parse import unquote

import pytest
from streaming_test import FakeStreamMagicServer, fake_server  # noqa: F401

from lyngdorf.streaming import (
    CONTROL_NEXT,
    CONTROL_PAUSE,
    CONTROL_PREVIOUS,
    StreamMagicSession,
    _smoip_status,
    async_activate_control,
    async_seek,
    async_set_play_mode,
)


def _unquote(path: str) -> str:
    return unquote(path)


@pytest.mark.asyncio
async def test_status_helper_reports_200(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    assert await _smoip_status(str(host), port, "/api/getData?path=x", 5.0) == 200


@pytest.mark.asyncio
async def test_status_helper_reports_404(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    assert await _smoip_status(str(host), port, "/nope", 5.0) == 404


@pytest.mark.asyncio
async def test_status_helper_none_on_connection_error():
    assert await _smoip_status("127.0.0.1", 1, "/api/getData?path=x", 0.5) is None


@pytest.mark.asyncio
async def test_session_status_reuses_connection(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    session = StreamMagicSession(str(host), port)
    fake_server.connections = 0
    try:
        for _ in range(3):
            assert await session.get_status("/api/getData?path=x", 5.0) == 200
    finally:
        session.close()
    assert fake_server.connections == 1


class TestTransportWireFormat:
    """The exact requests confirmed against a real MP-60."""

    @pytest.mark.asyncio
    async def test_pause_request_shape(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        assert await async_activate_control(str(host), CONTROL_PAUSE, port) is True
        path = fake_server.last_path
        assert "/api/setData" in path
        assert "path=player%3Aplayer%2Fcontrol" in path
        assert "role=activate" in path
        assert json.dumps({"control": "pause"}) in _unquote(path)

    @pytest.mark.asyncio
    async def test_next_uses_trailing_underscore(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        await async_activate_control(str(host), CONTROL_NEXT, port)
        assert '"control": "next_"' in _unquote(fake_server.last_path)

    @pytest.mark.asyncio
    async def test_seek_sends_milliseconds(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        assert await async_seek(str(host), 60000, port) is True
        body = _unquote(fake_server.last_path)
        assert '"control": "seekTime"' in body
        assert '"time": 60000' in body

    @pytest.mark.asyncio
    async def test_play_mode_request_shape(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        assert await async_set_play_mode(str(host), "shuffle", port) is True
        path = _unquote(fake_server.last_path)
        assert "path=settings:/mediaPlayer/playMode" in path
        assert "role=value" in path
        assert '"playerPlayMode": "shuffle"' in path
        assert '"type": "playerPlayMode"' in path

    @pytest.mark.asyncio
    async def test_failure_returns_false(self, fake_server: FakeStreamMagicServer):
        """The device answers a rejected control with HTTP 500."""
        fake_server.fail_writes = True
        host, port = fake_server.server_address
        assert await async_activate_control(str(host), CONTROL_PAUSE, port) is False

    @pytest.mark.asyncio
    async def test_network_failure_returns_false(self):
        assert (
            await async_activate_control("127.0.0.1", CONTROL_PREVIOUS, 1, 0.5) is False
        )

    @pytest.mark.asyncio
    async def test_uses_session_when_given(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        fake_server.connections = 0
        try:
            for control in (CONTROL_PAUSE, CONTROL_NEXT, CONTROL_PREVIOUS):
                assert await async_activate_control(
                    str(host), control, port, session=session
                )
        finally:
            session.close()
        assert fake_server.connections == 1
