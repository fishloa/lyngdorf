"""Tests for the streaming module (parser + poll loop).

No device is required: `FakeStreamMagicServer` stands in for the
streaming module's :8080 API. The payloads it serves are real captures
from an MP-60 (see `tests/fixtures/`), so the parser is tested against
what the hardware actually sends.
"""

import asyncio
import contextlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import unquote

import pytest

from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel
from lyngdorf.device import Receiver
from lyngdorf.states import Control, PlaybackState, PlayMode, Repeat
from lyngdorf.streaming import (
    NowPlaying,
    StreamMagicSession,
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


class _NowPlayingHandler(BaseHTTPRequestHandler):
    """Minimal stub of the StreamMagic :8080 API."""

    server: "FakeStreamMagicServer"

    def log_message(self, format, *args):
        pass

    @property
    def protocol_version(self):  # type: ignore[override]
        """HTTP/1.1 offers keep-alive; HTTP/1.0 does not."""
        return "HTTP/1.1" if self.server.keep_alive else "HTTP/1.0"

    def setup(self):
        """Called once per TCP connection - counts real sockets."""
        self.server.connections += 1
        super().setup()

    def _respond(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        # Keep-alive needs exact framing or the client cannot find the
        # start of the next response and closes anyway.
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.write(body)

    def do_GET(self):
        self.server.last_path = self.path
        if "/api/setData" in self.path:
            if self.server.fail_writes:
                body = b'{"error":{"title":"Error","message":"failed"}}'
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.write(body)
            else:
                self._respond(b"null")
            return
        if "/api/getData" in self.path and "playTime" in self.path:
            self._respond(json.dumps(self.server.position_response).encode())
        elif "/api/getData" in self.path and "playMode" in self.path:
            self._respond(json.dumps(self.server.play_mode_response).encode())
        elif "/api/getData" in self.path:
            # The full-payload now-playing fetch. Counted separately because
            # it is the expensive request the poll loop must NOT make on
            # every position/play-mode tick - see TestPollRefetchDecision.
            self.server.now_playing_fetch_count += 1
            self._respond(json.dumps(self.server.get_data_response).encode())
        elif "/api/getRows" in self.path:
            self._respond(json.dumps(self.server.play_modes_response).encode())
        elif "/api/event/modifyQueue" in self.path and "queueId=&" in self.path:
            self._respond(json.dumps(self.server.queue_id).encode())
        elif "/api/event/modifyQueue" in self.path and "subscribe=" in self.path:
            self._respond(b"true")
        elif "/api/event/pollQueue" in self.path:
            self.server.poll_calls += 1
            # Signal at a caller-chosen call count - e.g. "2" means the
            # second long-poll request has landed, which can only happen
            # once the loop has fully finished processing the first
            # response (including any refetch it triggered).
            if (
                self.server.poll_signal is not None
                and self.server.poll_calls == self.server.poll_signal_at
            ):
                self.server.poll_signal.set()
            if self.server.poll_batches is not None:
                idx = min(self.server.poll_calls - 1, len(self.server.poll_batches) - 1)
                body = self.server.poll_batches[idx] if self.server.poll_batches else []
            else:
                body = self.server.poll_response
            self._respond(json.dumps(body).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def write(self, data: bytes) -> None:
        self.wfile.write(data)


class FakeStreamMagicServer(HTTPServer):
    keep_alive: bool = True
    connections: int = 0
    queue_id: str = "{test-queue-123}"
    get_data_response: object = [TestParseNowPlaying.PLAYING_PAYLOAD]
    position_response: object = load_fixture("play_time.json")
    play_mode_response: object = [
        {"type": "playerPlayMode", "playerPlayMode": "normal"}
    ]
    play_modes_response: object = load_fixture("play_modes.json")
    poll_response: list = []
    last_path: str = ""
    fail_writes: bool = False

    # -- scripted pollQueue sequence, for TestPollRefetchDecision --
    # `poll_batches`, when set, overrides `poll_response`: call N of
    # pollQueue returns `poll_batches[N-1]` (the last entry repeats once
    # exhausted). `poll_signal` lets a test wait, without sleeping, for a
    # specific call count to be reached.
    poll_batches: list | None = None
    poll_calls: int = 0
    poll_signal: Event | None = None
    poll_signal_at: int = 0
    now_playing_fetch_count: int = 0


@pytest.fixture()
def fake_server():
    server = FakeStreamMagicServer(("127.0.0.1", 0), _NowPlayingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


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
    host, port = fake_server.server_address
    assert await async_fetch_play_mode(str(host), port) == "normal"


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
    """The global enum fallback, read via `getRows` rather than `getData`."""
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
async def test_fetch_play_modes_not_a_dict(fake_server: FakeStreamMagicServer):
    fake_server.play_modes_response = "nope"
    host, port = fake_server.server_address
    assert await async_fetch_play_modes(str(host), port) == frozenset()


@pytest.mark.asyncio
async def test_fetch_play_modes_connection_error():
    assert await async_fetch_play_modes("127.0.0.1", port=1, timeout=0.5) == frozenset()


class TestStreamMagicSession:
    """Connection reuse.

    Subscribing to position makes the poll loop iterate roughly once a
    second. Without reuse that is a fresh TCP socket every second -
    ~86,400 a day - against embedded hardware with few to spare, which is
    enough to destabilise a device. These tests pin the socket count, not
    just the responses.
    """

    @pytest.mark.asyncio
    async def test_reuses_one_connection(self, fake_server):
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        fake_server.connections = 0
        try:
            for _ in range(5):
                assert await session.get("/api/getData?path=x", 5.0) is not None
        finally:
            session.close()
        assert fake_server.connections == 1
        assert session.reused_connection is True

    @pytest.mark.asyncio
    async def test_falls_back_when_keep_alive_unsupported(self, fake_server):
        """Some devices may not offer keep-alive; those must still work."""
        fake_server.keep_alive = False
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        fake_server.connections = 0
        try:
            for _ in range(5):
                assert await session.get("/api/getData?path=x", 5.0) is not None
        finally:
            session.close()
        assert fake_server.connections == 5
        assert session.reused_connection is False

    @pytest.mark.asyncio
    async def test_recovers_when_device_drops_kept_alive_connection(self, fake_server):
        """A connection idle between requests may be dropped server-side;
        that must surface as a retry, not a failed request."""
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        try:
            assert await session.get("/api/getData?path=x", 5.0) is not None
            # Simulate the device hanging up on the idle socket.
            session._conn.sock.close()  # type: ignore[union-attr]
            assert await session.get("/api/getData?path=x", 5.0) is not None
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self):
        session = StreamMagicSession("127.0.0.1", 1)
        assert await session.get("/api/getData?path=x", 0.5) is None

    @pytest.mark.asyncio
    async def test_gives_up_on_keep_alive_after_repeated_failures(self, fake_server):
        """#31 reports a TDAI-3400 that dislikes keep-alive. A device that
        keeps failing reuse must be left alone, not retried forever."""
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        try:
            # The first request opens a fresh connection, so it cannot
            # fail a reuse; every one after it can.
            assert await session.get("/api/getData?path=x", 5.0) is not None
            for _ in range(session.MAX_REUSE_FAILURES):
                session._conn.sock.close()  # type: ignore[union-attr]
                assert await session.get("/api/getData?path=x", 5.0) is not None
            assert session.keep_alive_disabled is True

            # From here on, every request gets its own connection.
            fake_server.connections = 0
            for _ in range(3):
                assert await session.get("/api/getData?path=x", 5.0) is not None
            assert fake_server.connections == 3
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_successful_reuse_clears_the_failure_tally(self, fake_server):
        """An occasional stale socket over a long session must not
        accumulate into a false verdict against the device."""
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        try:
            assert await session.get("/api/getData?path=x", 5.0) is not None
            for _ in range(session.MAX_REUSE_FAILURES * 2):
                session._conn.sock.close()  # type: ignore[union-attr]
                # Fails the reuse, retries on a fresh connection.
                assert await session.get("/api/getData?path=x", 5.0) is not None
                # A clean reuse straight after clears the tally.
                assert await session.get("/api/getData?path=x", 5.0) is not None
            assert session.keep_alive_disabled is False
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, fake_server):
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        await session.get("/api/getData?path=x", 5.0)
        session.close()
        session.close()

    @pytest.mark.asyncio
    async def test_reopens_after_close(self, fake_server):
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        try:
            assert await session.get("/api/getData?path=x", 5.0) is not None
            session.close()
            assert await session.get("/api/getData?path=x", 5.0) is not None
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_helpers_accept_a_session(self, fake_server):
        """The poll loop drives every helper through one connection."""
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
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
            session.close()
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
        follows. Waits - via a `threading.Event` set the instant the
        *second* pollQueue request lands, never a sleep - because that
        second request cannot be sent until every `await` triggered by
        processing the first batch (including any refetch) has finished.
        """
        host, port = fake_server.server_address
        fake_server.poll_batches = [batch, []]
        fake_server.poll_calls = 0
        fake_server.poll_signal = Event()
        fake_server.poll_signal_at = 2
        fake_server.now_playing_fetch_count = 0

        api = LyngdorfApi(str(host), LyngdorfModel.MP_60)
        api.streammagic_port = port
        api._connection_enabled = True

        task = asyncio.ensure_future(api._poll_now_playing())
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, fake_server.poll_signal.wait, 5.0)
            assert (
                fake_server.poll_signal.is_set()
            ), "poll loop never reached a second cycle"
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
        assert Receiver("127.0.0.1", model).has_position is True

    @pytest.mark.parametrize("model", NON_STREAMING)
    def test_non_streaming_models_report_no_position(self, model):
        receiver = Receiver("127.0.0.1", model)
        assert receiver.has_position is False
        assert receiver.position_ms is None
        assert receiver.position_updated_at is None
        assert receiver.position_percent is None

    @pytest.mark.parametrize("model", NON_STREAMING)
    def test_non_streaming_stays_none_even_if_api_has_a_value(self, model):
        """The model gate wins over whatever the API layer holds."""
        receiver = Receiver("127.0.0.1", model)
        receiver._api._update_position(5000)
        assert receiver.position_ms is None


class TestPositionPercent:
    """position_percent pairs position with NowPlaying.duration_ms."""

    def receiver_playing(self, duration_ms, position_ms):
        receiver = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        receiver._now_playing = NowPlaying(
            PlaybackState.PLAYING, "T", None, None, None, None, duration_ms
        )
        receiver._api._update_position(position_ms)
        return receiver

    def test_midway(self):
        assert self.receiver_playing(1000, 500).position_percent == 0.5

    def test_real_capture_values(self):
        assert round(self.receiver_playing(723785, 484650).position_percent, 2) == 0.67

    def test_start_of_track(self):
        assert self.receiver_playing(1000, 0).position_percent == 0.0

    def test_clamped_when_position_exceeds_duration(self):
        assert self.receiver_playing(1000, 1500).position_percent == 1.0

    def test_none_without_duration(self):
        assert self.receiver_playing(None, 500).position_percent is None

    def test_none_without_position(self):
        assert self.receiver_playing(1000, None).position_percent is None

    def test_none_for_live_stream_zero_duration(self):
        """Live streams report duration 0; a percentage is meaningless."""
        assert self.receiver_playing(0, 500).position_percent is None

    def test_none_when_nothing_playing(self):
        receiver = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        receiver._api._update_position(500)
        assert receiver.position_percent is None

    def test_non_streaming_model_has_no_poll_task(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
        assert not api._model.has_streaming_feature()


# -- Receiver now-playing integration --


class TestReceiverNowPlaying:
    def test_now_playing_default_none(self):
        from lyngdorf.device import MP60Receiver

        r = MP60Receiver("127.0.0.1")
        assert r.now_playing is None

    @pytest.mark.asyncio
    async def test_now_playing_changed_callback(self):
        from lyngdorf.device import MP60Receiver

        r = MP60Receiver("127.0.0.1")
        notified = []
        r._notification_callbacks.append(lambda: notified.append(True))
        np = NowPlaying(PlaybackState.PLAYING, "T", None, None, None, None, None)
        r._now_playing_changed(np)
        await asyncio.sleep(0)
        assert r.now_playing == np
        assert len(notified) == 1

    def test_non_streaming_receiver_has_no_now_playing(self):
        from lyngdorf.device import TDAI2170Receiver

        r = TDAI2170Receiver("127.0.0.1")
        assert r.now_playing is None


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
        assert model.has_streaming_feature() == expected
