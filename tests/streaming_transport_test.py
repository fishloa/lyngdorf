"""Tests for transport control (writes to the :8080 API).

No device required: the fake server from streaming_test stands in.
"""

# `fake_server` is a fixture imported from streaming_test and used as a test
# parameter of the same name in every test below - pyflakes reads each of
# those parameters as a redefinition of the (already "used") import, hence
# the blanket suppression rather than per-line noqa comments.
# ruff: noqa: F811

import contextlib
import json
import socket
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import pytest
from streaming_test import FakeStreamMagicServer, fake_server  # noqa: F401

from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel
from lyngdorf.device import Receiver
from lyngdorf.exceptions import LyngdorfUnsupportedError
from lyngdorf.states import Control, PlaybackState, PlayMode, Repeat
from lyngdorf.streaming import (
    NowPlaying,
    StreamMagicSession,
    _smoip_status,
    async_activate_control,
    async_seek,
    async_set_play_mode,
)


def _garbage_response_server() -> tuple[str, int, socket.socket]:
    """A raw one-shot TCP server that answers with a non-HTTP response.

    Forces `http.client` to raise `http.client.BadStatusLine` (an
    `HTTPException` subclass) out of `getresponse()`, on what is - from
    `StreamMagicSession`'s point of view - a brand-new connection. This is
    the exact "fresh connection" shape #37's fix wave requires writes to
    survive: a device replying with garbage (or a truncated/odd response)
    must not escape as an unhandled exception.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()

    def serve() -> None:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            with contextlib.suppress(OSError):
                conn.recv(4096)
                conn.sendall(b"not a valid http status line\r\n\r\n")

    threading.Thread(target=serve, daemon=True).start()
    return str(host), port, srv


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
        assert await async_activate_control(str(host), Control.PAUSE, port) is True
        path = fake_server.last_path
        assert "/api/setData" in path
        assert "path=player:player/control" in _unquote(path)
        assert "role=activate" in path
        assert json.dumps({"control": "pause"}) in _unquote(path)

    @pytest.mark.asyncio
    async def test_next_uses_trailing_underscore(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        await async_activate_control(str(host), Control.NEXT_TRACK, port)
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
        assert await async_activate_control(str(host), Control.PAUSE, port) is False

    @pytest.mark.asyncio
    async def test_network_failure_returns_false(self):
        assert (
            await async_activate_control("127.0.0.1", Control.PREVIOUS_TRACK, 1, 0.5)
            is False
        )

    @pytest.mark.asyncio
    async def test_uses_session_when_given(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        fake_server.connections = 0
        try:
            for control in (Control.PAUSE, Control.NEXT_TRACK, Control.PREVIOUS_TRACK):
                assert await async_activate_control(
                    str(host), control, port, session=session
                )
        finally:
            session.close()
        assert fake_server.connections == 1


class TestWritesSurviveHttpException:
    """`http.client.HTTPException` (e.g. `BadStatusLine`) on a fresh
    connection must not escape any write path - `async_activate_control`,
    `async_seek` and `async_set_play_mode` all document "returns False on
    rejection or network failure rather than raising", and that promise
    held for `OSError`/`TimeoutError` but not for a malformed HTTP response.
    """

    @pytest.mark.asyncio
    async def test_smoip_status_returns_none(self):
        """The module-level one-shot helper, used when no session is given."""
        host, port, srv = _garbage_response_server()
        try:
            assert await _smoip_status(host, port, "/api/getData?path=x", 2.0) is None
        finally:
            srv.close()

    @pytest.mark.asyncio
    async def test_session_get_status_returns_none_on_fresh_connection(self):
        """The session path: `_conn` is None going in, so this is exactly
        the fresh-connection case - no reused-connection retry applies."""
        host, port, srv = _garbage_response_server()
        session = StreamMagicSession(host, port)
        try:
            assert await session.get_status("/api/getData?path=x", 2.0) is None
        finally:
            session.close()
            srv.close()

    @pytest.mark.asyncio
    async def test_activate_control_returns_false(self):
        host, port, srv = _garbage_response_server()
        try:
            assert (
                await async_activate_control(host, Control.PAUSE, port, timeout=2.0)
                is False
            )
        finally:
            srv.close()

    @pytest.mark.asyncio
    async def test_seek_returns_false(self):
        host, port, srv = _garbage_response_server()
        try:
            assert await async_seek(host, 1000, port, timeout=2.0) is False
        finally:
            srv.close()

    @pytest.mark.asyncio
    async def test_set_play_mode_returns_false(self):
        host, port, srv = _garbage_response_server()
        try:
            assert (
                await async_set_play_mode(host, "shuffle", port, timeout=2.0) is False
            )
        finally:
            srv.close()


def _np(controls=(), play_modes=()):
    """Build a `NowPlaying` from wire-format strings, for test brevity.

    `controls` and `play_modes` are the device's own spellings (e.g.
    "next_", "shuffle") - the same shape every fixture and capture in this
    project uses - converted here to the typed `Control`/`PlayMode` values
    `NowPlaying` actually holds.
    """
    parsed_modes = frozenset(
        mode
        for mode in (PlayMode.from_wire(value) for value in play_modes)
        if mode is not None
    )
    return NowPlaying(
        PlaybackState.PLAYING,
        "T",
        None,
        None,
        None,
        None,
        None,
        frozenset(Control(c) for c in controls),
        parsed_modes,
    )


class TestApiGating:
    """The device accepts anything, so the library must refuse."""

    @pytest.mark.asyncio
    async def test_pause_raises_when_not_advertised(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(controls=["next_"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_pause()

    @pytest.mark.asyncio
    async def test_seek_raises_when_not_advertised(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(controls=["pause"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_seek(1000)

    @pytest.mark.asyncio
    async def test_everything_raises_when_stopped(self):
        """Stopped devices report no controls at all."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(None)
        for call in (api.async_pause(), api.async_next(), api.async_previous()):
            with pytest.raises(LyngdorfUnsupportedError):
                await call

    @pytest.mark.asyncio
    async def test_play_mode_raises_when_not_offered(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["shuffle"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_play_mode(PlayMode(shuffle=False, repeat=Repeat.ALL))

    def test_bogus_wire_value_cannot_become_a_play_mode(self):
        """The device would answer 200 to a nonsense play mode and store it
        - but with `PlayMode` typed, there is no longer a way to even
        construct one to pass to `async_set_play_mode`: `PlayMode.from_wire`
        is the only route from a wire string to a `PlayMode`, and it
        returns None for anything it does not recognise. The gate this
        test used to exercise at the API layer is now enforced by the type
        itself, one level lower."""
        assert PlayMode.from_wire("bogusMode") is None

    @pytest.mark.asyncio
    async def test_non_streaming_model_raises(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
        api._update_now_playing(_np(controls=["pause"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_pause()

    def test_available_sets_reflect_now_playing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        assert api.available_controls == frozenset()
        api._update_now_playing(_np(controls=["pause"], play_modes=["shuffle"]))
        assert api.available_controls == frozenset({Control.PAUSE})
        assert api.available_play_modes == frozenset(
            {PlayMode(shuffle=True, repeat=Repeat.OFF)}
        )

    def test_available_play_modes_falls_back_to_global_enum(self):
        """A source that reports no `playMode` key at all still needs
        something to offer, or every play-mode call raises (issue #32 fix
        wave)."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._global_play_modes = frozenset(
            {PlayMode(shuffle=False, repeat=Repeat.OFF), PlayMode(True, Repeat.OFF)}
        )
        api._update_now_playing(_np(controls=["pause"]))  # no play_modes
        assert api.available_play_modes == frozenset(
            {PlayMode(shuffle=False, repeat=Repeat.OFF), PlayMode(True, Repeat.OFF)}
        )

    def test_available_play_modes_prefers_per_source_list(self):
        """The per-source list is authoritative when non-empty, even if it
        disagrees with the device's global enum."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._global_play_modes = frozenset(
            {PlayMode(shuffle=False, repeat=Repeat.OFF), PlayMode(True, Repeat.OFF)}
        )
        api._update_now_playing(_np(play_modes=["repeatAll", "shuffleRepeatAll"]))
        assert api.available_play_modes == frozenset(
            {PlayMode(False, Repeat.ALL), PlayMode(True, Repeat.ALL)}
        )

    def test_available_play_modes_empty_when_nothing_playing(self):
        """The global fallback only applies while something is playing."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._global_play_modes = frozenset(
            {PlayMode(shuffle=False, repeat=Repeat.OFF), PlayMode(True, Repeat.OFF)}
        )
        assert api.available_play_modes == frozenset()

    @pytest.mark.asyncio
    async def test_supported_call_reaches_the_device(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        api = LyngdorfApi(str(host), LyngdorfModel.MP_60)
        api.streammagic_port = port
        api._update_now_playing(_np(controls=["pause"]))
        assert await api.async_pause() is True
        assert '"control": "pause"' in _unquote(fake_server.last_path)


class TestReceiverCapabilities:
    STREAMING = [
        LyngdorfModel.MP_40,
        LyngdorfModel.MP_50,
        LyngdorfModel.MP_60,
        LyngdorfModel.TDAI_1120,
        LyngdorfModel.TDAI_2210,
        LyngdorfModel.TDAI_3400,
    ]
    NON_STREAMING = [
        LyngdorfModel.TDAI_2170,
        LyngdorfModel.P_100,
        LyngdorfModel.P_200,
        LyngdorfModel.P_300,
    ]

    def test_every_model_is_covered(self):
        assert set(self.STREAMING) | set(self.NON_STREAMING) == set(LyngdorfModel)

    def test_capabilities_follow_the_source(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        assert (r.can_pause, r.can_next, r.can_previous, r.can_seek) == (
            False,
            False,
            False,
            False,
        )
        # AirPlay: no seek
        r._api._update_now_playing(_np(controls=["pause", "next_", "previous"]))
        assert (r.can_pause, r.can_next, r.can_previous, r.can_seek) == (
            True,
            True,
            True,
            False,
        )
        # Spotify Connect: adds seek and play modes
        r._api._update_now_playing(
            _np(
                controls=["pause", "next_", "previous", "seekTime"],
                play_modes=["shuffle", "repeatAll"],
            )
        )
        assert r.can_seek is True
        assert r.available_play_modes == frozenset(
            {PlayMode(True, Repeat.OFF), PlayMode(False, Repeat.ALL)}
        )

    def test_capabilities_vanish_when_stopped(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        r._api._update_now_playing(_np(controls=["pause", "seekTime"]))
        r._api._update_now_playing(None)
        assert (r.can_pause, r.can_seek) == (False, False)
        assert r.available_play_modes == frozenset()

    def test_play_mode_delegates_to_api(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        assert r.play_mode is None
        r._api._update_play_mode("shuffle")
        assert r.play_mode == PlayMode(shuffle=True, repeat=Repeat.OFF)

    @pytest.mark.parametrize(
        "model",
        [
            LyngdorfModel.TDAI_2170,
            LyngdorfModel.P_100,
            LyngdorfModel.P_200,
            LyngdorfModel.P_300,
        ],
    )
    def test_play_mode_none_on_non_streaming_models(self, model):
        r = Receiver("127.0.0.1", model)
        r._api._update_play_mode("shuffle")
        assert r.play_mode is None

    @pytest.mark.parametrize("model", NON_STREAMING)
    def test_non_streaming_models_offer_nothing(self, model):
        r = Receiver("127.0.0.1", model)
        r._api._update_now_playing(_np(controls=["pause"], play_modes=["shuffle"]))
        assert (r.can_pause, r.can_next, r.can_previous, r.can_seek) == (
            False,
            False,
            False,
            False,
        )
        assert r.available_play_modes == frozenset()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", NON_STREAMING)
    async def test_non_streaming_models_raise(self, model):
        r = Receiver("127.0.0.1", model)
        with pytest.raises(LyngdorfUnsupportedError):
            await r.async_pause()

    def test_capability_change_fires_the_existing_callback(self):
        """This is how Home Assistant learns to redraw its buttons."""
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        r.register_notification_callback(lambda: seen.append(r.can_seek))
        r._api._update_now_playing(_np(controls=["pause"]))
        r._api._update_now_playing(_np(controls=["pause", "seekTime"]))
        assert seen == [False, True]


class TestCallbackRegistration:
    """All five register_* methods share one rule: return an idempotent
    unsubscribe, and collapse a duplicate registration to a single entry.

    Each of the four common assertions (detach stops firing, double
    unsubscribe is a no-op, duplicate registration fires once, unregistering
    one leaves others firing) is covered for every registration point.
    """

    # -- LyngdorfApi.register_notification_callback --------------------

    @pytest.mark.asyncio
    async def test_api_notification_unsubscribe_stops_firing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub = api.register_notification_callback(lambda: seen.append(1))
        await api._notify_notification_callbacks()
        unsub()
        await api._notify_notification_callbacks()
        assert seen == [1]

    @pytest.mark.asyncio
    async def test_api_notification_double_unsubscribe_is_noop(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        unsub = api.register_notification_callback(lambda: None)
        unsub()
        unsub()  # must not raise

    @pytest.mark.asyncio
    async def test_api_notification_duplicate_registration_fires_once(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []

        def cb():
            seen.append(1)

        api.register_notification_callback(cb)
        api.register_notification_callback(cb)
        await api._notify_notification_callbacks()
        assert seen == [1]

    @pytest.mark.asyncio
    async def test_api_notification_unregister_one_leaves_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub_a = api.register_notification_callback(lambda: seen.append("a"))
        api.register_notification_callback(lambda: seen.append("b"))
        unsub_a()
        await api._notify_notification_callbacks()
        assert seen == ["b"]

    def test_api_un_register_notification_callback_never_registered_is_noop(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api.un_register_notification_callback(lambda: None)  # must not raise

    # -- LyngdorfApi.register_callback(command, cb) ---------------------

    @pytest.mark.asyncio
    async def test_api_command_callback_unsubscribe_stops_firing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub = api.register_callback("CMD", lambda p1, p2: seen.append((p1, p2)))
        await api._async_run_callbacks("CMD", "1", "2")
        unsub()
        await api._async_run_callbacks("CMD", "3", "4")
        assert seen == [("1", "2")]

    @pytest.mark.asyncio
    async def test_api_command_callback_double_unsubscribe_is_noop(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        unsub = api.register_callback("CMD", lambda p1, p2: None)
        unsub()
        unsub()  # must not raise

    @pytest.mark.asyncio
    async def test_api_command_callback_duplicate_registration_fires_once(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []

        def cb(p1, p2):
            seen.append((p1, p2))

        api.register_callback("CMD", cb)
        api.register_callback("CMD", cb)
        await api._async_run_callbacks("CMD", "1", "2")
        assert seen == [("1", "2")]

    @pytest.mark.asyncio
    async def test_api_command_callback_unregister_one_leaves_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub_a = api.register_callback("CMD", lambda p1, p2: seen.append("a"))
        api.register_callback("CMD", lambda p1, p2: seen.append("b"))
        unsub_a()
        await api._async_run_callbacks("CMD", "1", "2")
        assert seen == ["b"]

    @pytest.mark.asyncio
    async def test_api_command_callback_unsubscribe_does_not_affect_other_command(
        self,
    ):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub_a = api.register_callback("CMD_A", lambda p1, p2: seen.append("a"))
        api.register_callback("CMD_B", lambda p1, p2: seen.append("b"))
        unsub_a()
        await api._async_run_callbacks("CMD_A", "1", "2")
        await api._async_run_callbacks("CMD_B", "1", "2")
        assert seen == ["b"]

    # -- LyngdorfApi.register_now_playing_callback ----------------------

    def test_api_now_playing_unsubscribe_stops_firing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub = api.register_now_playing_callback(lambda np: seen.append(np))
        api._update_now_playing(_np(controls=["pause"]))
        unsub()
        api._update_now_playing(_np(controls=["pause", "seekTime"]))
        assert len(seen) == 1

    def test_api_now_playing_double_unsubscribe_is_noop(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        unsub = api.register_now_playing_callback(lambda np: None)
        unsub()
        unsub()  # must not raise

    def test_api_now_playing_duplicate_registration_fires_once(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []

        def cb(np):
            seen.append(np)

        api.register_now_playing_callback(cb)
        api.register_now_playing_callback(cb)
        api._update_now_playing(_np(controls=["pause"]))
        assert len(seen) == 1

    def test_api_now_playing_unregister_one_leaves_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub_a = api.register_now_playing_callback(lambda np: seen.append("a"))
        api.register_now_playing_callback(lambda np: seen.append("b"))
        unsub_a()
        api._update_now_playing(_np(controls=["pause"]))
        assert seen == ["b"]

    # -- LyngdorfApi.register_position_callback -------------------------

    def test_api_position_unsubscribe_stops_firing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub = api.register_position_callback(lambda pos: seen.append(pos))
        api._update_position(1000)
        unsub()
        api._update_position(2000)
        assert seen == [1000]

    def test_api_position_double_unsubscribe_is_noop(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        unsub = api.register_position_callback(lambda pos: None)
        unsub()
        unsub()  # must not raise

    def test_api_position_duplicate_registration_fires_once(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []

        def cb(pos):
            seen.append(pos)

        api.register_position_callback(cb)
        api.register_position_callback(cb)
        api._update_position(1000)
        assert seen == [1000]

    def test_api_position_unregister_one_leaves_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub_a = api.register_position_callback(lambda pos: seen.append("a"))
        api.register_position_callback(lambda pos: seen.append("b"))
        unsub_a()
        api._update_position(1000)
        assert seen == ["b"]

    # -- Receiver.register_notification_callback -------------------------

    def test_receiver_notification_unsubscribe_stops_firing(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub = r.register_notification_callback(lambda: seen.append(1))
        r._api._update_now_playing(_np(controls=["pause"]))
        unsub()
        r._api._update_now_playing(_np(controls=["pause", "seekTime"]))
        assert seen == [1]

    def test_receiver_notification_double_unsubscribe_is_noop(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        unsub = r.register_notification_callback(lambda: None)
        unsub()
        unsub()  # must not raise

    def test_receiver_notification_duplicate_registration_fires_once(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []

        def cb():
            seen.append(1)

        r.register_notification_callback(cb)
        r.register_notification_callback(cb)
        r._api._update_now_playing(_np(controls=["pause"]))
        assert seen == [1]

    def test_receiver_notification_unregister_one_leaves_others(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub_a = r.register_notification_callback(lambda: seen.append("a"))
        r.register_notification_callback(lambda: seen.append("b"))
        unsub_a()
        r._api._update_now_playing(_np(controls=["pause"]))
        assert seen == ["b"]

    def test_receiver_un_register_notification_callback_never_registered_is_noop(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        r.un_register_notification_callback(lambda: None)  # must not raise


class TestMultiDeviceIsolation:
    """Several Lyngdorf devices may be controlled at once, each with its own
    `Receiver`/`LyngdorfApi`. Nothing here shares state on purpose - every
    callback list and cached value is an instance attribute - but that had
    no regression guard before this test (see the project ledger's Task 6
    finding). Driving one device's api must never be visible on another's.
    """

    def test_now_playing_update_does_not_cross_devices(self):
        a = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        b = Receiver("127.0.0.2", LyngdorfModel.MP_60)
        b_seen = []
        b.register_notification_callback(lambda: b_seen.append(1))

        a._api._update_now_playing(
            _np(controls=["pause", "next_", "previous", "seekTime"])
        )

        assert b_seen == []
        assert (b.can_pause, b.can_next, b.can_previous, b.can_seek) == (
            False,
            False,
            False,
            False,
        )
        assert b.available_play_modes == frozenset()
        assert b.now_playing is None
        # The driven device did see it, confirming the test setup is valid.
        assert a.can_pause is True

    def test_position_update_does_not_cross_devices(self):
        a = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        b = Receiver("127.0.0.2", LyngdorfModel.MP_60)
        b_seen = []
        b._api.register_position_callback(b_seen.append)

        a._api._update_position(28650)

        assert b_seen == []
        assert b.position_ms is None
        assert a.position_ms == 28650

    def test_play_mode_update_does_not_cross_devices(self):
        a = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        b = Receiver("127.0.0.2", LyngdorfModel.MP_60)
        b_seen = []
        b._api.register_play_mode_callback(b_seen.append)

        a._api._update_play_mode("shuffle")

        assert b_seen == []
        assert b.play_mode is None
        assert a.play_mode == PlayMode(shuffle=True, repeat=Repeat.OFF)


class TestShuffleRepeat:
    """`async_set_shuffle`/`async_set_repeat` each replace one field of the
    current `PlayMode` and validate the *resulting* combination, so a
    caller changing one axis can never clobber the other."""

    @pytest.mark.asyncio
    async def test_set_shuffle_preserves_repeat(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        api = LyngdorfApi(str(host), LyngdorfModel.MP_60)
        api.streammagic_port = port
        api._update_now_playing(_np(play_modes=["repeatOne", "shuffleRepeatOne"]))
        api._update_play_mode("repeatOne")

        assert await api.async_set_shuffle(True) is True
        body = _unquote(fake_server.last_path)
        assert '"playerPlayMode": "shuffleRepeatOne"' in body

    @pytest.mark.asyncio
    async def test_set_repeat_preserves_shuffle(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        api = LyngdorfApi(str(host), LyngdorfModel.MP_60)
        api.streammagic_port = port
        api._update_now_playing(_np(play_modes=["shuffle", "shuffleRepeatAll"]))
        api._update_play_mode("shuffle")

        assert await api.async_set_repeat(Repeat.ALL) is True
        body = _unquote(fake_server.last_path)
        assert '"playerPlayMode": "shuffleRepeatAll"' in body

    @pytest.mark.asyncio
    async def test_set_shuffle_raises_when_resulting_combination_unavailable(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal"]))
        api._update_play_mode("normal")
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_shuffle(True)

    @pytest.mark.asyncio
    async def test_set_repeat_raises_when_resulting_combination_unavailable(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal"]))
        api._update_play_mode("normal")
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_repeat(Repeat.ALL)

    @pytest.mark.asyncio
    async def test_set_shuffle_raises_when_no_current_play_mode(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal", "shuffle"]))
        # play_mode itself is still None: nothing has reported the *current*
        # mode yet, only what is available.
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_shuffle(True)

    @pytest.mark.asyncio
    async def test_set_repeat_raises_when_no_current_play_mode(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal", "repeatAll"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_repeat(Repeat.ALL)

    def test_can_shuffle_false_when_only_normal_is_offered(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal"]))
        api._update_play_mode("normal")
        assert api.can_shuffle is False

    def test_can_shuffle_true_when_a_shuffle_toggle_exists(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal", "shuffle"]))
        api._update_play_mode("normal")
        assert api.can_shuffle is True

    def test_can_shuffle_false_without_a_current_play_mode(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal", "shuffle"]))
        assert api.can_shuffle is False

    def test_available_repeat_modes_reachable_from_current_shuffle(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(
            _np(play_modes=["normal", "repeatOne", "shuffle", "shuffleRepeatAll"])
        )
        api._update_play_mode("shuffle")
        assert api.available_repeat_modes == frozenset({Repeat.OFF, Repeat.ALL})

    def test_available_repeat_modes_empty_without_a_current_play_mode(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["normal", "repeatOne"]))
        assert api.available_repeat_modes == frozenset()

    def test_shuffle_and_repeat_properties_derive_from_play_mode(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        assert api.shuffle is None
        assert api.repeat is None
        api._update_play_mode("shuffleRepeatOne")
        assert api.shuffle is True
        assert api.repeat == Repeat.ONE

    def test_non_streaming_model_reports_none_and_empty(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
        api._update_play_mode("shuffle")
        assert api.shuffle is None
        assert api.repeat is None
        assert api.can_shuffle is False
        assert api.available_repeat_modes == frozenset()

    @pytest.mark.asyncio
    async def test_receiver_mirrors_shuffle_and_repeat(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        r = Receiver(str(host), LyngdorfModel.MP_60)
        r._api.streammagic_port = port
        r._api._update_now_playing(_np(play_modes=["repeatOne", "shuffleRepeatOne"]))
        r._api._update_play_mode("repeatOne")

        assert r.shuffle is False
        assert r.repeat == Repeat.ONE
        assert r.can_shuffle is True
        assert r.available_repeat_modes == frozenset({Repeat.ONE})

        assert await r.async_set_shuffle(True) is True
        assert '"playerPlayMode": "shuffleRepeatOne"' in _unquote(fake_server.last_path)

    @pytest.mark.asyncio
    async def test_receiver_async_set_repeat_delegates(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        r = Receiver(str(host), LyngdorfModel.MP_60)
        r._api.streammagic_port = port
        r._api._update_now_playing(_np(play_modes=["shuffle", "shuffleRepeatAll"]))
        r._api._update_play_mode("shuffle")

        assert await r.async_set_repeat(Repeat.ALL) is True
        assert '"playerPlayMode": "shuffleRepeatAll"' in _unquote(fake_server.last_path)


class TestPlayModeForwardedToNotifications:
    """The defect this task fixes: play-mode changes used to update
    `Receiver.play_mode` silently, with no notification firing. Position is
    deliberately NOT forwarded this way - see the comment next to the
    registration in `Receiver.__init__` - so the contrast is tested here
    too, to guard against someone "fixing" that asymmetry later."""

    def test_play_mode_change_fires_notification(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        r.register_notification_callback(lambda: seen.append(r.play_mode))
        r._api._update_play_mode("shuffle")
        assert seen == [PlayMode(shuffle=True, repeat=Repeat.OFF)]

    def test_position_change_does_not_fire_notification(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        r.register_notification_callback(lambda: seen.append(1))
        r._api._update_position(28650)
        assert seen == []


def _now_playing(
    state: PlaybackState = PlaybackState.PLAYING, title: str = "Track A"
) -> NowPlaying:
    return NowPlaying(state, title, None, None, None, None, None)


class _FakeClock:
    """A controllable stand-in for the `datetime` name in `lyngdorf.api`.

    `_update_position` calls `datetime.now(UTC)` by looking up the bare
    name `datetime` in its own module's globals at call time - so replacing
    that name with an object exposing a compatible `.now()` lets a test
    drive the wall clock deterministically, with no real sleeping.
    """

    def __init__(self, start: "datetime") -> None:
        self.current = start

    def now(self, tz=None) -> "datetime":
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class TestPositionJumpCallback:
    """Regression guard for `register_position_jump_callback`: it must fire
    on a genuine discontinuity and, critically, must NOT fire for ordinary
    once-a-second progression - see `_is_position_discontinuity`.

    Every test drives `_update_position` directly against a `_FakeClock`
    rather than sleeping against the real one.
    """

    def _api_with_clock(self) -> tuple[LyngdorfApi, _FakeClock]:
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        clock = _FakeClock(datetime(2024, 1, 1, tzinfo=UTC))
        return api, clock

    def test_steady_progression_fires_raw_never_jump(self, monkeypatch):
        """The test that matters most: this is the guard against a future
        change quietly collapsing the two callbacks and reintroducing a
        Home Assistant state write every second."""
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing())

        raw_seen: list[int | None] = []
        jump_seen: list[int | None] = []
        api.register_position_callback(raw_seen.append)
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(0)  # priming call, establishes "previous"
        raw_seen.clear()
        jump_seen.clear()

        for ms in range(1000, 6000, 1000):
            clock.advance(1.0)
            api._update_position(ms)

        assert raw_seen == [1000, 2000, 3000, 4000, 5000]
        assert jump_seen == []

    def test_seek_fires_both(self, monkeypatch):
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing())

        raw_seen: list[int | None] = []
        jump_seen: list[int | None] = []
        api.register_position_callback(raw_seen.append)
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(0)
        clock.advance(1.0)
        api._update_position(1000)
        raw_seen.clear()
        jump_seen.clear()

        clock.advance(1.0)
        api._update_position(60000)  # expected ~2000, actual 60000

        assert raw_seen == [60000]
        assert jump_seen == [60000]

    def test_pause_fires_both(self, monkeypatch):
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing(state=PlaybackState.PLAYING))

        raw_seen: list[int | None] = []
        jump_seen: list[int | None] = []
        api.register_position_callback(raw_seen.append)
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(1000)
        clock.advance(1.0)
        api._update_now_playing(_now_playing(state=PlaybackState.PAUSED))
        raw_seen.clear()
        jump_seen.clear()

        api._update_position(1000)  # same ms - a paused track repeats it

        assert raw_seen == []  # unchanged value: the raw callback is silent
        assert jump_seen == [1000]  # but pausing is still a discontinuity

    def test_track_change_fires_both(self, monkeypatch):
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing(title="Track A"))

        raw_seen: list[int | None] = []
        jump_seen: list[int | None] = []
        api.register_position_callback(raw_seen.append)
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(1000)
        clock.advance(1.0)
        api._update_now_playing(_now_playing(title="Track B"))
        raw_seen.clear()
        jump_seen.clear()

        api._update_position(2000)  # matches expected elapsed exactly

        assert raw_seen == [2000]
        assert jump_seen == [2000]  # still a discontinuity: the track changed

    def test_first_position_after_idle_fires_both(self, monkeypatch):
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing())

        raw_seen: list[int | None] = []
        jump_seen: list[int | None] = []
        api.register_position_callback(raw_seen.append)
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(5000)

        assert raw_seen == [5000]
        assert jump_seen == [5000]

    def test_position_going_to_none_fires_both(self, monkeypatch):
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing())

        raw_seen: list[int | None] = []
        jump_seen: list[int | None] = []
        api.register_position_callback(raw_seen.append)
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(1000)
        raw_seen.clear()
        jump_seen.clear()

        api._update_position(None)

        assert raw_seen == [None]
        assert jump_seen == [None]

    def test_within_tolerance_does_not_fire_jump(self, monkeypatch):
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing())

        raw_seen: list[int | None] = []
        jump_seen: list[int | None] = []
        api.register_position_callback(raw_seen.append)
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(0)
        clock.advance(1.0)
        api._update_position(1000)
        raw_seen.clear()
        jump_seen.clear()

        clock.advance(1.0)
        # Expected ~2000 (1000 + 1000ms elapsed); 1500ms of drift is inside
        # POSITION_DRIFT_TOLERANCE_MS (2000ms).
        api._update_position(3500)

        assert raw_seen == [3500]
        assert jump_seen == []

    def test_exceeding_tolerance_fires_jump(self, monkeypatch):
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing())

        jump_seen: list[int | None] = []
        api.register_position_jump_callback(jump_seen.append)

        api._update_position(0)
        clock.advance(1.0)
        api._update_position(1000)
        jump_seen.clear()

        clock.advance(1.0)
        # Expected ~2000; 2500ms of drift exceeds the 2000ms tolerance.
        api._update_position(4500)

        assert jump_seen == [4500]

    def test_receiver_register_position_jump_callback_delegates(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        r.register_position_jump_callback(seen.append)
        r._api._update_position(5000)
        assert seen == [5000]

    def test_registration_is_idempotent(self):
        """Same contract as every other register_* method - see
        `TestCallbackRegistration`."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []

        def cb(pos):
            seen.append(pos)

        api.register_position_jump_callback(cb)
        api.register_position_jump_callback(cb)
        api._update_position(1000)
        assert seen == [1000]

    def test_unsubscribe_stops_firing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        unsub = api.register_position_jump_callback(seen.append)
        api._update_position(1000)
        unsub()
        api._update_position(50000)
        assert seen == [1000]

    def test_raw_fires_before_jump(self, monkeypatch):
        """Order matters: a consumer subscribed to both must see the raw
        value land before the jump notification."""
        api, clock = self._api_with_clock()
        monkeypatch.setattr("lyngdorf.api.datetime", clock)
        api._update_now_playing(_now_playing())

        order: list[str] = []
        api.register_position_callback(lambda pos: order.append("raw"))
        api.register_position_jump_callback(lambda pos: order.append("jump"))

        api._update_position(1000)  # first call: both fire

        assert order == ["raw", "jump"]
