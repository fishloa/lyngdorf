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

from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel
from lyngdorf.device import Receiver
from lyngdorf.exceptions import LyngdorfUnsupportedError
from lyngdorf.streaming import (
    CONTROL_NEXT,
    CONTROL_PAUSE,
    CONTROL_PREVIOUS,
    NowPlaying,
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
        assert "path=player:player/control" in _unquote(path)
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


def _np(controls=(), play_modes=()):
    return NowPlaying(
        "playing",
        "T",
        None,
        None,
        None,
        None,
        None,
        frozenset(controls),
        frozenset(play_modes),
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
            await api.async_set_play_mode("repeatAll")

    @pytest.mark.asyncio
    async def test_bogus_play_mode_never_reaches_the_device(self):
        """The device would answer 200 and store it."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["shuffle"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_play_mode("bogusMode")

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
        assert api.available_controls == frozenset({"pause"})
        assert api.available_play_modes == frozenset({"shuffle"})

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
        assert r.available_play_modes == frozenset({"shuffle", "repeatAll"})

    def test_capabilities_vanish_when_stopped(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        r._api._update_now_playing(_np(controls=["pause", "seekTime"]))
        r._api._update_now_playing(None)
        assert (r.can_pause, r.can_seek) == (False, False)
        assert r.available_play_modes == frozenset()

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
