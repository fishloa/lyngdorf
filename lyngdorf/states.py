"""Typed device states for the streaming module's playback API.

Three kinds of value cross the streaming (`:8080`) API's public surface as
bare strings if left unmodelled: the play mode, the playback state, and the
transport control names. Each is a closed-ish set the caller would otherwise
have to know by heart, spelled exactly as the device spells it - down to the
trailing underscore on `next_`, which nothing catches if mistyped.

This module is importable on its own, without dragging in the HTTP layer in
`lyngdorf/streaming.py`, so consumers (and the Home Assistant integration in
particular) can reference these types without needing a live connection.

Two different compatibility rules apply here, and they pull in opposite
directions:

Backwards compatibility with existing callers of this library is explicitly
NOT a requirement - the project owner has waived it for this change. There
are no shims, aliases, or deprecation paths; callers update to the new types.

Forwards compatibility with the device IS a requirement. The device accepts
and stores arbitrary strings - an unrecognised play mode still returns
HTTP 200 - the capability set it advertises varies by source, and it has been
observed to self-update its firmware mid-development. A type that raises on
an unrecognised value would take out a consumer the moment the device sends
something new. `Control` and `PlaybackState` below cope with this the same
way: a lenient `_missing_` that turns any unrecognised string into a usable
member instead of raising. `PlayMode.from_wire` copes with it differently -
by returning `None` for anything it does not recognise, rather than guessing
- because silently treating an unknown mode as `normal` would be worse than
visibly reporting "unknown".

:license: MIT, see LICENSE for more details.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Repeat(StrEnum):
    """Repeat setting, one axis of the device's combined play-mode enum.

    These values are ours, not the device's - the device has no separate
    repeat field, only the combined `PlayMode.wire` string. Chosen to match
    Home Assistant's own `RepeatMode` values (`off`/`one`/`all`) so the
    integration maps across with no translation layer.
    """

    OFF = "off"
    ONE = "one"
    ALL = "all"


# The device's six play-mode wire values are a 2x3 grid of (shuffle, repeat),
# not six independent states - see `PlayMode` below for why that matters.
_TO_WIRE: dict[tuple[bool, Repeat], str] = {
    (False, Repeat.OFF): "normal",
    (False, Repeat.ONE): "repeatOne",
    (False, Repeat.ALL): "repeatAll",
    (True, Repeat.OFF): "shuffle",
    (True, Repeat.ONE): "shuffleRepeatOne",
    (True, Repeat.ALL): "shuffleRepeatAll",
}
_FROM_WIRE: dict[str, tuple[bool, Repeat]] = {
    wire: pair for pair, wire in _TO_WIRE.items()
}


@dataclass(frozen=True)
class PlayMode:
    """The device's combined shuffle/repeat mode.

    A value object rather than an enum, deliberately: the six wire values
    (`normal`, `shuffle`, `repeatOne`, `shuffleRepeatOne`, `repeatAll`,
    `shuffleRepeatAll`) are not six independent states but a 2x3 grid of two
    orthogonal axes - shuffle on/off, repeat off/one/all. A flat enum would
    just re-encode the device's wire spelling instead of modelling the
    domain, and would force every caller that wants to change just one axis
    to first work out which of the six strings the *other* axis is
    currently sitting at. Home Assistant itself models it this way -
    `shuffle` is a bool, `repeat` is `RepeatMode.OFF/ONE/ALL`, and they are
    separate entity features - so a value object with both fields carried
    explicitly is what makes changing one axis safe: `dataclasses.replace`
    carries the other over rather than leaving it to the device to infer.

    Frozen (and so hashable) rather than a plain class, so it can live in a
    `frozenset` alongside the other modes a source advertises.
    """

    shuffle: bool = False
    repeat: Repeat = Repeat.OFF

    @classmethod
    def from_wire(cls, value: str) -> PlayMode | None:
        """Parse a device play-mode string, or None if unrecognised.

        Returns None rather than guessing - including for the `bogusMode`
        the device will happily accept and store - so an unknown value is
        visibly unknown rather than silently mistaken for `normal`.
        """
        pair = _FROM_WIRE.get(value)
        if pair is None:
            return None
        shuffle, repeat = pair
        return cls(shuffle=shuffle, repeat=repeat)

    @property
    def wire(self) -> str:
        """The device's spelling of this shuffle/repeat combination."""
        return _TO_WIRE[(self.shuffle, self.repeat)]


class Control(StrEnum):
    """A transport action name, as spelled on the wire.

    `NEXT_TRACK`'s value carries a trailing underscore - `next_` - because
    the device really does spell it that way; nothing about the name gives
    a caller any way to guess that, which is exactly the kind of mistake
    typing this enum is meant to prevent.

    Lenient: see `_missing_` and the module docstring. The known members
    are what has been observed on real hardware, not an exhaustive vendor
    list - the device's own capability payload is the source of truth for
    what a given source actually offers.
    """

    PAUSE = "pause"
    NEXT_TRACK = "next_"
    PREVIOUS_TRACK = "previous"
    SEEK = "seekTime"
    SKIP_BACKWARD_15_SECONDS = "backward15sec"
    SKIP_FORWARD_15_SECONDS = "forward15sec"
    LIKE = "like"
    DISLIKE = "dislike"

    @classmethod
    def _missing_(cls, value: object) -> Control | None:
        if not isinstance(value, str):
            return None
        member: Control = str.__new__(cls, value)
        member._name_ = value
        member._value_ = value
        return member


class PlaybackState(StrEnum):
    """The device's reported playback state.

    Lenient: see `_missing_` and the module docstring - a firmware update
    that adds a state (or the device reporting one not previously observed
    live, e.g. a `buffering`-style transitional state) must not raise.
    """

    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    TRANSITIONING = "transitioning"

    @classmethod
    def _missing_(cls, value: object) -> PlaybackState | None:
        if not isinstance(value, str):
            return None
        member: PlaybackState = str.__new__(cls, value)
        member._name_ = value
        member._value_ = value
        return member
