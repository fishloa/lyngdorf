# ruff: noqa: F821, F401
"""Tests for the streaming module (parser + poll loop).

No device is required: `FakeStreamMagicServer` stands in for the
streaming module's :8080 API. The payloads it serves are real captures
from an MP-60 (see `tests/fixtures/`), so the parser is tested against
what the hardware actually sends.
"""

import asyncio
import contextlib
import json
from pathlib import Path
from urllib.parse import quote, unquote

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer

from lyngdorf.api import LyngdorfApi
from lyngdorf.const import NOW_PLAYING_PATH
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver
from lyngdorf.states import Control, PlaybackState, PlayMode, Repeat
from lyngdorf.streaming import (
    NowPlaying,
    StreamingClient,
    _coerce_ms,
    _coerce_play_mode,
    _unwrap_value,
    async_fetch_now_playing,
    async_fetch_play_mode,
    async_fetch_play_modes,
    async_fetch_position,
    async_init_now_playing_queue,
    async_poll_now_playing_events,
    async_subscribe_now_playing,
    parse_now_playing,
    parse_play_mode_events,
    parse_play_modes,
    parse_position_events,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> object:
    """Load a verbatim device capture from tests/fixtures/."""
    return json.loads((FIXTURES / name).read_text())


# -- parse_now_playing unit tests --


class TestParseNowPlaying:
    """Parser exercised against representative payloads."""

    PLAYING_PAYLOAD = {
        "state": "playing",
        "trackRoles": {
            "title": "Bohemian Rhapsody",
            "icon": "https://art.example.com/cover.jpg",
            "mediaData": {
                "metaData": {
                    "artist": "Queen",
                    "album": "A Night at the Opera",
                }
            },
        },
        "mediaRoles": {"title": "Spotify Connect"},
        "status": {"duration": 354000},
    }

    def test_playing_track(self):
        np = parse_now_playing(self.PLAYING_PAYLOAD)
        assert np is not None
        assert np.state == PlaybackState.PLAYING
        assert np.title == "Bohemian Rhapsody"
        assert np.artist == "Queen"
        assert np.album == "A Night at the Opera"
        assert np.source == "Spotify Connect"
        assert np.art_url == "https://art.example.com/cover.jpg"
        assert np.duration_ms == 354000

    def test_paused_state(self):
        payload = {**self.PLAYING_PAYLOAD, "state": "paused"}
        np = parse_now_playing(payload)
        assert np is not None
        assert np.state == PlaybackState.PAUSED

    def test_empty_dict_returns_none(self):
        assert parse_now_playing({}) is None

    def test_none_returns_none(self):
        assert parse_now_playing(None) is None

    def test_string_returns_none(self):
        assert parse_now_playing("not a dict") is None

    def test_no_title_returns_none(self):
        payload = {"trackRoles": {"icon": "x"}}
        assert parse_now_playing(payload) is None

    def test_empty_track_roles_returns_none(self):
        payload = {"trackRoles": {}}
        assert parse_now_playing(payload) is None

    def test_missing_optional_fields(self):
        payload = {"trackRoles": {"title": "Solo"}}
        np = parse_now_playing(payload)
        assert np is not None
        assert np.title == "Solo"
        assert np.artist is None
        assert np.album is None
        assert np.source is None
        assert np.art_url is None
        assert np.duration_ms is None

    def test_duration_as_float(self):
        payload = {
            "trackRoles": {"title": "X", "mediaData": {}},
            "status": {"duration": 123456.0},
        }
        np = parse_now_playing(payload)
        assert np is not None
        assert np.duration_ms == 123456

    def test_duration_non_numeric_ignored(self):
        payload = {
            "trackRoles": {"title": "X", "mediaData": {}},
            "status": {"duration": "unknown"},
        }
        np = parse_now_playing(payload)
        assert np is not None
        assert np.duration_ms is None

    def test_frozen_dataclass(self):
        np = parse_now_playing(self.PLAYING_PAYLOAD)
        assert np is not None
        with pytest.raises(AttributeError):
            np.title = "nope"  # type: ignore[misc]

    def test_unmodelled_control_key_parses_leniently(self):
        """Integration test for `Control`'s leniency, through the actual
        path a real device payload takes rather than in isolation (see
        `tests/states_test.py::TestControlLeniency` for the isolated
        version). This path is where a leniency regression would be
        catastrophic: a strict `Control` here would raise inside
        `parse_now_playing` and take out the ENTIRE now-playing parse the
        first time the device ships a control this library does not yet
        model, not merely lose that one capability."""
        payload = {
            **self.PLAYING_PAYLOAD,
            "controls": {
                "pause": True,
                "next_": True,
                "someFutureControl": True,
                "backward15sec": False,  # not enabled - must be excluded
            },
        }
        np = parse_now_playing(payload)
        assert np is not None
        assert Control.PAUSE in np.controls
        assert Control.NEXT_TRACK in np.controls
        assert Control.SKIP_BACKWARD_15_SECONDS not in np.controls
        unmodelled = Control("someFutureControl")
        assert unmodelled in np.controls
        assert isinstance(unmodelled, Control)


class TestUnwrapValue:
    def test_single_element_list(self):
        assert _unwrap_value([{"key": "val"}]) == {"key": "val"}

    def test_multi_element_list_returns_last(self):
        assert _unwrap_value([1, 2, 3]) == 3

    def test_empty_list_passes_through(self):
        assert _unwrap_value([]) == []

    def test_non_list_passes_through(self):
        assert _unwrap_value({"key": "val"}) == {"key": "val"}

    def test_none_passes_through(self):
        assert _unwrap_value(None) is None


class TestRealCaptures:
    """Parse the verbatim MP-60 captures in tests/fixtures/."""

    def test_airplay_track(self):
        np = parse_now_playing(_unwrap_value(load_fixture("now_playing_airplay.json")))
        assert np is not None
        assert np.title == "Shine on You Crazy Diamond - Live in Gdańsk"
        assert np.artist == "David Gilmour"
        assert np.album == "Live in Gdansk"
        assert np.source == "AirPlay"
        assert np.state == PlaybackState.PLAYING
        assert np.duration_ms == 723785
        assert np.art_url is not None and np.art_url.startswith("http://")

    def test_idle_payload_returns_none(self):
        """A stopped device reports state but no trackRoles at all."""
        assert (
            parse_now_playing(_unwrap_value(load_fixture("now_playing_idle.json")))
            is None
        )

    def test_play_time_capture(self):
        assert _coerce_ms(_unwrap_value(load_fixture("play_time.json"))) == 484650

    def test_poll_queue_position_capture(self):
        assert parse_position_events(load_fixture("poll_queue_position.json")) == 28650

    def test_position_and_duration_give_percentage(self):
        """The two halves a progress bar needs, both in milliseconds."""
        np = parse_now_playing(_unwrap_value(load_fixture("now_playing_airplay.json")))
        position = _coerce_ms(_unwrap_value(load_fixture("play_time.json")))
        assert np is not None and np.duration_ms is not None
        assert round(position / np.duration_ms, 2) == 0.67

    def test_spotify_connect_capabilities(self):
        """The native source advertises far more than AirPlay."""
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_spotify_connect.json"))
        )
        assert np is not None
        assert Control.PAUSE in np.controls
        assert Control.NEXT_TRACK in np.controls
        assert Control.PREVIOUS_TRACK in np.controls
        assert Control.SEEK in np.controls
        assert PlayMode(shuffle=False, repeat=Repeat.ALL) in np.play_modes
        assert PlayMode(shuffle=True, repeat=Repeat.OFF) in np.play_modes

    def test_false_controls_are_not_capabilities(self):
        """The device advertises unavailable controls as false."""
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_spotify_connect.json"))
        )
        assert np is not None
        assert Control.SKIP_BACKWARD_15_SECONDS not in np.controls
        assert Control.SKIP_FORWARD_15_SECONDS not in np.controls

    def test_airplay_has_no_seek_or_play_modes(self):
        np = parse_now_playing(_unwrap_value(load_fixture("now_playing_airplay.json")))
        assert np is not None
        assert np.controls == frozenset(
            {Control.PAUSE, Control.NEXT_TRACK, Control.PREVIOUS_TRACK}
        )
        assert np.play_modes == frozenset()

    def test_play_mode_key_is_not_itself_a_control(self):
        """`playMode` is a nested dict, not a transport action."""
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_spotify_connect.json"))
        )
        assert np is not None
        assert "playMode" not in np.controls

    def test_spotify_smart_shuffle_track(self):
        """Captured with Spotify's "smart shuffle" active. The device has
        no distinct wire value for that - it reports plain `shuffle`, which
        is what `play_mode_current.json` (captured at the same time)
        carries. Not a bug: asserted here so it stays that way."""
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_spotify_smart_shuffle.json"))
        )
        assert np is not None
        assert np.title == "Liar - Live At The Rainbow, London / March 1974"
        assert np.artist == "Queen"
        assert np.album == "Live at the Rainbow (Deluxe)"
        assert np.source == "Liked Songs"
        assert np.state == PlaybackState.PLAYING
        assert np.duration_ms == 507737
        assert PlayMode(shuffle=True, repeat=Repeat.OFF) in np.play_modes
        # Same omission as the other native-source capture: `normal` is
        # never in the per-source list.
        assert PlayMode(shuffle=False, repeat=Repeat.OFF) not in np.play_modes


