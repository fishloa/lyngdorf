"""Tests for the Player component (spec §2.5): structural presence,
delegation over the NowPlayingEngine protocol, runtime can_* predicates,
and position_percent math. The transport-write serialisation regression
test is Task 6 (same file)."""

import asyncio
import contextlib
from datetime import UTC, datetime

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from streaming_test import TestParseNowPlaying, load_fixture

from lyngdorf.api import LyngdorfApi
from lyngdorf.components import Player, build_player
from lyngdorf.const import LyngdorfModel
from lyngdorf.exceptions import LyngdorfUnsupportedError
from lyngdorf.states import Control, PlayMode, Repeat
from lyngdorf.streaming import NowPlaying, parse_now_playing

FAKE_IP = "0.0.0.0"


class FakeEngine:
    """Minimal NowPlayingEngine with settable state and recorded calls -
    proves Player is a pure view/delegate with no logic of its own beyond
    position_percent and the can_* membership tests."""

    def __init__(self) -> None:
        self.now_playing: NowPlaying | None = None
        self.position_ms: int | None = None
        self.position_updated_at: datetime | None = None
        self.play_mode: PlayMode | None = None
        self.shuffle: bool | None = None
        self.repeat: Repeat | None = None
        self.available_controls: frozenset[Control] = frozenset()
        self.available_play_modes: frozenset[PlayMode] = frozenset()
        self.can_shuffle: bool = False
        self.available_repeat_modes: frozenset[Repeat] = frozenset()
        self.calls: list[tuple[str, object]] = []

    def register_position_callback(self, cb):
        self.calls.append(("on_position", cb))
        return lambda: self.calls.append(("unsub_position", cb))

    def register_position_jump_callback(self, cb):
        self.calls.append(("on_position_jump", cb))
        return lambda: self.calls.append(("unsub_jump", cb))

    async def async_pause(self) -> bool:
        self.calls.append(("pause", None))
        return True

    async def async_next(self) -> bool:
        self.calls.append(("next", None))
        return True

    async def async_previous(self) -> bool:
        self.calls.append(("previous", None))
        return True

    async def async_seek(self, position_ms: int) -> bool:
        self.calls.append(("seek", position_ms))
        return True

    async def async_set_play_mode(self, mode: PlayMode) -> bool:
        self.calls.append(("set_play_mode", mode))
        return True

    async def async_set_shuffle(self, shuffle: bool) -> bool:
        self.calls.append(("set_shuffle", shuffle))
        return True

    async def async_set_repeat(self, repeat: Repeat) -> bool:
        self.calls.append(("set_repeat", repeat))
        return True


class TestBuildPlayer:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_presence_matches_model_config(self, model):
        """spec §5 tier 1: `player is None` replaces has_position /
        has_streaming_feature()."""
        player = build_player(model, FakeEngine())
        assert (player is not None) is model.config.has_streaming

    def test_presence_anchors(self):
        """Anchors from spec §2.5: None on the TDAI-2170 and the whole P
        series; present on MP-40/50/60 and TDAI-1120/2210/3400."""
        engine = FakeEngine()
        for model in (
            LyngdorfModel.TDAI_2170,
            LyngdorfModel.P_100,
            LyngdorfModel.P_200,
            LyngdorfModel.P_300,
        ):
            assert build_player(model, engine) is None
        for model in (
            LyngdorfModel.MP_40,
            LyngdorfModel.MP_50,
            LyngdorfModel.MP_60,
            LyngdorfModel.TDAI_1120,
            LyngdorfModel.TDAI_2210,
            LyngdorfModel.TDAI_3400,
        ):
            assert build_player(model, engine) is not None


class TestPlayerDelegation:
    def test_can_predicates_are_live_membership_tests(self):
        """spec §5 tier 2: runtime capability stays a predicate, never a
        type - can_* vary with every source switch. Do not 'improve'
        these into structure."""
        engine = FakeEngine()
        player = Player(engine)
        assert (
            player.can_pause,
            player.can_next,
            player.can_previous,
            player.can_seek,
        ) == (False,) * 4

        engine.available_controls = frozenset({Control.PAUSE, Control.SEEK})
        assert player.can_pause is True
        assert player.can_seek is True
        assert player.can_next is False
        assert player.can_previous is False

        engine.available_controls = frozenset()  # source switched away
        assert player.can_pause is False

    def test_reads_delegate(self):
        engine = FakeEngine()
        player = Player(engine)
        now = datetime.now(UTC)
        engine.position_ms = 1234
        engine.position_updated_at = now
        engine.shuffle = True
        engine.repeat = Repeat.ALL
        engine.can_shuffle = True
        assert player.position_ms == 1234
        assert player.position_updated_at is now
        assert player.shuffle is True
        assert player.repeat is Repeat.ALL
        assert player.can_shuffle is True
        assert player.play_modes == frozenset()
        assert player.repeat_modes == frozenset()

    @pytest.mark.asyncio
    async def test_transport_and_mode_writes_delegate(self):
        engine = FakeEngine()
        player = Player(engine)
        assert await player.pause() is True
        assert await player.next_track() is True
        assert await player.previous_track() is True
        assert await player.seek(45_000) is True
        assert await player.set_shuffle(True) is True
        assert await player.set_repeat(Repeat.ONE) is True
        assert [name for name, _ in engine.calls] == [
            "pause",
            "next",
            "previous",
            "seek",
            "set_shuffle",
            "set_repeat",
        ]
        assert ("seek", 45_000) in engine.calls

    def test_position_callbacks_delegate_and_return_the_unsubscribe(self):
        engine = FakeEngine()
        player = Player(engine)
        cb = lambda ms: None  # noqa: E731
        unsub = player.on_position(cb)
        unsub_jump = player.on_position_jump(cb)
        unsub()
        unsub_jump()
        assert [name for name, _ in engine.calls] == [
            "on_position",
            "on_position_jump",
            "unsub_position",
            "unsub_jump",
        ]


