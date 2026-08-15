"""Tests for the nowplaying module (parser + poll loop)."""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel
from lyngdorf.nowplaying import (
    NowPlaying,
    _unwrap_value,
    async_fetch_now_playing,
    async_init_now_playing_queue,
    async_poll_now_playing_events,
    async_subscribe_now_playing,
    parse_now_playing,
)

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


# -- Fake HTTP server for integration tests --


class _NowPlayingHandler(BaseHTTPRequestHandler):
    """Minimal stub of the StreamMagic :8080 API."""

    server: "FakeStreamMagicServer"

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if "/api/getData" in self.path:
            body = json.dumps(self.server.get_data_response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.write(body)
        elif "/api/event/modifyQueue" in self.path and "queueId=&" in self.path:
            body = json.dumps(self.server.queue_id).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.write(body)
        elif "/api/event/modifyQueue" in self.path and "subscribe=" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.write(b"true")
        elif "/api/event/pollQueue" in self.path:
            body = json.dumps(self.server.poll_response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def write(self, data: bytes) -> None:
        self.wfile.write(data)


class FakeStreamMagicServer(HTTPServer):
    queue_id: str = "{test-queue-123}"
    get_data_response: object = [TestParseNowPlaying.PLAYING_PAYLOAD]
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