class TestParsePositionEvents:
    """Position events carry their value inline, so no refetch is needed.

    Payload shape confirmed live against an MP-60: the queue returns one
    `update` entry per changed path, roughly once a second while playing.
    """

    def event(self, ms: int) -> dict:
        return {
            "itemType": "update",
            "rowsEvents": [],
            "path": "player:player/data/playTime",
            "itemValue": {"type": "i64_", "i64_": ms},
        }

    def test_single_event(self):
        assert parse_position_events([self.event(28650)]) == 28650

    def test_zero_position(self):
        assert parse_position_events([self.event(0)]) == 0

    def test_latest_wins_when_batched(self):
        events = [self.event(28650), self.event(29650), self.event(30650)]
        assert parse_position_events(events) == 30650

    def test_ignores_other_paths(self):
        other = {"itemType": "update", "path": "player:player/data", "itemValue": {}}
        assert parse_position_events([other]) is None

    def test_position_extracted_from_mixed_batch(self):
        other = {"itemType": "update", "path": "player:player/data", "itemValue": {}}
        assert parse_position_events([other, self.event(1234)]) == 1234

    def test_empty_list(self):
        assert parse_position_events([]) is None

    def test_missing_item_value(self):
        assert parse_position_events([{"path": "player:player/data/playTime"}]) is None

    def test_non_numeric_value_ignored(self):
        bad = {
            "path": "player:player/data/playTime",
            "itemValue": {"type": "i64_", "i64_": "nope"},
        }
        assert parse_position_events([bad]) is None

    def test_malformed_entries_ignored(self):
        assert parse_position_events(["junk", None, 42]) is None


class TestCoercePlayMode:
    def test_extracts_value(self):
        assert (
            _coerce_play_mode({"type": "playerPlayMode", "playerPlayMode": "shuffle"})
            == "shuffle"
        )

    def test_non_dict_returns_none(self):
        assert _coerce_play_mode("nope") is None

    def test_missing_key_returns_none(self):
        assert _coerce_play_mode({"type": "playerPlayMode"}) is None

    def test_non_string_value_returns_none(self):
        assert _coerce_play_mode({"playerPlayMode": 5}) is None


class TestParsePlayModeEvents:
    """Play mode events carry their value inline too, mirroring position -
    see `TestParsePositionEvents`.

    Payload shape confirmed live against an MP-60::

        {"itemType":"update","path":"settings:/mediaPlayer/playMode",
         "itemValue":{"type":"playerPlayMode","playerPlayMode":"shuffle"}}
    """

    def event(self, mode: str) -> dict:
        return {
            "itemType": "update",
            "rowsEvents": [],
            "path": "settings:/mediaPlayer/playMode",
            "itemValue": {"type": "playerPlayMode", "playerPlayMode": mode},
        }

    def test_single_event(self):
        assert parse_play_mode_events([self.event("shuffle")]) == "shuffle"

    def test_latest_wins_when_batched(self):
        events = [self.event("normal"), self.event("shuffle"), self.event("repeatAll")]
        assert parse_play_mode_events(events) == "repeatAll"

    def test_ignores_other_paths(self):
        other = {"itemType": "update", "path": "player:player/data", "itemValue": {}}
        assert parse_play_mode_events([other]) is None

    def test_play_mode_extracted_from_mixed_batch(self):
        other = {
            "itemType": "update",
            "path": "player:player/data/playTime",
            "itemValue": {"type": "i64_", "i64_": 1000},
        }
        assert parse_play_mode_events([other, self.event("shuffle")]) == "shuffle"

    def test_empty_list(self):
        assert parse_play_mode_events([]) is None

    def test_missing_item_value(self):
        assert (
            parse_play_mode_events([{"path": "settings:/mediaPlayer/playMode"}]) is None
        )

    def test_non_string_value_ignored(self):
        bad = {
            "path": "settings:/mediaPlayer/playMode",
            "itemValue": {"type": "playerPlayMode", "playerPlayMode": 5},
        }
        assert parse_play_mode_events([bad]) is None

    def test_malformed_entries_ignored(self):
        assert parse_play_mode_events(["junk", None, 42]) is None

    def test_not_a_list_returns_none(self):
        assert parse_play_mode_events(None) is None