class TestPositionPercent:
    def _player_with(self, position_ms, payload=None) -> Player:
        engine = FakeEngine()
        engine.position_ms = position_ms
        if payload is not None:
            engine.now_playing = parse_now_playing(payload)
        return Player(engine)

    def test_none_without_position_or_now_playing(self):
        assert self._player_with(None).position_percent is None
        assert self._player_with(30_000).position_percent is None

    def test_fraction_and_cap(self):
        payload = TestParseNowPlaying.PLAYING_PAYLOAD
        player = self._player_with(30_000, payload)
        duration = player.now_playing.duration_ms
        assert duration  # the fixture track has a real duration
        assert player.position_percent == pytest.approx(min(1.0, 30_000 / duration))
        beyond = self._player_with(duration * 2, payload)
        assert beyond.position_percent == 1.0  # capped, never > 1.0


class TestPlayerGating:
    """The unchanged raise-on-ungated contract (spec §2.5/D7), through a
    real LyngdorfApi engine: the device answers HTTP 200 to anything, so
    a bool return alone can never mean 'honoured' - ungated transport
    calls raise LyngdorfUnsupportedError."""

    @pytest.mark.asyncio
    async def test_pause_raises_when_the_source_offers_no_controls(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        player = build_player(LyngdorfModel.MP_60, api)
        assert player is not None
        assert player.can_pause is False
        with pytest.raises(LyngdorfUnsupportedError):
            await player.pause()

    def test_seeded_now_playing_enables_the_predicates(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._update_now_playing(
            parse_now_playing(
                {
                    **TestParseNowPlaying.PLAYING_PAYLOAD,
                    "controls": {"pause": True},
                }
            )
        )
        player = build_player(LyngdorfModel.MP_60, api)
        assert player is not None
        assert player.can_pause is True
        assert player.now_playing is api.now_playing

    def test_pause_docstring_keeps_the_airplay_warning(self):
        """spec §9 item 9: the pause() source-dependence warning (AirPlay
        session teardown cannot be undone from the device) survives
        verbatim on Player.pause."""
        assert Player.pause.__doc__ is not None
        assert "AirPlay" in Player.pause.__doc__


class TestTransportWritesBypassThePollLock:
    """spec §8: transport writes must NOT queue behind the poll loop's
    serialisation lock. The poll holds its StreamingClient's asyncio.Lock
    for the entire ~25s long-poll request; if pause() were routed through
    that client - the exact consolidation a tidy-minded refactor makes -
    a user's pause would wait out the poll cycle. 1.x semantics: every
    transport write takes a fresh connection with Connection: close.

    Mechanism: a fake device whose pollQueue handler BLOCKS until
    released. With the long poll provably in flight (and the poll
    client's lock therefore held), pause() must still complete within
    2 seconds on its own connection.
    """

    @pytest.mark.asyncio
    async def test_pause_completes_while_a_long_poll_is_in_flight(self):
        poll_in_flight = asyncio.Event()
        release_poll = asyncio.Event()
        peers: set = set()
        write_paths: list[str] = []

        async def handle(request: web.Request) -> web.Response:
            peers.add(request.transport.get_extra_info("peername"))
            path = request.raw_path
            if "/api/event/pollQueue" in path:
                poll_in_flight.set()
                await release_poll.wait()
                return web.json_response([])
            if "/api/event/modifyQueue" in path and "queueId=&" in path:
                return web.json_response("{test-queue}")
            if "/api/event/modifyQueue" in path and "subscribe=" in path:
                return web.Response(text="true", content_type="application/json")
            if "/api/setData" in path:
                write_paths.append(path)
                return web.Response(text="null", content_type="application/json")
            if "/api/getData" in path and "playTime" in path:
                return web.json_response(load_fixture("play_time.json"))
            if "/api/getData" in path and "playMode" in path:
                return web.json_response(load_fixture("play_mode_current.json"))
            if "/api/getData" in path:
                return web.json_response(
                    [
                        {
                            **TestParseNowPlaying.PLAYING_PAYLOAD,
                            "controls": {"pause": True},
                        }
                    ]
                )
            if "/api/getRows" in path:
                return web.json_response(load_fixture("play_modes_roles_value.json"))
            return web.Response(status=404)

        app = web.Application()
        app.router.add_route("GET", "/{tail:.*}", handle)
        server = TestServer(app)
        await server.start_server()
        try:
            api = LyngdorfApi(str(server.host), LyngdorfModel.MP_60)
            api.streammagic_port = server.port
            api._connection_enabled = True
            poll_task = asyncio.ensure_future(api._poll_now_playing())
            try:
                await asyncio.wait_for(poll_in_flight.wait(), 5.0)
                player = build_player(LyngdorfModel.MP_60, api)
                assert player is not None
                assert player.can_pause is True

                result = await asyncio.wait_for(player.pause(), 2.0)
                assert result is True
                assert not release_poll.is_set()
                assert any("/api/setData" in p for p in write_paths)
                assert len(peers) >= 2
            finally:
                release_poll.set()
                api._connection_enabled = False
                poll_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poll_task
        finally:
            await server.close()
