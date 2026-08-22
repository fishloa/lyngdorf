"""Parsers for the streaming module's JSON payloads.

Pure functions: payload in, value out. Every function returns a
None/empty fallback rather than raising - this API is reverse-engineered
with no format guarantee (see the package docstring in __init__.py).
"""

from __future__ import annotations

import json
import logging

from ..const import NOW_PLAYING_POSITION_PATH, PLAY_MODE_PATH
from ..states import Control, PlaybackState, PlayMode
from .types import NowPlaying

_LOGGER = logging.getLogger(__package__)


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


def _decode_json(text: str | None, host: str, path_and_query: str) -> object | None:
    if not text:
        return None
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        _LOGGER.debug("%s: StreamMagic response was not valid JSON", host)
        return None
