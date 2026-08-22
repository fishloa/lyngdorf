"""Transport to the streaming module's :8080 HTTP API.

The reused-connection session, one-shot helpers, reads, queue management
and transport writes. What the API is and how the long-poll event queue
works is documented on the package (see __init__.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import json
import logging
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import quote

from ..const import (
    CONTROL_PATH,
    NOW_PLAYING_PATH,
    NOW_PLAYING_POSITION_PATH,
    PLAY_MODE_PATH,
    PLAY_MODES_PATH,
    STREAMMAGIC_PORT,
)
from ..states import Control
from .parsers import (
    _coerce_ms,
    _coerce_play_mode,
    _decode_json,
    _unwrap_value,
    parse_now_playing,
)
from .types import NowPlaying

_LOGGER = logging.getLogger(__package__)

_T = TypeVar("_T")


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

    Independently verified on a real TDAI-3400 by @svwhisper: 20
    sequential position fetches through this exact class reused a single
    open connection for 19 of the 20 (`keep_alive_disabled` stayed False
    throughout, zero reuse failures), with one steady ESTABLISHED socket
    and no TIME_WAIT, and `playTime` ticking cleanly in ~1000ms steps.
    That walks back #31's original report that the 3400 "dislikes
    keep-alive" - with plain `http.client` reuse and no forced
    `Connection: close`, it holds one socket open without complaint. The
    chunked/no-`Content-Length` framing #31 also reported still stands as
    a real observation, though, so the detect-and-latch fallback below
    remains as defensive cover - it is simply unexercised on that unit.
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
        exceptional - though see the class docstring: a subsequent field
        test against a real TDAI-3400 (@svwhisper) held keep-alive open
        for 20 sequential requests with zero reuse failures, so this
        latch has not actually been observed to trigger on that model.
        Latching means one connection-per-request from then on - the
        behaviour this class replaced - rather than a failed reuse plus a
        retry on every single request.
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

    Feeds `LyngdorfApi.available_play_modes`, which takes the *union* of
    this and a source's own per-source `NowPlaying.play_modes` rather than
    preferring one over the other: each is a partial view of the device's
    six-value 2x3 grid (this global list omits the `repeatAll` variants;
    the per-source list separately omits `normal`), so neither is
    authoritative alone. `settings:/mediaPlayer/playModes` is a list rather
    than a single value, so this uses `getRows` rather than `getData`.

    Row shape depends on the roles requested, confirmed against an MP-60.
    This request asks for `roles=value`, which gives single-element rows::

        {"rowsCount": 4, "rows": [
            [{"type": "playerPlayMode", "playerPlayMode": "normal"}],
            [{"type": "playerPlayMode", "playerPlayMode": "shuffle"}],
            ...
        ]}

    Requesting `roles=title,value` instead gives two-element rows::

        {"rowsCount": 4, "rows": [
            ["Normal", {"type": "playerPlayMode", "playerPlayMode": "normal"}],
            ["Shuffle", {"type": "playerPlayMode", "playerPlayMode": "shuffle"}],
            ...
        ]}

    Either way the value is the LAST element of the row, so it is read from
    `row[-1]` rather than a fixed index - a row is accepted as long as it is
    a non-empty list whose last element coerces to a play mode. This keeps
    the parser correct regardless of which roles a future change requests,
    rather than silently discarding every row whenever the two disagree
    about row length.
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
        if not isinstance(row, list) or not row:
            continue
        mode = _coerce_play_mode(row[-1])
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
