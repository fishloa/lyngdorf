"""Tests for the nowplaying module (parser + poll loop).

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
from threading import Thread

import pytest

from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel
from lyngdorf.device import Receiver
from lyngdorf.nowplaying import (
    NowPlaying,
    StreamMagicSession,
    _coerce_ms,
    _unwrap_value,
    async_fetch_now_playing,
    async_fetch_position,
    async_init_now_playing_queue,
    async_poll_now_playing_events,
    async_subscribe_now_playing,
    parse_now_playing,
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
        assert np.state == "playing"
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
        assert np.state == "paused"

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
        assert np.state == "playing"
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
        if "/api/getData" in self.path and "playTime" in self.path:
            self._respond(json.dumps(self.server.position_response).encode())
        elif "/api/getData" in self.path:
            self._respond(json.dumps(self.server.get_data_response).encode())
        elif "/api/event/modifyQueue" in self.path and "queueId=&" in self.path:
            self._respond(json.dumps(self.server.queue_id).encode())
        elif "/api/event/modifyQueue" in self.path and "subscribe=" in self.path:
            self._respond(b"true")
        elif "/api/event/pollQueue" in self.path:
            self._respond(json.dumps(self.server.poll_response).encode())
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
    poll_response: list = []


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
        np = NowPlaying("playing", "T", "A", "Al", "S", None, None)
        api._update_now_playing(np)
        assert received == [np]

    def test_update_deduplicates(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_now_playing_callback(received.append)
        np = NowPlaying("playing", "T", "A", "Al", "S", None, None)
        api._update_now_playing(np)
        api._update_now_playing(np)
        assert len(received) == 1

    def test_update_fires_on_change(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []
        api.register_now_playing_callback(received.append)
        np1 = NowPlaying("playing", "T1", None, None, None, None, None)
        np2 = NowPlaying("playing", "T2", None, None, None, None, None)
        api._update_now_playing(np1)
        api._update_now_playing(np2)
        assert received == [np1, np2]

    def test_now_playing_property(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        assert api.now_playing is None
        np = NowPlaying("playing", "T", None, None, None, None, None)
        api._update_now_playing(np)
        assert api.now_playing == np

    def test_callback_error_does_not_break_others(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        received = []

        def bad_cb(np):
            raise RuntimeError("boom")

        api.register_now_playing_callback(bad_cb)
        api.register_now_playing_callback(received.append)
        np = NowPlaying("playing", "T", None, None, None, None, None)
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
        np = NowPlaying("playing", "T", None, None, None, None, None)
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
            NowPlaying("playing", "T", None, None, None, None, None)
        )
        api._update_position(5000)
        api.set_power_state(False)
        assert api.now_playing is None
        assert api.position_ms is None

    def test_power_off_notifies_consumers(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(
            NowPlaying("playing", "T", None, None, None, None, None)
        )
        received = []
        api.register_now_playing_callback(received.append)
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
            "playing", "T", None, None, None, None, duration_ms
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
        np = NowPlaying("playing", "T", None, None, None, None, None)
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
