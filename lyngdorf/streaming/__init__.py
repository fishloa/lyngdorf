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

from .client import (
    StreamingClient,
    _smoip_get,
    _smoip_status,
    async_activate_control,
    async_fetch_now_playing,
    async_fetch_play_mode,
    async_fetch_play_modes,
    async_fetch_position,
    async_init_now_playing_queue,
    async_poll_now_playing_events,
    async_seek,
    async_set_play_mode,
    async_subscribe_now_playing,
)
from .parsers import (
    _coerce_ms,
    _coerce_play_mode,
    _decode_json,
    _unwrap_value,
    parse_now_playing,
    parse_play_mode_events,
    parse_play_modes,
    parse_position_events,
)
from .types import NowPlaying

__all__ = [
    "NowPlaying",
    "StreamingClient",
    "_coerce_ms",
    "_coerce_play_mode",
    "_decode_json",
    "_smoip_get",
    "_smoip_status",
    "_unwrap_value",
    "async_activate_control",
    "async_fetch_now_playing",
    "async_fetch_play_mode",
    "async_fetch_play_modes",
    "async_fetch_position",
    "async_init_now_playing_queue",
    "async_poll_now_playing_events",
    "async_seek",
    "async_set_play_mode",
    "async_subscribe_now_playing",
    "parse_now_playing",
    "parse_play_mode_events",
    "parse_play_modes",
    "parse_position_events",
]
