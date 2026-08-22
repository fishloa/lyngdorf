"""The `NowPlaying` value type for streaming-capable models."""

from __future__ import annotations

from dataclasses import dataclass

from ..states import Control, PlaybackState, PlayMode


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
