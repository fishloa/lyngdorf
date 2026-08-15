"""Now-playing metadata via the streaming module's HTTP API.

Streaming-capable Lyngdorf models (see ``ModelConfig.has_streaming``) embed a
StreamUnlimited streaming module that exposes now-playing metadata (track
title/artist/album/art, play state) over a separate HTTP JSON API on port
8080 - unrelated to the ``:84`` RIO protocol the rest of this library speaks.

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

The exact shape of a change event's payload in that last response isn't
confirmed (only the empty/no-change case, ``[]``, has been observed live) -
so rather than parse it, a change just triggers a fresh one-shot
``getData`` fetch for the authoritative current value. That keeps exactly
one parsing path (`parse_now_playing`, exercised by both the initial fetch
and every subsequent update) instead of two, at the cost of one extra HTTP
round trip per change - a deliberate simplicity trade given only the
``getData`` shape is confirmed.

:license: MIT, see LICENSE for more details.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import logging
from dataclasses import dataclass
from urllib.parse import quote

from .const import NOW_PLAYING_PATH, STREAMMAGIC_PORT

_LOGGER = logging.getLogger(__package__)


@dataclass(frozen=True)
class NowPlaying:
    """Now-playing metadata for a streaming-capable model.

    Attributes:
        state: Raw play state as reported by the device (e.g. "playing",
            "paused", "transitioning"), passed through unnormalized.
        title: Track title.
        artist: Track artist.
        album: Track album.
        source: Human-readable streaming source name (e.g. "Qobuz
            Connect") - not the RIO `source` input name.
        art_url: Album art URL, if any.
        duration_ms: Track duration in milliseconds, if known. No elapsed/
            position is available from this endpoint.
    """

    state: str | None
    title: str | None
    artist: str | None
    album: str | None
    source: str | None
    art_url: str | None
    duration_ms: int | None


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

    return NowPlaying(
        state=payload.get("state"),
        title=title,
        artist=meta_data.get("artist"),
        album=meta_data.get("album"),
        source=media_roles.get("title"),
        art_url=track_roles.get("icon"),
        duration_ms=int(duration) if isinstance(duration, (int, float)) else None,
    )


def _unwrap_value(raw: object) -> object:
    """Unwrap the single-element array a `roles=value` `getData` request
    returns the value inside."""
    if isinstance(raw, list) and raw:
        return raw[-1]
    return raw


async def _smoip_get(
    host: str, port: int, path_and_query: str, timeout: float
) -> object | None:
    """GET a StreamMagic API path and parse the JSON response.

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
    except (TimeoutError, OSError):
        _LOGGER.debug("%s: StreamMagic request to %s failed", host, path_and_query)
        return None

    if not text:
        return None
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        _LOGGER.debug("%s: StreamMagic response was not valid JSON", host)
        return None


async def async_fetch_now_playing(
    host: str, port: int = STREAMMAGIC_PORT, timeout: float = 8.0
) -> NowPlaying | None:
    """One-shot fetch of the current now-playing state.

    Used both for the initial value before the first long-poll cycle and
    for every subsequent update (see module docstring). Returns None on
    any network/parse failure or idle input - never raises.
    """
    data = await _smoip_get(
        host,
        port,
        f"/api/getData?path={quote(NOW_PLAYING_PATH)}&roles=value",
        timeout,
    )
    if data is None:
        return None
    return parse_now_playing(_unwrap_value(data))


async def async_init_now_playing_queue(
    host: str, port: int = STREAMMAGIC_PORT, timeout: float = 8.0
) -> str | None:
    """Create a new event queue, subscribed to nothing yet.

    Returns the queue ID, or None on failure.
    """
    data = await _smoip_get(
        host,
        port,
        "/api/event/modifyQueue?queueId=&subscribe[]=&unsubscribe[]",
        timeout,
    )
    if not isinstance(data, str):
        return None
    return data.strip("{}") or None


async def async_subscribe_now_playing(
    host: str, queue_id: str, port: int = STREAMMAGIC_PORT, timeout: float = 8.0
) -> bool:
    """Subscribe an existing queue to now-playing changes."""
    subscribe = quote(json.dumps([{"path": NOW_PLAYING_PATH, "type": "itemWithValue"}]))
    data = await _smoip_get(
        host,
        port,
        f"/api/event/modifyQueue?queueId={queue_id}&subscribe={subscribe}&unsubscribe=[]",
        timeout,
    )
    return data is not None


async def async_poll_now_playing_events(
    host: str, queue_id: str, port: int = STREAMMAGIC_PORT, timeout: float = 25.0
) -> list | None:
    """Long-poll the queue for changes on its subscribed path(s).

    Blocks server-side for up to `timeout` seconds. Returns the (possibly
    empty) list of change events if the call completed, or None if it
    failed outright (network error, or the queue itself has expired/is no
    longer known to the device) - the caller should treat None as a signal
    to discard `queue_id` and re-initialize.
    """
    data = await _smoip_get(
        host,
        port,
        f"/api/event/pollQueue?queueId={queue_id}&timeout={int(timeout)}",
        timeout + 5.0,
    )
    return data if isinstance(data, list) else None