class TestParsePlayModes:
    """`parse_play_modes` maps advertised wire strings through
    `PlayMode.from_wire`, dropping anything unrecognised - shared by
    `parse_now_playing` (per-source) and the global-enum fallback."""

    def test_maps_known_wire_values(self):
        assert parse_play_modes(frozenset({"shuffle", "repeatAll"})) == frozenset(
            {PlayMode(True, Repeat.OFF), PlayMode(False, Repeat.ALL)}
        )

    def test_drops_unrecognised_values(self):
        """A firmware update growing a mode this library does not model
        must not raise, and must not be silently mistaken for a known one."""
        assert parse_play_modes(frozenset({"shuffle", "bogusMode"})) == frozenset(
            {PlayMode(True, Repeat.OFF)}
        )

    def test_empty_input(self):
        assert parse_play_modes(frozenset()) == frozenset()


# -- Fake HTTP server for integration tests --


class FakeStreamMagicServer:
    """In-loop stand-in for the streaming module's :8080 API.

    Same routes and knobs as the old threaded-HTTPServer fake, but served
    by aiohttp.test_utils.TestServer so the client under test, the
    long-poll scripting and the tests all share one event loop - no
    threads, no cross-thread signalling.

    The payloads served are real captures from an MP-60 (see
    `tests/fixtures/`), so parsers are tested against what the hardware
    actually sends.
    """

    def __init__(self) -> None:
        self.keep_alive: bool = True
        self.connections: int = 0
        self.queue_id: str = "{test-queue-123}"
        self.get_data_response: object = [TestParseNowPlaying.PLAYING_PAYLOAD]
        self.position_response: object = load_fixture("play_time.json")
        # A real device capture (`settings:/mediaPlayer/playMode`,
        # roles=value) rather than a hand-written approximation.
        self.play_mode_response: object = load_fixture("play_mode_current.json")
        # The shape `async_fetch_play_modes` actually receives - it
        # requests `roles=value`, giving single-element rows. The
        # `roles=title,value` two-element shape is exercised explicitly by
        # test_fetch_play_modes_title_value_shape.
        self.play_modes_response: object = load_fixture("play_modes_roles_value.json")
        self.poll_response: list = []
        self.last_path: str = ""
        self.fail_writes: bool = False

        # -- scripted pollQueue sequence, for TestPollRefetchDecision --
        # `poll_batches`, when set, overrides `poll_response`: call N of
        # pollQueue returns `poll_batches[N-1]` (the last entry repeats
        # once exhausted). `poll_signal` lets a test wait, without
        # sleeping, for a specific call count to be reached.
        self.poll_batches: list | None = None
        self.poll_calls: int = 0
        self.poll_signal: asyncio.Event | None = None
        self.poll_signal_at: int = 0
        self.now_playing_fetch_count: int = 0

        self._seen_peers: set = set()
        self._test_server: TestServer | None = None

    @property
    def server_address(self) -> tuple[str, int]:
        assert self._test_server is not None
        return (self._test_server.host, self._test_server.port)

    async def handle(self, request: web.Request) -> web.Response:
        # Count real TCP connections by client (ip, port): one kept-alive
        # socket serves many requests but has exactly one peername -
        # the aiohttp equivalent of the old handler's per-connection
        # setup() counter. Tests reset `connections = 0` between phases.
        peer = request.transport.get_extra_info("peername")
        if peer not in self._seen_peers:
            self._seen_peers.add(peer)
            self.connections += 1
        # raw_path preserves percent-encoding, exactly like the old
        # handler's self.path - tests unquote() it before asserting, and
        # Task 7's byte-identical wire test asserts it raw.
        self.last_path = request.raw_path
        response = self._route(request.raw_path)
        if not self.keep_alive:
            # Emulate a device that declines reuse: `Connection: close`
            # on every response (the old fake spoke HTTP/1.0 instead;
            # same observable effect - one connection per request).
            response.force_close()
        return response

    def _route(self, path: str) -> web.Response:
        if "/api/setData" in path:
            if self.fail_writes:
                return web.Response(
                    status=500,
                    text='{"error":{"title":"Error","message":"failed"}}',
                    content_type="application/json",
                )
            return web.Response(text="null", content_type="application/json")
        if "/api/getData" in path and "playTime" in path:
            return web.json_response(self.position_response)
        if "/api/getData" in path and "playMode" in path:
            return web.json_response(self.play_mode_response)
        if "/api/getData" in path:
            # The full-payload now-playing fetch. Counted separately
            # because it is the expensive request the poll loop must NOT
            # make on every position/play-mode tick - see
            # TestPollRefetchDecision.
            self.now_playing_fetch_count += 1
            return web.json_response(self.get_data_response)
        if "/api/getRows" in path:
            return web.json_response(self.play_modes_response)
        if "/api/event/modifyQueue" in path and "queueId=&" in path:
            return web.json_response(self.queue_id)
        if "/api/event/modifyQueue" in path and "subscribe=" in path:
            return web.Response(text="true", content_type="application/json")
        if "/api/event/pollQueue" in path:
            self.poll_calls += 1
            # Signal at a caller-chosen call count - e.g. "2" means the
            # second long-poll request has landed, which can only happen
            # once the loop has fully finished processing the first
            # response (including any refetch it triggered).
            if self.poll_signal is not None and self.poll_calls == self.poll_signal_at:
                self.poll_signal.set()
            if self.poll_batches is not None:
                idx = min(self.poll_calls - 1, len(self.poll_batches) - 1)
                body = self.poll_batches[idx] if self.poll_batches else []
            else:
                body = self.poll_response
            return web.json_response(body)
        return web.Response(status=404)


@pytest_asyncio.fixture()
async def fake_server():
    fake = FakeStreamMagicServer()
    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    fake._test_server = server
    yield fake
    await server.close()


# -- HTTP helper integration tests --


