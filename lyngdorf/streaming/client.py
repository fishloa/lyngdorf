"""Transport to the streaming module's :8080 HTTP API.

The reused-connection session, one-shot helpers, reads, queue management
and transport writes. What the API is and how the long-poll event queue
works is documented on the package (see __init__.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import quote

import aiohttp
from yarl import URL

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


class StreamingClient:
    """Serialized aiohttp access to one device's streaming module.

    Subscribing to playback position makes the long-poll queue return
    about once a second, so a connection-per-request costs roughly
    86,400 TCP sockets a day against embedded hardware that has few to
    spare (#29/#31). This holds one warm connection and reuses it: the
    requests are serialized by `_lock`, so aiohttp's per-host pool never
    grows past one connection. Deliberately NOT enforced via connector
    limits - a limit would be global on an injected shared session
    (typically Home Assistant's, shared by every integration in the
    process) and must not be touched.

    Session ownership (issue #50, `inject-websession`): decided at
    construction - `_owns_session = session is None`. An injected
    session is used for every request and is never closed by this class;
    an owned session is created lazily on first use (a ClientSession
    needs a running event loop, and a client that never issues a
    request - e.g. on a non-streaming model - must never allocate one)
    and is closed by `close()`. A request after `close()` lazily
    recreates the owned session, so reconnect needs no special handling.

    A device may drop the kept-alive socket while it sits idle between
    long-poll cycles; that surfaces on the next request as
    `aiohttp.ServerDisconnectedError`, which gets one clean retry
    (recent aiohttp versions also retry idempotent requests internally,
    but the dependency floor is aiohttp>=3.0.0, so the rule is enforced
    here rather than assumed). Anything else - timeout, refused
    connection, malformed response - returns None, matching every
    helper's never-raises contract for this reverse-engineered API.

    Keep-alive history, so it is not re-litigated: the old
    http.client-based session carried a MAX_REUSE_FAILURES latch for
    #31's report that a TDAI-3400 replies chunked and "dislikes
    keep-alive". A field test on a real TDAI-3400 by @svwhisper then
    showed 20 sequential position fetches reusing a single open
    connection (one steady ESTABLISHED socket, no TIME_WAIT, zero reuse
    failures), walking that report back. aiohttp honours
    `Connection: close` per response natively, so a device that declines
    reuse simply gets a fresh connection per request - the old fallback
    behaviour - and the manual latch is gone.
    """

    def __init__(
        self,
        host: str,
        port: int = STREAMMAGIC_PORT,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._injected = session
        self._owns_session = session is None
        # Created lazily on first request, never here: a ClientSession
        # needs a running event loop, and an instance that never issues
        # a request must never allocate one.
        self._owned: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    def _session(self) -> aiohttp.ClientSession:
        if not self._owns_session:
            assert self._injected is not None
            return self._injected
        if self._owned is None or self._owned.closed:
            self._owned = aiohttp.ClientSession()
        return self._owned

    async def get(self, path_and_query: str, timeout: float) -> object | None:
        """GET a path and parse the JSON response, reusing the connection.

        Returns None on any network/parse failure or non-200 rather than
        raising, matching `_smoip_get`.
        """
        async with self._lock:
            result = await self._perform(path_and_query, timeout)
        if result is None:
            return None
        status, body = result
        if status != 200:
            return None
        return _decode_json(body, self._host, path_and_query)

    async def get_status(self, path_and_query: str, timeout: float) -> int | None:
        """GET a path and return the HTTP status rather than the body.

        Writes need this: a successful `activate` returns a body of
        literal `null`, which parses to None exactly like a failure, so
        only the status distinguishes them.
        """
        async with self._lock:
            result = await self._perform(path_and_query, timeout)
        return result[0] if result is not None else None

    async def one_shot_status(self, path_and_query: str, timeout: float) -> int | None:
        """A write's request: this client's session, a fresh connection,
        and NO lock.

        Deliberately does not take `self._lock`. That lock serialises the
        poll loop's requests only (spec §8); a transport write that waited
        on it would sit behind the in-flight ~25 s long poll before
        leaving the process. `Connection: close` keeps 1.x's
        connection-per-write semantics so the device releases the slot
        immediately (#29/#31).

        Returns the bare status because a successful `activate` answers
        with a body of literal `null`, indistinguishable from failure
        once parsed.
        """
        session = self._session()
        url = URL(f"http://{self._host}:{self._port}{path_and_query}", encoded=True)
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout + 1),
                headers={"Connection": "close"},
            ) as resp:
                await resp.read()
                return resp.status
        except (TimeoutError, OSError, aiohttp.ClientError):
            _LOGGER.debug(
                "%s: StreamMagic write to %s failed", self._host, path_and_query
            )
            return None

    async def _perform(
        self, path_and_query: str, timeout: float
    ) -> tuple[int, str] | None:
        """One request, with one clean retry on a stale kept-alive socket.

        A connection idle since the last request may have been dropped
        by the device without us noticing, which aiohttp surfaces as
        `ServerDisconnectedError` when we try to reuse it. That gets one
        clean retry; a second disconnect stands as a failure.

        The URL is built with encoded=True so the exact percent-encoding
        the call sites produce with `quote()` reaches the wire
        unchanged - yarl would otherwise re-normalize it (measured: it
        decodes %3A back to ':'), silently changing the request shapes
        verified against a real device.
        """
        url = URL(f"http://{self._host}:{self._port}{path_and_query}", encoded=True)
        client_timeout = aiohttp.ClientTimeout(total=timeout + 1)
        for attempt in (1, 2):
            try:
                session = self._session()
                async with session.get(url, timeout=client_timeout) as resp:
                    body = await resp.read()
                    return resp.status, body.decode(errors="replace")
            except aiohttp.ServerDisconnectedError:
                if attempt == 1:
                    _LOGGER.debug(
                        "%s: kept-alive connection was stale, retrying",
                        self._host,
                    )
                    continue
                _LOGGER.debug(
                    "%s: StreamMagic request to %s failed",
                    self._host,
                    path_and_query,
                )
                return None
            except (TimeoutError, OSError, aiohttp.ClientError):
                _LOGGER.debug(
                    "%s: StreamMagic request to %s failed",
                    self._host,
                    path_and_query,
                )
                return None
        return None

    async def close(self) -> None:
        """Close the owned session, if any. Never touches an injected one.

        Safe to call repeatedly; a later request lazily recreates the
        owned session (reconnect needs no special handling).
        """
        if self._owned is not None:
            await self._owned.close()
            self._owned = None


async def _one_shot(
    host: str, port: int, path_and_query: str, timeout: float
) -> tuple[int, str] | None:
    """One request on its own connection, closed before returning.

    `Connection: close` is sent explicitly so the device drops its end
    immediately rather than holding one of its few slots for an idle
    socket - the same behaviour the http.client implementation had.
    encoded=True for the same wire-verbatim reason as
    `StreamingClient._perform`.
    """
    url = URL(f"http://{host}:{port}{path_and_query}", encoded=True)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout + 1),
                headers={"Connection": "close"},
            ) as resp:
                body = await resp.read()
                return resp.status, body.decode(errors="replace")
    except (TimeoutError, OSError, aiohttp.ClientError):
        _LOGGER.debug("%s: StreamMagic request to %s failed", host, path_and_query)
        return None


async def _smoip_get(
    host: str, port: int, path_and_query: str, timeout: float
) -> object | None:
    """GET a StreamMagic API path and parse the JSON response.

    One-shot: opens a connection, uses it once, closes it. For repeated
    requests against the same device - notably the poll loop - use
    `StreamingClient`, which keeps the connection open.

    Returns None on any error rather than raising, since this is a
    best-effort, reverse-engineered API with no stability guarantee.
    """
    result = await _one_shot(host, port, path_and_query, timeout)
    if result is None:
        return None
    status, body = result
    if status != 200:
        return None
    return _decode_json(body, host, path_and_query)


async def _smoip_status(
    host: str, port: int, path_and_query: str, timeout: float
) -> int | None:
    """One-shot request returning the HTTP status rather than the body.

    Mirrors `_smoip_get`. Writes need the bare status because a
    successful `activate` returns a body of literal `null`,
    indistinguishable from a failure once parsed.
    """
    result = await _one_shot(host, port, path_and_query, timeout)
    return result[0] if result is not None else None


async def _get_status(
    session: StreamingClient | None,
    host: str,
    port: int,
    path_and_query: str,
    timeout: float,
    *,
    pooled: bool = True,
) -> int | None:
    """Route a status request.

    `pooled=False` is the write path: a client is available and its
    session should be used, but the pooled-and-locked `get_status` must
    not be (spec §8). Without a client at all — a standalone caller with
    no receiver — fall back to the free-function one-shot.
    """
    if session is None:
        return await _smoip_status(host, port, path_and_query, timeout)
    if pooled:
        return await session.get_status(path_and_query, timeout)
    return await session.one_shot_status(path_and_query, timeout)


async def _get(
    session: StreamingClient | None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
) -> list[object] | None:
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
    session: StreamingClient | None,
    path: str,
    role: str,
    value: dict[str, object],
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
        pooled=False,
    )
    if status != 200:
        _LOGGER.debug("%s: %s rejected (status %s)", host, log_context, status)
    return status == 200


async def _activate(
    host: str,
    payload: dict[str, object],
    port: int,
    timeout: float,
    session: StreamingClient | None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
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
    session: StreamingClient | None = None,
) -> bool:
    """Set the combined shuffle/repeat mode, e.g. "shuffle", "repeatAll".

    One enum rather than two flags, so setting it replaces both axes at
    once.
    """
    value: dict[str, object] = {"type": "playerPlayMode", "playerPlayMode": mode}
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
