"""The streaming module's HTTP API.

Streaming-capable Lyngdorf models (see ``ModelConfig.has_streaming``) embed a
StreamUnlimited streaming module that exposes its own HTTP JSON API on port
8080 - unrelated to the ``:84`` RIO protocol the rest of this library speaks.
This module owns everything spoken to it: the connection, now-playing
metadata, playback position, and transport control.

This API is not documented anywhere by Lyngdorf, Cambridge Audio, or
StreamUnlimited - everything here is derived from observing real device
traffic (confirmed against a real MP-60), the same approach every other
open-source client of this API (e.g. Cambridge Audio's own StreamMagic app
protocol, reimplemented by community projects such as ``aiostreammagic`` and
``ha-lyngdorf``) has had to take. No stability guarantee - a firmware update
could change this without notice.

Mechanism (confirmed live against a real MP-60): rather than polling
``getData`` on a fixed interval, the API supports a push-like long-poll event
queue::

    GET /api/event/modifyQueue?queueId=&subscribe[]=&unsubscribe[]
        -> creates a queue, returns a queueId
    GET /api/event/modifyQueue?queueId=<id>&subscribe=[{"path":...,"type":"itemWithValue"}]&unsubscribe=[]
        -> subscribes the queue to a path
    GET /api/event/pollQueue?queueId=<id>&timeout=<seconds>
        -> blocks server-side for up to `timeout` seconds, returning as
           soon as a subscribed path changes (or an empty list on timeout)

A change event looks like::

    [{"itemType": "update", "rowsEvents": [],
      "path": "player:player/data/playTime",
      "itemValue": {"type": "i64_", "i64_": 28650}}]

For track metadata the event's ``itemValue`` is not parsed - a change just
triggers a fresh one-shot ``getData`` fetch for the authoritative current
value. That keeps exactly one parsing path (`parse_now_playing`, exercised
by both the initial fetch and every subsequent update) instead of two, at
the cost of one extra HTTP round trip per change.

Playback position (`NOW_PLAYING_POSITION_PATH`) is the exception: it is
subscribed on the same queue but read straight off ``itemValue``, because
it changes about once a second and a refetch per tick would mean an extra
HTTP request every second for a single integer.

No websocket is involved. The device does expose one on ``:80`` (Lyngdorf's
own control protocol, subprotocol ``control``), but it carries system/setup/
source state only - nothing about playback - and the streaming module has no
websocket at all. Confirmed against a real MP-60, including that it does not
answer the SMOIP protocol Cambridge Audio's StreamMagic devices use. The
long-poll queue is the push channel for playback state, and is what the
device's own web client uses.

:license: MIT, see LICENSE for more details.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import quote

from .const import (
    CONTROL_PATH,
    NOW_PLAYING_PATH,
    NOW_PLAYING_POSITION_PATH,
    PLAY_MODE_PATH,
    PLAY_MODES_PATH,
    STREAMMAGIC_PORT,
)
from .states import Control, PlaybackState, PlayMode

_LOGGER = logging.getLogger(__package__)

_T = TypeVar("_T")


@dataclass(frozen=True)
class NowPlaying:
    """Now-playing metadata for a streaming-capable model.

    Attributes:
        state: Playback state as reported by the device (e.g. playing,
            paused, transitioning). A lenient `PlaybackState`, so a value
            the device reports that isn't one of the known members still
            comes through usably rather than raising - see `states.py`.
        title: Track title.
        artist: Track artist.
        album: Track album.
        source: Human-readable streaming source name (e.g. "Qobuz
            Connect") - not the RIO `source` input name.
        art_url: Album art URL, if any.
        duration_ms: Track duration in milliseconds, if known. No elapsed/
            position is available from this endpoint.
        controls: Transport actions the device currently offers, e.g.
            {Control.PAUSE, Control.NEXT_TRACK, Control.PREVIOUS_TRACK,
            Control.SEEK}. Source-dependent and empty when nothing is
            playing.
        play_modes: Shuffle/repeat modes the current source offers, built
            by mapping each advertised wire string through
            `PlayMode.from_wire` and dropping any that come back
            unrecognised (logged at debug). Empty on sources that offer
            none.
    """

    state: PlaybackState | None
    title: str | None
    artist: str | None
    album: str | None
    source: str | None
    art_url: str | None
    duration_ms: int | None
    controls: frozenset[Control] = frozenset()
    play_modes: frozenset[PlayMode] = frozenset()


def _enabled_keys(payload: object) -> frozenset[str]:
    """Keys whose value is exactly True.

    The device lists unavailable controls as `false` rather than omitting
    them, so presence is not permission.
    """
    if not isinstance(payload, dict):
        return frozenset()
    return frozenset(k for k, v in payload.items() if v is True)


def parse_now_playing(payload: object) -> NowPlaying | None:
    """Parse a `player:player/data` value payload into `NowPlaying`.

    Returns None for an empty/idle payload (no active streaming session -
    an inactive or non-streaming input reports `{}`) or anything not
    shaped as expected, rather than raising - this endpoint is
    reverse-engineered with no format guarantee.
    """
    if not isinstance(payload, dict):
        return None
    track_roles = payload.get("trackRoles")
    if not isinstance(track_roles, dict) or not track_roles:
        return None

    title = track_roles.get("title")
    if not title:
        return None

    media_data = track_roles.get("mediaData")
    meta_data = media_data.get("metaData") if isinstance(media_data, dict) else None
    meta_data = meta_data if isinstance(meta_data, dict) else {}

    media_roles = payload.get("mediaRoles")
    media_roles = media_roles if isinstance(media_roles, dict) else {}

    status = payload.get("status")
    status = status if isinstance(status, dict) else {}
    duration = status.get("duration")

    controls_payload = payload.get("controls")
    controls_payload = controls_payload if isinstance(controls_payload, dict) else {}
    # `playMode` is a nested capability dict, not a transport action.
    controls = frozenset(
        Control(k)
        for k in _enabled_keys(
            {k: v for k, v in controls_payload.items() if k != "playMode"}
        )
    )
    play_modes = parse_play_modes(_enabled_keys(controls_payload.get("playMode")))

    raw_state = payload.get("state")
    state = PlaybackState(raw_state) if isinstance(raw_state, str) else None

    return NowPlaying(
        state=state,
        title=title,
        artist=meta_data.get("artist"),
        album=meta_data.get("album"),
        source=media_roles.get("title"),
        art_url=track_roles.get("icon"),
        duration_ms=int(duration) if isinstance(duration, (int, float)) else None,
        controls=controls,
        play_modes=play_modes,
    )


def parse_play_modes(wire_values: frozenset[str]) -> frozenset[PlayMode]:
    """Map advertised wire strings through `PlayMode.from_wire`.

    A wire string the device advertises that `PlayMode` does not model
    (a firmware update grew a mode we do not know about) is dropped rather
    than raising - logged at debug, since it means the device offers
    something this library cannot yet represent.
    """
    modes = set()
    for value in wire_values:
        mode = PlayMode.from_wire(value)
        if mode is None:
            _LOGGER.debug("Unmodelled play mode advertised: %r", value)
            continue
        modes.add(mode)
    return frozenset(modes)


def _coerce_ms(raw: object) -> int | None:
    """Pull an integer millisecond count out of a typed-value wrapper.

    Values arrive wrapped as ``{"type": "i64_", "i64_": 28650}``. Bools are
    rejected explicitly - `bool` is an `int` subclass, and a stray `True`
    silently becoming position 1 would be worse than reporting nothing.
    """
    if not isinstance(raw, dict):
        return None
    value = raw.get("i64_")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def parse_position_events(events: object) -> int | None:
    """Extract the newest playback position from a batch of queue events.

    Returns None if the batch contains no position event, so the caller can
    distinguish "position unchanged" from "position is now zero". Malformed
    entries are skipped rather than raising - this API is reverse-engineered
    with no format guarantee.
    """
    if not isinstance(events, list):
        return None

    position: int | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("path") != NOW_PLAYING_POSITION_PATH:
            continue
        ms = _coerce_ms(event.get("itemValue"))
        if ms is not None:
            position = ms
    return position


def _coerce_play_mode(raw: object) -> str | None:
    """Pull the play-mode string out of a typed-value wrapper.

    Values arrive wrapped as ``{"type": "playerPlayMode", "playerPlayMode":
    "shuffle"}``.
    """
    if not isinstance(raw, dict):
        return None
    value = raw.get("playerPlayMode")
    return value if isinstance(value, str) else None


def parse_play_mode_events(events: object) -> str | None:
    """Extract the newest play mode from a batch of queue events.

    Returns None if the batch contains no play-mode event, so the caller
    can distinguish "unchanged" from a real value. Malformed entries are
    skipped rather than raising, matching `parse_position_events`.
    """
    if not isinstance(events, list):
        return None

    mode: str | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("path") != PLAY_MODE_PATH:
            continue
        value = _coerce_play_mode(event.get("itemValue"))
        if value is not None:
            mode = value
    return mode


def _unwrap_value(raw: object) -> object:
    """Unwrap the single-element array a `roles=value` `getData` request
    returns the value inside."""
    if isinstance(raw, list) and raw:
        return raw[-1]
    return raw


class StreamMagicSession:
    """Serialized HTTP access to one device's streaming module.

    Subscribing to playback position makes the long-poll queue return
    about once a second, so a connection-per-request costs roughly 86,400
    TCP sockets a day against embedded hardware that has few to spare.
    This holds one connection open and reuses it instead.

    Keep-alive is detected rather than assumed: `http.client` works out
    from the response whether the connection can be reused (HTTP version,
    `Connection:` header, framing), and a device that declines it simply
    gets a fresh connection each time - the old behaviour. The decision
    is re-read from every response, so a device that stops offering
    keep-alive mid-session is followed rather than fought.

    Requests are serialized: one `http.client` connection cannot carry
    two in flight, and the poll loop is sequential anyway.
    """

    #: Reuse failures tolerated before giving up on keep-alive entirely.
    #: A dropped idle socket is normal and costs one retry; a device that
    #: keeps failing is one that does not really support reuse, and
    #: retrying it forever would double its request count.
    MAX_REUSE_FAILURES = 3

    def __init__(self, host: str, port: int = STREAMMAGIC_PORT) -> None:
        self._host = host
        self._port = port
        self._conn: http.client.HTTPConnection | None = None
        self._lock = asyncio.Lock()
        self._reuse_failures = 0
        self.keep_alive_disabled = False
        """Set once this device has proved it cannot handle reuse.

        #31 reports a TDAI-3400 that replies chunked and "dislikes
        keep-alive", so a device declining it is expected, not
        exceptional. Latching means one connection-per-request from then
        on - the behaviour this class replaced - rather than a failed
        reuse plus a retry on every single request.
        """
        self.reused_connection = False
        """Whether the last request went down an already-open connection.

        Exposed for tests and diagnostics - a device silently falling back
        to connection-per-request is exactly the regression worth seeing.
        """

    async def get(self, path_and_query: str, timeout: float) -> object | None:
        """GET a path and parse the JSON response, reusing the connection.

        Returns None on any network/parse failure rather than raising,
        matching `_smoip_get`.
        """
        async with self._lock:
            text = await self._request(path_and_query, timeout, self._fetch)
        return _decode_json(text, self._host, path_and_query)

    async def get_status(self, path_and_query: str, timeout: float) -> int | None:
        """GET a path and return the HTTP status rather than the body.

        Writes need this: a successful `activate` returns a body of
        literal `null`, which parses to None exactly like a failure, so
        only the status distinguishes them. Everything else - connection
        reuse, the stale-connection retry, the keep-alive latch - is
        shared with `get()` via `_perform`; only what is extracted from
        the response differs.
        """
        async with self._lock:
            return await self._request(path_and_query, timeout, self._fetch_status)

    async def _request(
        self,
        path_and_query: str,
        timeout: float,
        fetch: Callable[[str, float], _T | None],
    ) -> _T | None:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, fetch, path_and_query, timeout),
                timeout=timeout + 1,
            )
        except (TimeoutError, OSError, http.client.HTTPException):
            _LOGGER.debug(
                "%s: StreamMagic request to %s failed", self._host, path_and_query
            )
            self.close()
            return None

    def _fetch(self, path_and_query: str, timeout: float) -> str | None:
        """Run one request, returning the decoded body on HTTP 200."""

        def extract(resp: http.client.HTTPResponse, body: bytes) -> str | None:
            return body.decode(errors="replace") if resp.status == 200 else None

        return self._perform(path_and_query, timeout, extract)

    def _fetch_status(self, path_and_query: str, timeout: float) -> int | None:
        """Run one request, returning the HTTP status rather than the body."""
        return self._perform(path_and_query, timeout, lambda resp, _body: resp.status)

    def _perform(
        self,
        path_and_query: str,
        timeout: float,
        extract: Callable[[http.client.HTTPResponse, bytes], _T | None],
    ) -> _T | None:
        """Run one request, retrying once on a stale kept-alive connection.

        A connection idle since the last request may have been dropped by
        the device without us noticing, which surfaces as an error only
        when we try to use it. That is indistinguishable from a real
        failure at the point it happens, so a reused connection gets one
        clean retry; a fresh connection does not, and the error stands.

        `extract` is the only thing that differs between `get()` and
        `get_status()` - the decoded body for one, the bare status code
        for the other - so the connection/retry/keep-alive machinery
        below exists exactly once rather than once per caller.
        """
        for attempt in (1, 2):
            reusing = self._conn is not None
            self.reused_connection = reusing
            try:
                result = self._perform_once(path_and_query, timeout, extract)
            except (OSError, http.client.HTTPException):
                self.close()
                if reusing:
                    self._note_reuse_failure()
                    if attempt == 1:
                        _LOGGER.debug(
                            "%s: kept-alive connection was stale, retrying", self._host
                        )
                        continue
                raise
            else:
                if reusing:
                    # A reuse that worked clears the tally, so occasional
                    # stale sockets over a long session never add up to a
                    # false verdict against the device.
                    self._reuse_failures = 0
                return result
        return None

    def _note_reuse_failure(self) -> None:
        self._reuse_failures += 1
        if self._reuse_failures < self.MAX_REUSE_FAILURES or self.keep_alive_disabled:
            return
        self.keep_alive_disabled = True
        _LOGGER.debug(
            "%s: keep-alive failed %d times, using one connection per request",
            self._host,
            self._reuse_failures,
        )

    def _perform_once(
        self,
        path_and_query: str,
        timeout: float,
        extract: Callable[[http.client.HTTPResponse, bytes], _T | None],
    ) -> _T | None:
        if self._conn is None:
            self._conn = http.client.HTTPConnection(
                self._host, self._port, timeout=timeout
            )
        conn = self._conn

        headers = {"Connection": "close"} if self.keep_alive_disabled else {}
        conn.request("GET", path_and_query, headers=headers)
        resp = conn.getresponse()
        body = resp.read()

        # `will_close` folds together HTTP version, the `Connection:`
        # header and whether the body was framed well enough to find the
        # next response - i.e. exactly "may this socket be reused". Must
        # be read after the body: consulting it before `resp.read()` can
        # give the wrong answer for chunked/close-delimited framing.
        if resp.will_close or self.keep_alive_disabled:
            self.close()

        return extract(resp, body)

    def close(self) -> None:
        """Drop the connection, if any. Safe to call repeatedly."""
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None


def _decode_json(text: str | None, host: str, path_and_query: str) -> object | None:
    if not text:
        return None
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        _LOGGER.debug("%s: StreamMagic response was not valid JSON", host)
        return None


async def _smoip_get(
    host: str, port: int, path_and_query: str, timeout: float
) -> object | None:
    """GET a StreamMagic API path and parse the JSON response.

    One-shot: opens a connection, uses it once, closes it. For repeated
    requests against the same device - notably the poll loop - use
    `StreamMagicSession`, which keeps the connection open.

    Stdlib `http.client` in `run_in_executor`, matching
    `device.async_get_device_serial()`'s existing pattern - no new
    dependency. Returns None on any error rather than raising, since this
    is a best-effort, reverse-engineered API with no stability guarantee.
    """
    loop = asyncio.get_running_loop()

    def _fetch() -> str | None:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path_and_query, headers={"Connection": "close"})
            resp = conn.getresponse()
            if resp.status != 200:
                return None
            return resp.read().decode(errors="replace")
        finally:
            conn.close()

    try:
        text = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch), timeout=timeout + 1
        )
    except (TimeoutError, OSError, http.client.HTTPException):
        _LOGGER.debug("%s: StreamMagic request to %s failed", host, path_and_query)
        return None

    return _decode_json(text, host, path_and_query)


async def _smoip_status(
    host: str, port: int, path_and_query: str, timeout: float
) -> int | None:
    """One-shot request returning the HTTP status rather than the body.

    Mirrors `_smoip_get`: opens a connection, uses it once, closes it.
    Writes need the bare status because a successful `activate` returns a
    body of literal `null`, indistinguishable from a failure once parsed.
    """
    loop = asyncio.get_running_loop()

    def _fetch() -> int:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path_and_query, headers={"Connection": "close"})
            resp = conn.getresponse()
            resp.read()
            return resp.status
        finally:
            conn.close()

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _fetch), timeout=timeout + 1
        )
    except (TimeoutError, OSError, http.client.HTTPException):
        _LOGGER.debug("%s: StreamMagic request to %s failed", host, path_and_query)
        return None


async def _get_status(
    session: StreamMagicSession | None,
    host: str,
    port: int,
    path_and_query: str,
    timeout: float,
) -> int | None:
    """Route a status request through a reused connection when available."""
    if session is not None:
        return await session.get_status(path_and_query, timeout)
    return await _smoip_status(host, port, path_and_query, timeout)


async def _get(
    session: StreamMagicSession | None,
    host: str,
    port: int,
    path_and_query: str,
    timeout: float,
) -> object | None:
    """Route a request through a reused connection when one is available.

    Every helper below takes an optional session so a caller making
    repeated requests - the poll loop - can hold one connection open,
    while one-off callers keep the simpler connection-per-request path.
    """
    if session is not None:
        return await session.get(path_and_query, timeout)
    return await _smoip_get(host, port, path_and_query, timeout)


async def async_fetch_now_playing(
    host: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> NowPlaying | None:
    """One-shot fetch of the current now-playing state.

    Used both for the initial value before the first long-poll cycle and
    for every subsequent update (see module docstring). Returns None on
    any network/parse failure or idle input - never raises.
    """
    data = await _get(
        session,
        host,
        port,
        f"/api/getData?path={quote(NOW_PLAYING_PATH)}&roles=value",
        timeout,
    )
    if data is None:
        return None
    return parse_now_playing(_unwrap_value(data))


async def async_fetch_position(
    host: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> int | None:
    """One-shot fetch of the current playback position, in milliseconds.

    Used to seed a starting value before the first queue event arrives.
    Returns None on any network/parse failure, or when the device reports
    no position - never raises.
    """
    data = await _get(
        session,
        host,
        port,
        f"/api/getData?path={quote(NOW_PLAYING_POSITION_PATH)}&roles=value",
        timeout,
    )
    if data is None:
        return None
    return _coerce_ms(_unwrap_value(data))


async def async_fetch_play_mode(
    host: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> str | None:
    """One-shot fetch of the current shuffle/repeat mode.

    Used to seed a starting value before the first queue event arrives.
    Returns None on any network/parse failure - never raises.
    """
    data = await _get(
        session,
        host,
        port,
        f"/api/getData?path={quote(PLAY_MODE_PATH)}&roles=value",
        timeout,
    )
    if data is None:
        return None
    return _coerce_play_mode(_unwrap_value(data))


async def async_fetch_play_modes(
    host: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> frozenset[str]:
    """One-shot fetch of the device's global play-mode enum.

    Fallback only: a source's own `NowPlaying.play_modes` is per-source
    and authoritative when non-empty - see `LyngdorfApi.available_play_modes`.
    `settings:/mediaPlayer/playModes` is a list rather than a single value,
    so this uses `getRows` rather than `getData`. Real response shape,
    confirmed against an MP-60::

        {"rowsCount": 4, "rows": [
            ["Normal", {"type": "playerPlayMode", "playerPlayMode": "normal"}],
            ["Shuffle", {"type": "playerPlayMode", "playerPlayMode": "shuffle"}],
            ...
        ]}

    Each row is `[title, value]`; only `value["playerPlayMode"]` is kept.
    Returns an empty set on any failure or unexpected shape, never raises -
    a fallback that itself needs troubleshooting has failed at its one job.
    """
    data = await _get(
        session,
        host,
        port,
        f"/api/getRows?path={quote(PLAY_MODES_PATH)}&roles=value&from=0&to=99",
        timeout,
    )
    if not isinstance(data, dict):
        return frozenset()
    rows = data.get("rows")
    if not isinstance(rows, list):
        return frozenset()

    modes: set[str] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            continue
        mode = _coerce_play_mode(row[1])
        if mode is not None:
            modes.add(mode)
    return frozenset(modes)


async def async_init_now_playing_queue(
    host: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> str | None:
    """Create a new event queue, subscribed to nothing yet.

    Returns the queue ID, or None on failure.
    """
    data = await _get(
        session,
        host,
        port,
        "/api/event/modifyQueue?queueId=&subscribe[]=&unsubscribe[]",
        timeout,
    )
    if not isinstance(data, str):
        return None
    return data.strip("{}") or None


async def async_subscribe_now_playing(
    host: str,
    queue_id: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    include_position: bool = True,
    session: StreamMagicSession | None = None,
) -> bool:
    """Subscribe an existing queue to now-playing changes.

    Play mode is always subscribed alongside track metadata - it changes
    only on user action, not at position's roughly-once-a-second rate, so
    there is no equivalent reason to make it optional. Position is
    subscribed on the same queue by default, so all three arrive over a
    single long-poll connection. Pass `include_position=False` to omit
    position, which drops the update rate from roughly once a second to
    once per track/state/play-mode change.
    """
    paths = [NOW_PLAYING_PATH, PLAY_MODE_PATH]
    if include_position:
        paths.append(NOW_PLAYING_POSITION_PATH)
    subscribe = quote(
        json.dumps([{"path": path, "type": "itemWithValue"} for path in paths])
    )
    data = await _get(
        session,
        host,
        port,
        f"/api/event/modifyQueue?queueId={queue_id}&subscribe={subscribe}&unsubscribe=[]",
        timeout,
    )
    return data is not None


async def async_poll_now_playing_events(
    host: str,
    queue_id: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 25.0,
    session: StreamMagicSession | None = None,
) -> list | None:
    """Long-poll the queue for changes on its subscribed path(s).

    Blocks server-side for up to `timeout` seconds. Returns the (possibly
    empty) list of change events if the call completed, or None if it
    failed outright (network error, or the queue itself has expired/is no
    longer known to the device) - the caller should treat None as a signal
    to discard `queue_id` and re-initialize.
    """
    data = await _get(
        session,
        host,
        port,
        f"/api/event/pollQueue?queueId={queue_id}&timeout={int(timeout)}",
        timeout + 5.0,
    )
    return data if isinstance(data, list) else None


# -- Transport control (writes) ------------------------------------------
#
# Everything below writes to the device. Two behaviours are worth knowing
# before calling any of it.
#
# The device validates nothing. Setting the play mode `bogusMode`
# returns HTTP 200 and reads back as `bogusMode`; so do modes the device
# does not declare. A request succeeding says only that it was accepted,
# never that it will be honoured. Callers must check `NowPlaying.controls`
# and `NowPlaying.play_modes` first - `LyngdorfApi` does.
#
# Pause means different things on different sources. Where the device
# does its own streaming, as with Spotify Connect, `pause` toggles: playing
# to paused and back again, since there is no separate resume command. On
# AirPlay and other controller-driven sources the same command ends the
# session outright, and the device cannot restart it - only the controlling
# app can. The device reports which happened: a real pause leaves `controls`
# populated, a teardown empties it.


async def _write(
    host: str,
    port: int,
    timeout: float,
    session: StreamMagicSession | None,
    path: str,
    role: str,
    value: dict,
    log_context: str,
) -> bool:
    """Shared GET-as-write for `/api/setData`, reporting HTTP success.

    Every write below funnels through here so there is exactly one place
    that decides success. Success is read from the status, never the
    body: the device answers a successful write with literal `null`,
    which parses to None exactly as a failure does.

    `path` is encoded the same way as the read helpers above, so every
    `path=` query in this module is built consistently.
    """
    status = await _get_status(
        session,
        host,
        port,
        f"/api/setData?path={quote(path)}"
        f"&role={role}&value={quote(json.dumps(value))}",
        timeout,
    )
    if status != 200:
        _LOGGER.debug("%s: %s rejected (status %s)", host, log_context, status)
    return status == 200


async def _activate(
    host: str,
    payload: dict,
    port: int,
    timeout: float,
    session: StreamMagicSession | None,
) -> bool:
    """Send one control-node action payload."""
    return await _write(
        host,
        port,
        timeout,
        session,
        CONTROL_PATH,
        "activate",
        payload,
        f"control {payload}",
    )


async def async_activate_control(
    host: str,
    control: Control | str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> bool:
    """Send one transport action, e.g. `Control.PAUSE`.

    Returns False on rejection or network failure rather than raising.
    """
    return await _activate(host, {"control": control}, port, timeout, session)


async def async_seek(
    host: str,
    position_ms: int,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> bool:
    """Seek to an absolute position, in milliseconds.

    The device's own web client sends `{"control": "seek", ...}`, which is
    wrong - that is parsed as the browse-and-play control and answered
    with HTTP 500 "Directory is empty. No playable items found."
    """
    return await _activate(
        host,
        {"control": Control.SEEK, "time": int(position_ms)},
        port,
        timeout,
        session,
    )


async def async_set_play_mode(
    host: str,
    mode: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> bool:
    """Set the combined shuffle/repeat mode, e.g. "shuffle", "repeatAll".

    One enum rather than two flags, so setting it replaces both axes at
    once.
    """
    value = {"type": "playerPlayMode", "playerPlayMode": mode}
    return await _write(
        host,
        port,
        timeout,
        session,
        PLAY_MODE_PATH,
        "value",
        value,
        f"play mode {mode!r}",
    )