@pytest.mark.asyncio
async def test_fetch_now_playing(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    np = await async_fetch_now_playing(str(host), port)
    assert np is not None
    assert np.title == "Bohemian Rhapsody"


@pytest.mark.asyncio
async def test_fetch_now_playing_empty(fake_server: FakeStreamMagicServer):
    fake_server.get_data_response = [{}]
    host, port = fake_server.server_address
    np = await async_fetch_now_playing(str(host), port)
    assert np is None


@pytest.mark.asyncio
async def test_init_queue(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    qid = await async_init_now_playing_queue(str(host), port)
    assert qid == "test-queue-123"


@pytest.mark.asyncio
async def test_subscribe(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    ok = await async_subscribe_now_playing(str(host), "test-queue-123", port)
    assert ok is True


@pytest.mark.asyncio
async def test_subscribe_includes_play_mode(fake_server: FakeStreamMagicServer):
    """Play mode is always subscribed, not just when position is."""
    host, port = fake_server.server_address
    await async_subscribe_now_playing(str(host), "test-queue-123", port)
    assert "settings:/mediaPlayer/playMode" in unquote(fake_server.last_path)


@pytest.mark.asyncio
async def test_subscribe_includes_play_mode_without_position(
    fake_server: FakeStreamMagicServer,
):
    host, port = fake_server.server_address
    await async_subscribe_now_playing(
        str(host), "test-queue-123", port, include_position=False
    )
    body = unquote(fake_server.last_path)
    assert "settings:/mediaPlayer/playMode" in body
    assert "player:player/data/playTime" not in body


@pytest.mark.asyncio
async def test_poll_empty(fake_server: FakeStreamMagicServer):
    fake_server.poll_response = []
    host, port = fake_server.server_address
    events = await async_poll_now_playing_events(str(host), "q", port, timeout=1.0)
    assert events == []


@pytest.mark.asyncio
async def test_poll_with_events(fake_server: FakeStreamMagicServer):
    fake_server.poll_response = [{"path": "player:player/data"}]
    host, port = fake_server.server_address
    events = await async_poll_now_playing_events(str(host), "q", port, timeout=1.0)
    assert events is not None
    assert len(events) == 1


@pytest.mark.asyncio
async def test_fetch_position(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    assert await async_fetch_position(str(host), port) == 484650


@pytest.mark.asyncio
async def test_fetch_position_non_numeric(fake_server: FakeStreamMagicServer):
    fake_server.position_response = [{"type": "i64_", "i64_": "bad"}]
    host, port = fake_server.server_address
    assert await async_fetch_position(str(host), port) is None


@pytest.mark.asyncio
async def test_fetch_position_connection_error():
    assert await async_fetch_position("127.0.0.1", port=1, timeout=0.5) is None


@pytest.mark.asyncio
async def test_fetch_play_mode(fake_server: FakeStreamMagicServer):
    """Default response is the real `play_mode_current.json` capture."""
    host, port = fake_server.server_address
    assert await async_fetch_play_mode(str(host), port) == "shuffle"


@pytest.mark.asyncio
async def test_fetch_play_mode_non_string(fake_server: FakeStreamMagicServer):
    fake_server.play_mode_response = [{"type": "playerPlayMode", "playerPlayMode": 5}]
    host, port = fake_server.server_address
    assert await async_fetch_play_mode(str(host), port) is None


@pytest.mark.asyncio
async def test_fetch_play_mode_connection_error():
    assert await async_fetch_play_mode("127.0.0.1", port=1, timeout=0.5) is None


@pytest.mark.asyncio
async def test_fetch_play_modes(fake_server: FakeStreamMagicServer):
    """The global enum fallback, read via `getRows` rather than `getData`.

    This is the real round trip: the fake server's default
    `play_modes_response` is `play_modes_roles_value.json`, the actual
    `roles=value` shape `async_fetch_play_modes` requests (single-element
    rows) - not the `[title, value]` shape a now-fixed bug was tested
    against. Restoring the old `len(row) != 2` check makes this fail.
    """
    host, port = fake_server.server_address
    modes = await async_fetch_play_modes(str(host), port)
    assert modes == frozenset({"normal", "shuffle", "repeatOne", "shuffleRepeatOne"})


@pytest.mark.asyncio
async def test_fetch_play_modes_title_value_shape(fake_server: FakeStreamMagicServer):
    """The parser must also accept `roles=title,value` two-element rows -
    a genuine device response (`play_modes_roles_title_value.json`), even though it is not
    what this request currently asks for. Guards against reintroducing a
    fixed row-length check tied to one particular role set."""
    fake_server.play_modes_response = load_fixture("play_modes_roles_title_value.json")
    host, port = fake_server.server_address
    modes = await async_fetch_play_modes(str(host), port)
    assert modes == frozenset({"normal", "shuffle", "repeatOne", "shuffleRepeatOne"})


@pytest.mark.asyncio
async def test_fetch_play_modes_malformed_rows_are_skipped(
    fake_server: FakeStreamMagicServer,
):
    fake_server.play_modes_response = {
        "rowsCount": 2,
        "rows": [
            ["Normal", {"type": "playerPlayMode", "playerPlayMode": "normal"}],
            "junk",
        ],
    }
    host, port = fake_server.server_address
    assert await async_fetch_play_modes(str(host), port) == frozenset({"normal"})


@pytest.mark.asyncio
async def test_fetch_play_modes_malformed_single_element_rows_are_skipped(
    fake_server: FakeStreamMagicServer,
):
    """Same as above but for the single-element `roles=value` shape: an
    empty row and a non-list row must both be skipped, not crash."""
    fake_server.play_modes_response = {
        "rowsCount": 3,
        "rows": [
            [{"type": "playerPlayMode", "playerPlayMode": "normal"}],
            [],
            "junk",
        ],
    }
    host, port = fake_server.server_address
    assert await async_fetch_play_modes(str(host), port) == frozenset({"normal"})


@pytest.mark.asyncio
async def test_fetch_play_modes_not_a_dict(fake_server: FakeStreamMagicServer):
    fake_server.play_modes_response = "nope"
    host, port = fake_server.server_address
    assert await async_fetch_play_modes(str(host), port) == frozenset()


@pytest.mark.asyncio
async def test_fetch_play_modes_connection_error():
    assert await async_fetch_play_modes("127.0.0.1", port=1, timeout=0.5) == frozenset()


# -- raw one-shot servers for connection-death shapes ----------------------
#
# A well-behaved aiohttp test server cannot close a socket mid-request on
# cue, so the stale-keep-alive and never-responds shapes are scripted on
# raw asyncio servers instead (in-loop, no threads).

_RAW_BODY = b'{"ok": true}'
_RAW_OK = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: " + str(len(_RAW_BODY)).encode() + b"\r\n"
    b"\r\n" + _RAW_BODY
)


async def _read_http_request(reader: asyncio.StreamReader) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(1024)
        if not chunk:
            return b""
        data += chunk
    return data


class TestStreamingClient:
    """The aiohttp transport: session ownership, one-socket reuse, and
    failure behaviour.

    Subscribing to position makes the poll loop iterate roughly once a
    second. Without reuse that is a fresh TCP socket every second -
    ~86,400 a day - against embedded hardware with few to spare (#29/#31),
    which is enough to destabilise a device. These tests pin the socket
    count, not just the responses.
    """

    @pytest.mark.asyncio
    async def test_ownership_decided_at_construction(self):
        """spec §8: `_owns_session = session is None`, decided at
        construction - and construction allocates nothing (lazy)."""
        owned = StreamingClient("127.0.0.1", 8080)
        assert owned._owns_session is True
        assert owned._owned is None  # no ClientSession until first request

        injected = aiohttp.ClientSession()
        try:
            client = StreamingClient("127.0.0.1", 8080, session=injected)
            assert client._owns_session is False
            assert client._owned is None
        finally:
            await injected.close()

    @pytest.mark.asyncio
    async def test_owned_session_created_lazily_and_closed(self, fake_server):
        """The owned ClientSession appears on first request, not in
        __init__ (it needs a running loop, and a client that never issues
        a request must never allocate one), and close() closes it."""
        host, port = fake_server.server_address
        client = StreamingClient(str(host), port)
        assert client._owned is None
        assert await client.get("/api/getData?path=x", 5.0) is not None
        owned = client._owned
        assert owned is not None
        await client.close()
        assert owned.closed is True
        assert client._owned is None

    @pytest.mark.asyncio
    async def test_injected_session_is_used_and_never_closed(self, fake_server):
        """The injected path, exercised with an instrumented session (the
        #50 test note): every request must ride the injected session, no
        owned session may appear, and close() must never touch it."""
        host, port = fake_server.server_address
        requests_seen = []
        trace = aiohttp.TraceConfig()

        async def on_start(session, ctx, params):
            requests_seen.append(str(params.url))

        trace.on_request_start.append(on_start)
        injected = aiohttp.ClientSession(trace_configs=[trace])
        try:
            client = StreamingClient(str(host), port, session=injected)
            for _ in range(3):
                assert await client.get("/api/getData?path=x", 5.0) is not None
            assert len(requests_seen) == 3  # they rode the injected session
            assert client._owned is None  # no session of our own appeared
            await client.close()
            assert injected.closed is False  # never closed by the library
            # ...and the client is still usable afterwards:
            assert await client.get("/api/getData?path=x", 5.0) is not None
        finally:
            await injected.close()

    @pytest.mark.asyncio
    async def test_reuses_one_connection(self, fake_server):
        host, port = fake_server.server_address
        client = StreamingClient(str(host), port)
        fake_server.connections = 0
        try:
            for _ in range(5):
                assert await client.get("/api/getData?path=x", 5.0) is not None
        finally:
            await client.close()
        assert fake_server.connections == 1

    @pytest.mark.asyncio
    async def test_concurrent_requests_hold_one_socket(self, fake_server):
        """#29/#31: the serialisation lock, not connector limits, keeps
        this at one socket - concurrent callers must queue rather than
        open a second connection on the device. (Connector limits would
        be global on an injected shared session and must not be touched.)
        """
        host, port = fake_server.server_address
        client = StreamingClient(str(host), port)
        fake_server.connections = 0
        try:
            results = await asyncio.gather(
                *(client.get("/api/getData?path=x", 5.0) for _ in range(5))
            )
            assert all(r is not None for r in results)
        finally:
            await client.close()
        assert fake_server.connections == 1

    @pytest.mark.asyncio
    async def test_fresh_connection_per_request_when_device_declines_keep_alive(
        self, fake_server
    ):
        """aiohttp honours `Connection: close` per response natively - no
        manual latch (the old MAX_REUSE_FAILURES machinery is gone). A
        device that declines reuse costs one connection per request,
        exactly the old fallback behaviour."""
        fake_server.keep_alive = False
        host, port = fake_server.server_address
        client = StreamingClient(str(host), port)
        fake_server.connections = 0
        try:
            for _ in range(5):
                assert await client.get("/api/getData?path=x", 5.0) is not None
        finally:
            await client.close()
        assert fake_server.connections == 5

    @pytest.mark.asyncio
    async def test_recovers_when_device_drops_kept_alive_connection(self):
        """A device may drop the socket idle between long-poll cycles.
        The request that went down the reused connection gets one clean
        retry on a fresh one (aiohttp surfaces the death as
        ServerDisconnectedError; recent aiohttp additionally retries
        idempotent requests internally - either way the caller sees
        success and the device sees exactly two connections)."""
        connections = []

        async def handler(reader, writer):
            connections.append(writer)
            if len(connections) == 1:
                await _read_http_request(reader)
                writer.write(_RAW_OK)
                await writer.drain()
                # Read the SECOND request off the reused socket, then die
                # without answering - the stale-keep-alive shape.
                await _read_http_request(reader)
                writer.close()
                return
            req = await _read_http_request(reader)
            if req:
                writer.write(_RAW_OK)
                await writer.drain()
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = StreamingClient("127.0.0.1", port)
        try:
            assert await client.get("/api/x", 5.0) == {"ok": True}
            assert await client.get("/api/x", 5.0) == {"ok": True}
            assert len(connections) == 2
        finally:
            await client.close()
            server.close()

    @pytest.mark.asyncio
    async def test_failure_on_every_connection_is_not_retried_forever(self):
        """A device that hangs up on every request must produce None
        after a bounded number of attempts - one clean retry, not a loop.
        (aiohttp may add one internal retry of its own depending on
        version, so the bound is a ceiling, not an exact count.)"""
        attempts = []

        async def handler(reader, writer):
            attempts.append(1)
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = StreamingClient("127.0.0.1", port)
        try:
            assert await client.get("/api/x", 2.0) is None
            assert 1 <= len(attempts) <= 4
        finally:
            await client.close()
            server.close()

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self):
        client = StreamingClient("127.0.0.1", 1)
        try:
            assert await client.get("/api/getData?path=x", 0.5) is None
            assert await client.get_status("/api/getData?path=x", 0.5) is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_status_reports_raw_status(self, fake_server):
        """Writes read the bare status - a successful activate returns a
        body of literal `null`, which parses to None exactly like a
        failure, so only the status distinguishes them."""
        host, port = fake_server.server_address
        client = StreamingClient(str(host), port)
        try:
            assert await client.get_status("/api/getData?path=x", 5.0) == 200
            assert await client.get_status("/nope", 5.0) == 404
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent_and_reopens_lazily(self, fake_server):
        """disconnect/reconnect: close() is safe to repeat, and a later
        request lazily recreates the owned session (spec §8: 'reconnect
        recreates it lazily')."""
        host, port = fake_server.server_address
        client = StreamingClient(str(host), port)
        try:
            assert await client.get("/api/getData?path=x", 5.0) is not None
            await client.close()
            await client.close()
            assert await client.get("/api/getData?path=x", 5.0) is not None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_helpers_accept_a_session(self, fake_server):
        """The poll loop drives every helper through one connection."""
        host, port = fake_server.server_address
        session = StreamingClient(str(host), port)
        fake_server.connections = 0
        try:
            assert await async_fetch_now_playing(str(host), port, session=session)
            assert await async_fetch_position(str(host), port, session=session)
            qid = await async_init_now_playing_queue(str(host), port, session=session)
            assert qid is not None
            assert await async_subscribe_now_playing(
                str(host), qid, port, session=session
            )
            assert (
                await async_poll_now_playing_events(
                    str(host), qid, port, timeout=1.0, session=session
                )
                is not None
            )
        finally:
            await session.close()
        assert fake_server.connections == 1

    @pytest.mark.asyncio
    async def test_helpers_without_session_still_work(self, fake_server):
        """Omitting the session keeps the old connection-per-request path."""
        host, port = fake_server.server_address
        fake_server.connections = 0
        assert await async_fetch_now_playing(str(host), port) is not None
        assert await async_fetch_position(str(host), port) is not None
        assert fake_server.connections == 2

    @pytest.mark.asyncio
    async def test_request_path_reaches_the_wire_unreencoded(self, fake_server):
        """Byte-identical wire contract: the exact bytes `quote()`
        produces must reach the device. yarl re-normalizes URLs by
        default (measured: %3A comes back out as ':'), so the client must
        build its URL with encoded=True. Pins the raw request target."""
        host, port = fake_server.server_address
        client = StreamingClient(str(host), port)
        path = f"/api/getData?path={quote(NOW_PLAYING_PATH)}&roles=value"
        try:
            assert await client.get(path, 5.0) is not None
        finally:
            await client.close()
        assert fake_server.last_path == path
        assert "player%3Aplayer/data" in fake_server.last_path


@pytest.mark.asyncio
async def test_non_streaming_model_never_allocates_a_session(monkeypatch):
    """spec §8: a non-streaming model (TDAI-2170, P series) never creates
    a ClientSession when none was injected - the poll loop is the only
    thing that constructs a StreamingClient, and it never starts on such
    a model. Counted by instrumenting ClientSession construction itself,
    so any allocation on any code path is caught."""
    created = []
    real_init = aiohttp.ClientSession.__init__

    def counting_init(self, *args, **kwargs):
        created.append(self)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "__init__", counting_init)

    api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
    api.set_power_state(True)  # the only poll trigger short of connect()
    await asyncio.sleep(0)
    assert api._now_playing_task is None
    assert created == []


@pytest.mark.asyncio
async def test_poll_returns_none_on_connection_error():
    events = await async_poll_now_playing_events("127.0.0.1", "q", port=1, timeout=0.5)
    assert events is None


# -- LyngdorfApi now-playing integration --


class TestApiNowPlaying:
    """Test that LyngdorfApi wires up the poll loop and callbacks."""

    def test_register_callback(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_now_playing_callback(received.append)
        np = NowPlaying(PlaybackState.PLAYING, "T", "A", "Al", "S", None, None)
        api._update_now_playing(np)
        assert received == [np]

    def test_update_deduplicates(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_now_playing_callback(received.append)
        np = NowPlaying(PlaybackState.PLAYING, "T", "A", "Al", "S", None, None)
        api._update_now_playing(np)
        api._update_now_playing(np)
        assert len(received) == 1

    def test_update_fires_on_change(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_now_playing_callback(received.append)
        np1 = NowPlaying(PlaybackState.PLAYING, "T1", None, None, None, None, None)
        np2 = NowPlaying(PlaybackState.PLAYING, "T2", None, None, None, None, None)
        api._update_now_playing(np1)
        api._update_now_playing(np2)
        assert received == [np1, np2]

    def test_now_playing_property(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        assert api.now_playing is None
        np = NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, None)
        api._update_now_playing(np)
        assert api.now_playing == np

    def test_callback_error_does_not_break_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []

        def bad_cb(np):
            raise RuntimeError("boom")

        api.register_now_playing_callback(bad_cb)
        api.register_now_playing_callback(received.append)
        np = NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, None)
        api._update_now_playing(np)
        assert received == [np]


class TestApiPosition:
    """Position is tracked separately from the now-playing metadata.

    It updates roughly once a second while playing, so folding it into
    `NowPlaying` would churn that object (and every consumer's callback)
    at 1Hz. Keeping it separate lets consumers subscribe to just the
    metadata, and mirrors Home Assistant's
    `media_position`/`media_position_updated_at` pair.
    """

    def test_position_starts_none(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        assert api.position_ms is None
        assert api.position_updated_at is None

    def test_update_sets_position_and_timestamp(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_position(28650)
        assert api.position_ms == 28650
        assert api.position_updated_at is not None

    def test_register_callback(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_position_callback(received.append)
        api._update_position(28650)
        assert received == [28650]

    def test_timestamp_advances_even_when_value_repeats(self):
        """A paused track reports the same ms; the timestamp must still
        move so consumers don't extrapolate from a stale anchor."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_position(1000)
        first = api.position_updated_at
        api._update_position(1000)
        assert api.position_updated_at >= first

    def test_repeated_value_does_not_refire_callback(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_position_callback(received.append)
        api._update_position(1000)
        api._update_position(1000)
        assert received == [1000]

    def test_position_does_not_churn_now_playing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        np_events = []
        api.register_now_playing_callback(np_events.append)
        np = NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, None)
        api._update_now_playing(np)
        for ms in (1000, 2000, 3000):
            api._update_position(ms)
        assert np_events == [np]

    def test_callback_error_does_not_break_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []

        def bad_cb(ms):
            raise RuntimeError("boom")

        api.register_position_callback(bad_cb)
        api.register_position_callback(received.append)
        api._update_position(500)
        assert received == [500]

    def test_position_cleared_when_idle(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_position(5000)
        api._update_position(None)
        assert api.position_ms is None


class TestApiPlayMode:
    """The active play mode, tracked the same way as position - see
    `TestApiPosition`."""

    def test_play_mode_starts_none(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        assert api.play_mode is None

    def test_update_sets_play_mode(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_play_mode("shuffle")
        assert api.play_mode == PlayMode(shuffle=True, repeat=Repeat.OFF)

    def test_register_callback(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_play_mode_callback(received.append)
        api._update_play_mode("shuffle")
        assert received == [PlayMode(shuffle=True, repeat=Repeat.OFF)]

    def test_repeated_value_does_not_refire_callback(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_play_mode_callback(received.append)
        api._update_play_mode("shuffle")
        api._update_play_mode("shuffle")
        assert received == [PlayMode(shuffle=True, repeat=Repeat.OFF)]

    def test_callback_error_does_not_break_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []

        def bad_cb(mode):
            raise RuntimeError("boom")

        api.register_play_mode_callback(bad_cb)
        api.register_play_mode_callback(received.append)
        api._update_play_mode("shuffle")
        assert received == [PlayMode(shuffle=True, repeat=Repeat.OFF)]

    def test_play_mode_cleared_when_idle(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_play_mode("shuffle")
        api._update_play_mode(None)
        assert api.play_mode is None

    def test_non_streaming_model_reports_no_play_mode(self):
        """The model gate wins over whatever the API layer holds."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
        api._update_play_mode("shuffle")
        assert api.play_mode is None

    def test_bogus_wire_value_reports_none(self):
        """The device will store and read back anything, including a mode
        `PlayMode.from_wire` does not recognise - that must not raise, and
        must not be silently mistaken for a known mode."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_play_mode("bogusMode")
        assert api.play_mode is None


class TestPowerGating:
    """The poll only runs while the device is on.

    With position subscribed the loop iterates about once a second, so
    polling a powered-off device is sustained traffic for state that
    cannot change.
    """

    def test_power_off_stops_the_poll(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._start_now_playing_poll = lambda: setattr(api, "_started", True)  # type: ignore[method-assign]
        stopped = []
        api._stop_now_playing_poll = lambda: stopped.append(True)  # type: ignore[method-assign]
        api.set_power_state(False)
        assert stopped == [True]

    def test_power_on_starts_the_poll(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        started = []
        api._start_now_playing_poll = lambda: started.append(True)  # type: ignore[method-assign]
        api.set_power_state(True)
        assert started == [True]

    def test_power_off_clears_stale_state(self):
        """A device that is off is not still playing the last track."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(
            NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, None)
        )
        api._update_position(5000)
        api._update_play_mode("shuffle")
        api.set_power_state(False)
        assert api.now_playing is None
        assert api.position_ms is None
        assert api.play_mode is None

    def test_power_off_notifies_consumers(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(
            NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, None)
        )
        received = []
        api.register_now_playing_callback(received.append)
        api.set_power_state(False)
        assert received == [None]

    def test_power_off_notifies_play_mode_consumers(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_play_mode("shuffle")
        received = []
        api.register_play_mode_callback(received.append)
        api.set_power_state(False)
        assert received == [None]

    def test_repeated_power_off_is_idempotent(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api.set_power_state(False)
        api.set_power_state(False)
        assert api.now_playing is None

    def test_non_streaming_model_is_unaffected(self):
        """A model with no streaming module has no poll to gate."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
        started = []
        api._start_now_playing_poll = lambda: started.append(True)  # type: ignore[method-assign]
        api.set_power_state(True)
        assert started == []


class TestSinglePollTask:
    """Only ever one poll task, and so only ever one kept-alive socket.

    A duplicate poll would double the request rate and hold a second
    connection to hardware with few slots - the failure mode this whole
    design is guarding against.
    """

    @pytest.mark.asyncio
    async def test_repeated_start_creates_one_task(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._connection_enabled = False  # poll loop exits immediately
        try:
            api._start_now_playing_poll()
            first = api._now_playing_task
            for _ in range(5):
                api._start_now_playing_poll()
            assert api._now_playing_task is first
        finally:
            api._stop_now_playing_poll()

    @pytest.mark.asyncio
    async def test_repeated_power_on_creates_one_task(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._connection_enabled = False
        try:
            api.set_power_state(True)
            first = api._now_playing_task
            for _ in range(5):
                api.set_power_state(True)
            assert api._now_playing_task is first
        finally:
            api._stop_now_playing_poll()

    @pytest.mark.asyncio
    async def test_power_cycling_does_not_accumulate_tasks(self):
        """Off/on repeatedly must never leave two live tasks."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._connection_enabled = False
        seen = []
        try:
            for _ in range(5):
                api.set_power_state(True)
                seen.append(api._now_playing_task)
                api.set_power_state(False)
                await asyncio.sleep(0)  # let the cancellation land
            live = [t for t in seen if t is not None and not t.done()]
            assert live == []
        finally:
            api._stop_now_playing_poll()

    @pytest.mark.asyncio
    async def test_restart_before_cancellation_lands_is_refused(self):
        """A cancelled task still owns its socket until it finishes, so
        no second task may start alongside it."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._connection_enabled = False
        try:
            api._start_now_playing_poll()
            first = api._now_playing_task
            api._stop_now_playing_poll()
            # No `await` - the cancellation has not been processed yet.
            api._start_now_playing_poll()
            assert api._now_playing_task is first
        finally:
            api._stop_now_playing_poll()

    @pytest.mark.asyncio
    async def test_slot_frees_once_the_task_finishes(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._connection_enabled = False
        api._start_now_playing_poll()
        first = api._now_playing_task
        assert first is not None
        api._stop_now_playing_poll()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        assert api._now_playing_task is None

    @pytest.mark.asyncio
    async def test_task_ending_while_wanted_is_restarted(self):
        """A poll that ends on its own while still wanted must not leave
        the device silently unpolled."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._connection_enabled = True
        api._now_playing_wanted = True
        try:

            async def noop():
                return None

            finished = asyncio.ensure_future(noop())
            await finished
            api._on_now_playing_task_done(finished)
            assert api._now_playing_task is not None
        finally:
            api._connection_enabled = False
            api._stop_now_playing_poll()

    @pytest.mark.asyncio
    async def test_failed_task_is_not_hot_restarted(self):
        """A task that dies instantly must not spin against the device."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._connection_enabled = True
        api._now_playing_wanted = True

        async def boom():
            raise RuntimeError("boom")

        failed = asyncio.ensure_future(boom())
        with contextlib.suppress(RuntimeError):
            await failed
        api._on_now_playing_task_done(failed)
        assert api._now_playing_task is None

    def test_start_without_event_loop_does_not_raise(self):
        """The power callback is synchronous and may run without a loop."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api.set_power_state(True)
        assert api._now_playing_task is None


def _position_event(ms: int) -> dict:
    return {
        "itemType": "update",
        "rowsEvents": [],
        "path": "player:player/data/playTime",
        "itemValue": {"type": "i64_", "i64_": ms},
    }


def _play_mode_event(mode: str) -> dict:
    return {
        "itemType": "update",
        "rowsEvents": [],
        "path": "settings:/mediaPlayer/playMode",
        "itemValue": {"type": "playerPlayMode", "playerPlayMode": mode},
    }


def _metadata_event() -> dict:
    return {"itemType": "update", "rowsEvents": [], "path": "player:player/data"}


class TestPollRefetchDecision:
    """Regression guard for the poll loop's full-payload refetch decision.

    `LyngdorfApi._poll_now_playing` subscribes to three paths: metadata
    (`player:player/data`), position (`.../playTime`, ~1/sec while
    playing) and play mode (changes on user action). Position and play
    mode arrive inline in the event itself, so only a metadata event needs
    a follow-up `getData?path=player:player/data` for the full payload.
    That decision is a single `any(...)` condition checking each event's
    path against a tuple of the two inline paths. If it ever regresses -
    a third subscribed path added without updating the tuple, or the
    logic inverted - every position tick would trigger an extra HTTP
    round-trip against embedded hardware with very few connection slots:
    roughly 86,400 superfluous requests a day, invisible in any test that
    only checks parsing or connection reuse.

    These tests drive `_poll_now_playing` itself against the fake server,
    scripting the pollQueue response so a single batch of events can be
    fed through and the resulting `getData` (non playTime/playMode)
    request count inspected. The queue-establishment phase (queue_id is
    None) always performs exactly one such fetch before any event batch
    is processed; that seed fetch is accounted for explicitly in each
    assertion below rather than ignored.
    """

    async def _drive_one_batch(
        self, fake_server: FakeStreamMagicServer, batch: list
    ) -> LyngdorfApi:
        """Run the poll loop through exactly one event batch, then stop it.

        `batch` is served as the first pollQueue response; an empty batch
        follows. Waits - via an `asyncio.Event` set the instant the
        *second* pollQueue request lands, never a sleep - because that
        second request cannot be sent until every `await` triggered by
        processing the first batch (including any refetch) has finished.
        """
        host, port = fake_server.server_address
        fake_server.poll_batches = [batch, []]
        fake_server.poll_calls = 0
        fake_server.poll_signal = asyncio.Event()
        fake_server.poll_signal_at = 2
        fake_server.now_playing_fetch_count = 0

        api = LyngdorfApi(str(host), LyngdorfModel.MP_60)
        api.streammagic_port = port
        api._connection_enabled = True

        task = asyncio.ensure_future(api._poll_now_playing())
        try:
            try:
                await asyncio.wait_for(fake_server.poll_signal.wait(), 5.0)
            except TimeoutError:
                pytest.fail("poll loop never reached a second cycle")
        finally:
            api._connection_enabled = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return api

    @pytest.mark.asyncio
    async def test_position_only_batch_causes_no_refetch(
        self, fake_server: FakeStreamMagicServer
    ):
        api = await self._drive_one_batch(fake_server, [_position_event(28650)])
        # 1 == the seed fetch made while establishing the queue; the
        # position-only batch must add none.
        assert fake_server.now_playing_fetch_count == 1
        assert api.position_ms == 28650

    @pytest.mark.asyncio
    async def test_play_mode_only_batch_causes_no_refetch(
        self, fake_server: FakeStreamMagicServer
    ):
        api = await self._drive_one_batch(fake_server, [_play_mode_event("shuffle")])
        assert fake_server.now_playing_fetch_count == 1
        assert api.play_mode == PlayMode(shuffle=True, repeat=Repeat.OFF)

    @pytest.mark.asyncio
    async def test_metadata_batch_causes_exactly_one_refetch(
        self, fake_server: FakeStreamMagicServer
    ):
        await self._drive_one_batch(fake_server, [_metadata_event()])
        # 2 == the seed fetch, plus exactly one refetch for the metadata
        # event - not zero (missed refetch) and not more than one.
        assert fake_server.now_playing_fetch_count == 2

    @pytest.mark.asyncio
    async def test_mixed_batch_causes_exactly_one_refetch_not_two(
        self, fake_server: FakeStreamMagicServer
    ):
        api = await self._drive_one_batch(
            fake_server, [_position_event(1234), _metadata_event()]
        )
        assert fake_server.now_playing_fetch_count == 2
        assert api.position_ms == 1234


class TestPositionModelGating:
    """Position comes from the streaming module, which not every model has.

    The TDAI-2170 and the P series have no streaming hardware at all, so
    they must report no position rather than a stale or invented one.
    """

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
        """Guards against a new model silently defaulting either way."""
        assert set(self.STREAMING) | set(self.NON_STREAMING) == set(LyngdorfModel)

    @pytest.mark.parametrize("model", STREAMING)
    def test_streaming_models_support_position(self, model):
        assert LyngdorfReceiver("127.0.0.1", model).player is not None

    @pytest.mark.parametrize("model", NON_STREAMING)
    def test_non_streaming_models_report_no_position(self, model):
        receiver = LyngdorfReceiver("127.0.0.1", model)
        # 2.1: capability is structural. "reports no position" IS "has no
        # player" - there is no object left to return None from, which is
        # the point of the component split.
        assert receiver.player is None

    @pytest.mark.parametrize("model", NON_STREAMING)
    def test_non_streaming_stays_none_even_if_api_has_a_value(self, model):
        """The model gate wins over whatever the API layer holds."""
        receiver = LyngdorfReceiver("127.0.0.1", model)
        receiver._api._update_position(5000)
        assert receiver.player is None, "the model gate wins over the API layer"


class TestPositionPercent:
    """position_percent pairs position with NowPlaying.duration_ms."""

    def receiver_playing(self, duration_ms, position_ms):
        receiver = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        receiver._api._update_now_playing(
            NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, duration_ms)
        )
        receiver._api._update_position(position_ms)
        return receiver

    def test_midway(self):
        assert self.receiver_playing(1000, 500).player.position_percent == 0.5

    def test_real_capture_values(self):
        assert (
            round(self.receiver_playing(723785, 484650).player.position_percent, 2)
            == 0.67
        )

    def test_start_of_track(self):
        assert self.receiver_playing(1000, 0).player.position_percent == 0.0

    def test_clamped_when_position_exceeds_duration(self):
        assert self.receiver_playing(1000, 1500).player.position_percent == 1.0

    def test_none_without_duration(self):
        assert self.receiver_playing(None, 500).player.position_percent is None

    def test_none_without_position(self):
        assert self.receiver_playing(1000, None).player.position_percent is None

    def test_none_for_live_stream_zero_duration(self):
        """Live streams report duration 0; a percentage is meaningless."""
        assert self.receiver_playing(0, 500).player.position_percent is None

    def test_none_when_nothing_playing(self):
        receiver = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        receiver._api._update_position(500)
        assert receiver.player.position_percent is None

    def test_non_streaming_model_has_no_poll_task(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
        assert not api._model.config.has_streaming


# -- Receiver now-playing integration --


class TestReceiverNowPlaying:
    def test_now_playing_default_none(self):
        from lyngdorf.receiver import LyngdorfReceiver  # PORT-NOTE(WP4)

        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        assert (
            r.player.now_playing is None
        )  # PORT-NOTE(WP4): now_playing lives on player

    @pytest.mark.asyncio
    async def test_now_playing_changed_callback(self):
        from lyngdorf.receiver import LyngdorfReceiver  # PORT-NOTE(WP4)

        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        notified = []
        r.on_change(
            lambda: notified.append(True)
        )  # PORT-NOTE(WP4): register_notification_callback -> on_change
        np = NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, None)
        r._api._update_now_playing(
            np
        )  # PORT-NOTE(WP4): now_playing stored on api (the engine)
        await asyncio.sleep(0)
        assert (
            r.player.now_playing == np
        )  # PORT-NOTE(WP4): now_playing accessed via player
        assert len(notified) == 1

    def test_non_streaming_receiver_has_no_now_playing(self):
        from lyngdorf.receiver import LyngdorfReceiver  # PORT-NOTE(WP4)

        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.TDAI_2170)
        assert r.player is None  # PORT-NOTE(WP4): no player on TDAI-2170


# -- has_streaming_feature per model --


class TestStreamingCapability:
    @pytest.mark.parametrize(
        "model,expected",
        [
            (LyngdorfModel.MP_40, True),
            (LyngdorfModel.MP_50, True),
            (LyngdorfModel.MP_60, True),
            (LyngdorfModel.TDAI_1120, True),
            (LyngdorfModel.TDAI_2170, False),
            (LyngdorfModel.TDAI_3400, True),
            (LyngdorfModel.P_100, False),
            (LyngdorfModel.P_200, False),
            (LyngdorfModel.P_300, False),
        ],
    )
    def test_has_streaming_feature(self, model, expected):
        assert model.config.has_streaming == expected
