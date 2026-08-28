"""The D9 deprecation shim layer: every 1.x name that was RENAMED or
RELOCATED, as a DeprecationWarning-emitting delegate on LyngdorfReceiver.

Time-boxed scaffolding with a demolition date: this file (and the fenced
has_*_feature block in models/__init__.py, plus the module __getattr__
aliases in lyngdorf/__init__.py) is deleted WHOLESALE in 2.1 - a recorded
work item (design §12), not an intention.

1.11 NOTE. 2.0.0 deliberately omitted two things, and said here that a
future reader must not "complete" the layer. 1.11.0 completes both, on
purpose, and 2.0.0 remains published without them:

- The 18 property setters, restored below. 2.0's reasoning was that
  removal is self-enforcing - assignment to a read-only property is a
  static [misc] error that locates every consumer site - and that is
  exactly right for 2.0. It is the wrong trade for a consumer whose CI
  type-checks the whole tree, because "locates every site" and "fails
  the build until every site is fixed in one commit" are the same
  sentence. Restored here so the pin can move in one PR and each call
  site can be migrated in another.
- The two reused names, `volume` and `lipsync`. Solved by making them
  genuinely both types at once - see FloatNumericControl in controls.py.

The issue #51 hazard the setters carry is real and is NOT waved away:
`asyncio.Event.set()` is not thread-safe, `receiver.volume = -25` looks
like a plain attribute write, and Home Assistant hit exactly that by
running sync entity actions in an executor. So the restored setters are
strictly safer than 1.x's: `_require_loop_thread` turns that silent
cross-thread race into an immediate, explanatory RuntimeError. It fires
only when a drain task is actually running and the caller is not on a
loop - so the loopless construction that tests and the client's own
documented fallback rely on is untouched.

Sync-in-1.x members are shimmed SYNC-BODIED, returning the coroutine
(never `async def`): measured, an unawaited legacy call then still emits
its DeprecationWarning where an async-def shim would be a silent no-op.
Not a property-setter reintroduction: calling an async function executes
nothing until awaited.

Read shims are READ-ONLY properties - measured against MagicMock(spec=)
fixtures, settability buys nothing (the mock replaces the descriptor
wholesale) and would itself be a property setter.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Callable, Coroutine, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .controls import Trim
from .exceptions import LyngdorfInvalidValueError, LyngdorfUnsupportedError
from .models import NumericRange
from .remote import RemoteKey
from .states import PlayMode, Repeat
from .streaming import NowPlaying

if TYPE_CHECKING:
    from .components import ZoneB


def _deprecated(old: str, new: str) -> None:
    warnings.warn(
        f"{old} is deprecated and will be removed in lyngdorf 2.1; use {new}",
        DeprecationWarning,
        stacklevel=3,
    )


async def _noop() -> None:
    """Awaitable no-op - the warn-and-ignore stepper shims return this."""


def _legacy_setter(old: str, new: str) -> None:
    """Warn for a restored 1.x property setter (1.11 only)."""
    warnings.warn(
        f"setting {old} is deprecated and is removed in lyngdorf 2.0; use {new}",
        DeprecationWarning,
        stacklevel=3,
    )


def _require_loop_thread(receiver: Any, name: str) -> None:
    """Refuse a legacy setter called off the event loop thread.

    The enqueue path ends in `asyncio.Event.set()`, which is not
    thread-safe. A sync-looking `receiver.x = v` invites exactly the call
    Home Assistant made - a sync entity action dispatched to an executor
    - and 1.x raced silently there. This raises instead.

    Deliberately narrow. It fires only when a drain task is live (so a
    loop exists on some thread) AND this thread has none - the precise
    shape of the cross-thread bug. With no drain task at all there is no
    Event to set: `_writeCommand` flushes synchronously by its own
    documented fallback, which is how the tests and any loopless caller
    already work, and that path stays allowed.
    """
    api = getattr(receiver, "_api", None)
    task = getattr(api, "_write_queue_task", None)
    if task is None or task.done():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError(
            f"setting {name} from a thread with no running event loop is "
            "unsafe: the write is enqueued via asyncio.Event.set(), which is "
            "not thread-safe. Await the 2.0 coroutine from the loop instead "
            "(see lyngdorf issue #51)."
        ) from None


class _CompatShims:
    """Mixin carrying every receiver-level shim. LyngdorfReceiver
    inherits it; 2.1 deletes the file and drops the base."""

    # ---- shape 1: read shims (read-only properties) -----------------------

    @property
    def mute_enabled(self) -> bool | None:
        _deprecated("mute_enabled", "muted")
        return self.muted

    @mute_enabled.setter
    def mute_enabled(self, enabled: bool) -> None:
        _legacy_setter("mute_enabled", "await set_muted(...)")
        _require_loop_thread(self, "mute_enabled")
        self._api.mute_enabled(enabled)

    @property
    def volume_range(self) -> NumericRange:
        _deprecated("volume_range", "volume.range")
        return self._volume.range

    @property
    def available_sources(self) -> list[str]:
        _deprecated("available_sources", "sources")
        return self.sources

    @property
    def available_sound_modes(self) -> list[str]:
        _deprecated("available_sound_modes", "sound_modes")
        return self.sound_modes

    @property
    def available_room_perfect_positions(self) -> list[str]:
        _deprecated("available_room_perfect_positions", "room_perfect_positions")
        return self.room_perfect_positions

    @property
    def available_voicings(self) -> list[str]:
        _deprecated("available_voicings", "voicings")
        return self.voicings

    @property
    def available_audio_inputs(self) -> list[str]:
        _deprecated("available_audio_inputs", "audio_inputs")
        return self.audio_inputs

    @property
    def available_video_inputs(self) -> list[str]:
        _deprecated("available_video_inputs", "video_inputs")
        return self.video_inputs

    @property
    def available_stream_types(self) -> list[str]:
        _deprecated("available_stream_types", "stream_types")
        return self.stream_types

    @property
    def trim_bass(self) -> float | None:
        _deprecated("trim_bass", "trims[Trim.BASS].value")
        ctl = self.trims.get(Trim.BASS)
        return ctl.value if ctl is not None else None

    @trim_bass.setter
    def trim_bass(self, value: float) -> None:
        _legacy_setter("trim_bass", "await trims[Trim.BASS].set(...)")
        _require_loop_thread(self, "trim_bass")
        ctl = self.trims.get(Trim.BASS)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_bass is not supported by model "
                f"{self.model.config.model_name}"
            )
        ctl._send_set(value)

    @property
    def trim_treble(self) -> float | None:
        _deprecated("trim_treble", "trims[Trim.TREBLE].value")
        ctl = self.trims.get(Trim.TREBLE)
        return ctl.value if ctl is not None else None

    @trim_treble.setter
    def trim_treble(self, value: float) -> None:
        _legacy_setter("trim_treble", "await trims[Trim.TREBLE].set(...)")
        _require_loop_thread(self, "trim_treble")
        ctl = self.trims.get(Trim.TREBLE)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_treble is not supported by model "
                f"{self.model.config.model_name}"
            )
        ctl._send_set(value)

    @property
    def trim_centre(self) -> float | None:
        _deprecated("trim_centre", "trims[Trim.CENTER].value")
        ctl = self.trims.get(Trim.CENTER)
        return ctl.value if ctl is not None else None

    @trim_centre.setter
    def trim_centre(self, value: float) -> None:
        _legacy_setter("trim_centre", "await trims[Trim.CENTER].set(...)")
        _require_loop_thread(self, "trim_centre")
        ctl = self.trims.get(Trim.CENTER)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_centre is not supported by model "
                f"{self.model.config.model_name}"
            )
        ctl._send_set(value)

    @property
    def trim_height(self) -> float | None:
        _deprecated("trim_height", "trims[Trim.HEIGHT].value")
        ctl = self.trims.get(Trim.HEIGHT)
        return ctl.value if ctl is not None else None

    @trim_height.setter
    def trim_height(self, value: float) -> None:
        _legacy_setter("trim_height", "await trims[Trim.HEIGHT].set(...)")
        _require_loop_thread(self, "trim_height")
        ctl = self.trims.get(Trim.HEIGHT)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_height is not supported by model "
                f"{self.model.config.model_name}"
            )
        ctl._send_set(value)

    @property
    def trim_lfe(self) -> float | None:
        _deprecated("trim_lfe", "trims[Trim.LFE].value")
        ctl = self.trims.get(Trim.LFE)
        return ctl.value if ctl is not None else None

    @trim_lfe.setter
    def trim_lfe(self, value: float) -> None:
        _legacy_setter("trim_lfe", "await trims[Trim.LFE].set(...)")
        _require_loop_thread(self, "trim_lfe")
        ctl = self.trims.get(Trim.LFE)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_lfe is not supported by model " f"{self.model.config.model_name}"
            )
        ctl._send_set(value)

    @property
    def trim_surround(self) -> float | None:
        _deprecated("trim_surround", "trims[Trim.SURROUND].value")
        ctl = self.trims.get(Trim.SURROUND)
        return ctl.value if ctl is not None else None

    @trim_surround.setter
    def trim_surround(self, value: float) -> None:
        _legacy_setter("trim_surround", "await trims[Trim.SURROUND].set(...)")
        _require_loop_thread(self, "trim_surround")
        ctl = self.trims.get(Trim.SURROUND)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_surround is not supported by model "
                f"{self.model.config.model_name}"
            )
        ctl._send_set(value)

    @property
    def trim_bass_range(self) -> NumericRange | None:
        _deprecated("trim_bass_range", "Trim.BASS in trims / trims[Trim.BASS].range")
        ctl = self.trims.get(Trim.BASS)
        return ctl.range if ctl is not None else None

    @property
    def trim_treble_range(self) -> NumericRange | None:
        _deprecated(
            "trim_treble_range", "Trim.TREBLE in trims / trims[Trim.TREBLE].range"
        )
        ctl = self.trims.get(Trim.TREBLE)
        return ctl.range if ctl is not None else None

    @property
    def trim_centre_range(self) -> NumericRange | None:
        _deprecated(
            "trim_centre_range", "Trim.CENTER in trims / trims[Trim.CENTER].range"
        )
        ctl = self.trims.get(Trim.CENTER)
        return ctl.range if ctl is not None else None

    @property
    def trim_height_range(self) -> NumericRange | None:
        _deprecated(
            "trim_height_range", "Trim.HEIGHT in trims / trims[Trim.HEIGHT].range"
        )
        ctl = self.trims.get(Trim.HEIGHT)
        return ctl.range if ctl is not None else None

    @property
    def trim_lfe_range(self) -> NumericRange | None:
        _deprecated("trim_lfe_range", "Trim.LFE in trims / trims[Trim.LFE].range")
        ctl = self.trims.get(Trim.LFE)
        return ctl.range if ctl is not None else None

    @property
    def trim_surround_range(self) -> NumericRange | None:
        _deprecated(
            "trim_surround_range", "Trim.SURROUND in trims / trims[Trim.SURROUND].range"
        )
        ctl = self.trims.get(Trim.SURROUND)
        return ctl.range if ctl is not None else None

    @property
    def lipsync_range(self) -> NumericRange | None:
        _deprecated("lipsync_range", "lipsync.range")
        return self._lipsync.range if self._lipsync is not None else None

    @property
    def zone_b_power_on(self) -> bool | None:
        _deprecated("zone_b_power_on", "zone_b.power_on")
        return self.zone_b.power_on if self.zone_b is not None else None

    @zone_b_power_on.setter
    def zone_b_power_on(self, enabled: bool) -> None:
        _legacy_setter("zone_b_power_on", "await zone_b.set_power(...)")
        _require_loop_thread(self, "zone_b_power_on")
        self._require_zone_b("zone_b_power_on")
        self._api.zone_b_power_on(enabled)

    @property
    def zone_b_mute_enabled(self) -> bool | None:
        _deprecated("zone_b_mute_enabled", "zone_b.muted")
        return self.zone_b.muted if self.zone_b is not None else None

    @zone_b_mute_enabled.setter
    def zone_b_mute_enabled(self, enabled: bool) -> None:
        _legacy_setter("zone_b_mute_enabled", "await zone_b.set_muted(...)")
        _require_loop_thread(self, "zone_b_mute_enabled")
        self._require_zone_b("zone_b_mute_enabled")
        self._api.zone_b_mute_enabled(enabled)

    @property
    def zone_b_source(self) -> str | None:
        _deprecated("zone_b_source", "zone_b.source")
        return self.zone_b.source if self.zone_b is not None else None

    @zone_b_source.setter
    def zone_b_source(self, name: str) -> None:
        _legacy_setter("zone_b_source", "await zone_b.set_source(...)")
        _require_loop_thread(self, "zone_b_source")
        zone_b = self._require_zone_b("zone_b_source")
        index = self._zone_b_sources.lookupIndex(name)
        if index < 0:
            raise LyngdorfInvalidValueError(
                f"{name} is not a valid Zone B source name, and cannot be chosen"
            )
        del zone_b
        self._api.change_zone_b_source(index)

    @property
    def zone_b_audio_input(self) -> str | None:
        _deprecated("zone_b_audio_input", "zone_b.audio_input")
        return self.zone_b.audio_input if self.zone_b is not None else None

    @property
    def zone_b_streaming_source(self) -> str | None:
        _deprecated("zone_b_streaming_source", "zone_b.streaming_source")
        return self.zone_b.streaming_source if self.zone_b is not None else None

    @property
    def zone_b_volume(self) -> float | None:
        _deprecated("zone_b_volume", "zone_b.volume.value")
        return self.zone_b.volume.value if self.zone_b is not None else None

    @zone_b_volume.setter
    def zone_b_volume(self, value: float) -> None:
        _legacy_setter("zone_b_volume", "await zone_b.volume.set(...)")
        _require_loop_thread(self, "zone_b_volume")
        zone_b = self._require_zone_b("zone_b_volume")
        zone_b.volume._send_set(value)

    @property
    def zone_b_volume_range(self) -> NumericRange | None:
        _deprecated("zone_b_volume_range", "zone_b.volume.range")
        return self.zone_b.volume.range if self.zone_b is not None else None

    @property
    def zone_b_available_sources(self) -> list[str]:
        _deprecated("zone_b_available_sources", "zone_b.sources")
        return self.zone_b.sources if self.zone_b is not None else []

    @property
    def has_position(self) -> bool:
        _deprecated("has_position", "player is not None")
        return self.player is not None

    @property
    def has_remote_keys(self) -> bool:
        _deprecated("has_remote_keys", "remote is not None")
        return self.remote is not None

    @property
    def available_remote_keys(self) -> frozenset[RemoteKey]:
        _deprecated("available_remote_keys", "remote.keys")
        return self.remote.keys if self.remote is not None else frozenset()

    @property
    def now_playing(self) -> NowPlaying | None:
        _deprecated("now_playing", "player.now_playing")
        return self.player.now_playing if self.player is not None else None

    @property
    def position_ms(self) -> int | None:
        _deprecated("position_ms", "player.position_ms")
        return self.player.position_ms if self.player is not None else None

    @property
    def position_updated_at(self) -> datetime | None:
        _deprecated("position_updated_at", "player.position_updated_at")
        return self.player.position_updated_at if self.player is not None else None

    @property
    def position_percent(self) -> float | None:
        _deprecated("position_percent", "player.position_percent")
        return self.player.position_percent if self.player is not None else None

    @property
    def can_pause(self) -> bool:
        _deprecated("can_pause", "player.can_pause")
        return self.player.can_pause if self.player is not None else False

    @property
    def can_next(self) -> bool:
        _deprecated("can_next", "player.can_next")
        return self.player.can_next if self.player is not None else False

    @property
    def can_previous(self) -> bool:
        _deprecated("can_previous", "player.can_previous")
        return self.player.can_previous if self.player is not None else False

    @property
    def can_seek(self) -> bool:
        _deprecated("can_seek", "player.can_seek")
        return self.player.can_seek if self.player is not None else False

    @property
    def can_shuffle(self) -> bool:
        _deprecated("can_shuffle", "player.can_shuffle")
        return self.player.can_shuffle if self.player is not None else False

    @property
    def play_mode(self) -> PlayMode | None:
        _deprecated("play_mode", "player.play_mode")
        return self.player.play_mode if self.player is not None else None

    @property
    def shuffle(self) -> bool | None:
        _deprecated("shuffle", "player.shuffle")
        return self.player.shuffle if self.player is not None else None

    @property
    def repeat(self) -> Repeat | None:
        _deprecated("repeat", "player.repeat")
        return self.player.repeat if self.player is not None else None

    @property
    def available_play_modes(self) -> frozenset[PlayMode]:
        _deprecated("available_play_modes", "player.play_modes")
        return self.player.play_modes if self.player is not None else frozenset()

    @property
    def available_repeat_modes(self) -> frozenset[Repeat]:
        _deprecated("available_repeat_modes", "player.repeat_modes")
        return self.player.repeat_modes if self.player is not None else frozenset()

    # ---- shape 2: sync-bodied write shims ---------------------------------

    def set_volume(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_volume", "volume.set")
        return self._volume.set(value)

    def set_zone_b_volume(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_zone_b_volume", "zone_b.volume.set")
        if self.zone_b is None:
            raise LyngdorfInvalidValueError(
                f"zone_b_volume is not supported by model "
                f"{self.model.config.model_name}"
            )
        return self.zone_b.volume.set(value)

    def set_lipsync(self, ms: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_lipsync", "lipsync.set")
        if self._lipsync is None:
            raise LyngdorfInvalidValueError(
                f"lipsync is not supported by model " f"{self.model.config.model_name}"
            )
        return self._lipsync.set(ms)

    def set_trim_bass(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_trim_bass", "trims[Trim.BASS].set")
        ctl = self.trims.get(Trim.BASS)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_bass is not supported by model "
                f"{self.model.config.model_name}"
            )
        return ctl.set(value)

    def set_trim_treble(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_trim_treble", "trims[Trim.TREBLE].set")
        ctl = self.trims.get(Trim.TREBLE)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_treble is not supported by model "
                f"{self.model.config.model_name}"
            )
        return ctl.set(value)

    def set_trim_centre(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_trim_centre", "trims[Trim.CENTER].set")
        ctl = self.trims.get(Trim.CENTER)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_centre is not supported by model "
                f"{self.model.config.model_name}"
            )
        return ctl.set(value)

    def set_trim_height(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_trim_height", "trims[Trim.HEIGHT].set")
        ctl = self.trims.get(Trim.HEIGHT)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_height is not supported by model "
                f"{self.model.config.model_name}"
            )
        return ctl.set(value)

    def set_trim_lfe(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_trim_lfe", "trims[Trim.LFE].set")
        ctl = self.trims.get(Trim.LFE)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_lfe is not supported by model " f"{self.model.config.model_name}"
            )
        return ctl.set(value)

    def set_trim_surround(self, value: float) -> Coroutine[Any, Any, None]:
        _deprecated("set_trim_surround", "trims[Trim.SURROUND].set")
        ctl = self.trims.get(Trim.SURROUND)
        if ctl is None:
            raise LyngdorfInvalidValueError(
                f"trim_surround is not supported by model "
                f"{self.model.config.model_name}"
            )
        return ctl.set(value)

    def send_remote_commands(
        self,
        commands: Iterable[str | RemoteKey],
        num_repeats: int = 1,
    ) -> Coroutine[Any, Any, None]:
        _deprecated("send_remote_commands", "remote.send")
        if self.remote is None:
            raise LyngdorfUnsupportedError(
                f"Model {self.model.config.model_name} has no remote keys"
            )
        return self.remote.send(commands, num_repeats=num_repeats)

    def press(self, key: RemoteKey) -> Coroutine[Any, Any, None]:
        _deprecated("press", "remote.press")
        if self.remote is None:
            raise LyngdorfUnsupportedError(
                f"Model {self.model.config.model_name} has no remote keys"
            )
        return self.remote.press(key)

    # ---- shape 3: stepper shims -------------------------------------------

    def volume_up(self) -> Coroutine[Any, Any, None]:
        _deprecated("volume_up", "volume.up")
        return self._volume.up()

    def volume_down(self) -> Coroutine[Any, Any, None]:
        _deprecated("volume_down", "volume.down")
        return self._volume.down()

    def zone_b_volume_up(self) -> Coroutine[Any, Any, None]:
        _deprecated("zone_b_volume_up", "zone_b.volume.up")
        if self.zone_b is None:
            warnings.warn(
                "this model has no Zone B; ignoring zone_b_volume_up",
                stacklevel=2,
            )
            return _noop()
        return self.zone_b.volume.up()

    def zone_b_volume_down(self) -> Coroutine[Any, Any, None]:
        _deprecated("zone_b_volume_down", "zone_b.volume.down")
        if self.zone_b is None:
            warnings.warn(
                "this model has no Zone B; ignoring zone_b_volume_down",
                stacklevel=2,
            )
            return _noop()
        return self.zone_b.volume.down()

    def _stepper_trim(
        self,
        trim: Trim,
        name: str,
        method: str,
    ) -> Coroutine[Any, Any, None]:
        _deprecated(
            name, f"isinstance(trims[{trim}], SteppableControl) and .{method}()"
        )
        ctl = self.trims.get(trim)
        from .controls import SteppableControl

        if isinstance(ctl, SteppableControl):
            return getattr(ctl, method)()
        warnings.warn(
            f"this model cannot step {name.split('_')[0]} trim; ignoring",
            stacklevel=2,
        )
        return _noop()

    def trim_bass_up(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.BASS, "trim_bass_up", "up")

    def trim_bass_down(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.BASS, "trim_bass_down", "down")

    def trim_treble_up(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.TREBLE, "trim_treble_up", "up")

    def trim_treble_down(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.TREBLE, "trim_treble_down", "down")

    def trim_centre_up(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.CENTER, "trim_centre_up", "up")

    def trim_centre_down(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.CENTER, "trim_centre_down", "down")

    def trim_height_up(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.HEIGHT, "trim_height_up", "up")

    def trim_height_down(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.HEIGHT, "trim_height_down", "down")

    def trim_lfe_up(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.LFE, "trim_lfe_up", "up")

    def trim_lfe_down(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.LFE, "trim_lfe_down", "down")

    def trim_surround_up(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.SURROUND, "trim_surround_up", "up")

    def trim_surround_down(self) -> Coroutine[Any, Any, None]:
        return self._stepper_trim(Trim.SURROUND, "trim_surround_down", "down")

    # ---- shape 4: already-async renames ------------------------------------
    # These are the ONE category that must be real `async def`, and the
    # reason is not obvious. MagicMock(spec=Cls) chooses AsyncMock vs
    # MagicMock by asking inspect.iscoroutinefunction of the CLASS
    # attribute. A sync-bodied shim returning a coroutine is not one, so
    # a spec'd mock yields a plain MagicMock and every consumer's
    # `await receiver.async_connect()` raises "MagicMock can't be
    # awaited" - measured at 120 failures in a real integration suite.
    #
    # It does not apply to the sync->async shims above: those were sync
    # in 1.x, so an unmigrated caller does not await them, and an
    # `async def` there would be a silent warning-less no-op. These
    # eight were ALREADY async in 1.x, so every caller already awaits
    # and there is no un-awaited hazard to protect against.

    async def async_connect(self) -> None:
        _deprecated("async_connect", "connect")
        return await self.connect()

    async def async_disconnect(self) -> None:
        _deprecated("async_disconnect", "disconnect")
        return await self.disconnect()

    async def async_pause(self) -> bool:
        _deprecated("async_pause", "player.pause")
        if self.player is None:
            return await _noop_raise_unsupported()
        return await self.player.pause()

    async def async_next(self) -> bool:
        _deprecated("async_next", "player.next_track")
        if self.player is None:
            return await _noop_raise_unsupported()
        return await self.player.next_track()

    async def async_previous(self) -> bool:
        _deprecated("async_previous", "player.previous_track")
        if self.player is None:
            return await _noop_raise_unsupported()
        return await self.player.previous_track()

    async def async_seek(self, position_ms: int) -> bool:
        _deprecated("async_seek", "player.seek")
        if self.player is None:
            return await _noop_raise_unsupported()
        return await self.player.seek(position_ms)

    def async_set_play_mode(self, mode: PlayMode) -> Coroutine[Any, Any, bool]:
        _deprecated("async_set_play_mode", "player.set_play_mode")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.set_play_mode(mode)

    async def async_set_shuffle(self, shuffle: bool) -> bool:
        _deprecated("async_set_shuffle", "player.set_shuffle")
        if self.player is None:
            return await _noop_raise_unsupported()
        return await self.player.set_shuffle(shuffle)

    async def async_set_repeat(self, repeat: Repeat) -> bool:
        _deprecated("async_set_repeat", "player.set_repeat")
        if self.player is None:
            return await _noop_raise_unsupported()
        return await self.player.set_repeat(repeat)

    # ---- shape 5: callback renames ------------------------------------------

    @property
    def _legacy_unsubs(self) -> dict[Callable[[], None], Callable[[], None]]:
        """Lazily-created map of 1.x callback -> its 2.0 unsubscribe.

        A property rather than an __init__ attribute because this is a
        mixin with no constructor of its own, and because a consumer that
        never touches the 1.x names should never allocate it. Dies in 2.1
        with the rest of this file.
        """
        existing = getattr(self, "_legacy_unsubs_map", None)
        if existing is None:
            existing = {}
            self._legacy_unsubs_map = existing
        return existing

    def register_notification_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        _deprecated("register_notification_callback", "on_change")
        unsubscribe = self.on_change(callback)
        # Remember it so the 1.x un_register_* shim below can find it.
        # Keyed on the callback itself: consumers pass bound methods,
        # which are fresh objects on each attribute access but compare
        # and hash equal, so the lookup finds the right unsubscribe.
        self._legacy_unsubs[callback] = unsubscribe
        return unsubscribe

    def un_register_notification_callback(self, callback: Callable[[], None]) -> None:
        """1.x's explicit unregister — deleted in 2.1.

        2.0 returns an unsubscribe from `on_change` instead, so this has
        nothing to delegate to directly; it looks up the unsubscribe that
        `register_notification_callback` stashed. A no-op for a callback
        that was never registered, matching 1.x, which tolerated it.

        Retained rather than removed because a consumer's *teardown* runs
        in every test: leaving one unadapted call site produced 472
        failures in a real integration suite, one line amplified.
        """
        _deprecated(
            "un_register_notification_callback",
            "the unsubscribe returned by on_change",
        )
        unsubscribe = self._legacy_unsubs.pop(callback, None)
        if unsubscribe is not None:
            unsubscribe()

    def register_position_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        _deprecated("register_position_callback", "player.on_position")
        if self.player is None:
            return lambda: None
        return self.player.on_position(callback)

    def register_position_jump_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        _deprecated("register_position_jump_callback", "player.on_position_jump")
        if self.player is None:
            return lambda: None
        return self.player.on_position_jump(callback)

    # -- 1.11-ONLY: the restored 1.x property setters --------------------------
    #
    # Attached at the end of the class body on purpose: `@name.setter`
    # only needs `name` already bound in the class namespace, so keeping
    # all eleven contiguous makes the 2.0 state one deletion rather than
    # eleven edits interleaved through the read shims.
    #
    # Each mirrors its 1.x body and its 2.0 replacement's guards - same
    # exception type, same message shape - so a consumer sees identical
    # behaviour whichever surface it is on. The write itself goes through
    # the control's sync sender rather than awaiting the coroutine: that
    # IS the 1.x contract (enqueue and return), and it is what makes a
    # setter possible at all.
    def _require_zone_b(self, name: str) -> ZoneB:
        """Guard for the Zone B setters, matching set_zone_b_volume's
        existing exception type and message shape."""
        zone_b = self.zone_b
        if zone_b is None:
            raise LyngdorfInvalidValueError(
                f"{name} is not supported by model " f"{self.model.config.model_name}"
            )
        return zone_b


async def _noop_raise_unsupported() -> bool:
    """Returns a coroutine that raises when awaited - for the
    player-None async_* shims (1.x raised only when awaited)."""
    raise LyngdorfUnsupportedError("this model has no streaming module")


# Registries for the completeness test — keep adjacent to the members so
# a member added without a registry entry is visible in the same diff.


SHIMMED_READS: frozenset[str] = frozenset(
    {
        "mute_enabled",
        "volume_range",
        "available_sources",
        "available_sound_modes",
        "available_room_perfect_positions",
        "available_voicings",
        "available_audio_inputs",
        "available_video_inputs",
        "available_stream_types",
        "trim_bass",
        "trim_treble",
        "trim_centre",
        "trim_height",
        "trim_lfe",
        "trim_surround",
        "trim_bass_range",
        "trim_treble_range",
        "trim_centre_range",
        "trim_height_range",
        "trim_lfe_range",
        "trim_surround_range",
        "lipsync_range",
        "zone_b_power_on",
        "zone_b_mute_enabled",
        "zone_b_source",
        "zone_b_audio_input",
        "zone_b_streaming_source",
        "zone_b_volume",
        "zone_b_volume_range",
        "zone_b_available_sources",
        "has_position",
        "has_remote_keys",
        "available_remote_keys",
        "now_playing",
        "position_ms",
        "position_updated_at",
        "position_percent",
        "can_pause",
        "can_next",
        "can_previous",
        "can_seek",
        "can_shuffle",
        "play_mode",
        "shuffle",
        "repeat",
        "available_play_modes",
        "available_repeat_modes",
    }
)
SHIMMED_WRITE_METHODS: frozenset[str] = frozenset(
    {
        "set_volume",
        "set_zone_b_volume",
        "set_lipsync",
        "set_trim_bass",
        "set_trim_treble",
        "set_trim_centre",
        "set_trim_height",
        "set_trim_lfe",
        "set_trim_surround",
        "send_remote_commands",
        "press",
    }
)
SHIMMED_STEPPERS: frozenset[str] = frozenset(
    {
        "volume_up",
        "volume_down",
        "zone_b_volume_up",
        "zone_b_volume_down",
        "trim_bass_up",
        "trim_bass_down",
        "trim_treble_up",
        "trim_treble_down",
        "trim_centre_up",
        "trim_centre_down",
        "trim_height_up",
        "trim_height_down",
        "trim_lfe_up",
        "trim_lfe_down",
        "trim_surround_up",
        "trim_surround_down",
    }
)
SHIMMED_ALREADY_ASYNC: frozenset[str] = frozenset(
    {
        "async_connect",
        "async_disconnect",
        "async_pause",
        "async_next",
        "async_previous",
        "async_seek",
        "async_set_play_mode",
        "async_set_shuffle",
        "async_set_repeat",
    }
)
SHIMMED_CALLBACKS: frozenset[str] = frozenset(
    {
        "register_notification_callback",
        "un_register_notification_callback",
        "register_position_callback",
        "register_position_jump_callback",
    }
)
SHIMMED_MODEL_FEATURE_CHECKS: frozenset[str] = frozenset(
    {
        "has_zone_b_feature",
        "has_video_feature",
        "has_surround_feature",
        "has_streaming_feature",
        "has_lipsync_feature",
        "has_remote_keys_feature",
        "has_bass_trim_feature",
        "has_treble_trim_feature",
        "has_bass_trim_step_feature",
        "has_treble_trim_step_feature",
        "has_mute_state_in_parameter",
    }
)

DIAGNOSTICS_SHIMS: dict[str, str] = {
    "async_probe_device_capabilities": "probe_capabilities",
}

# --- D9 module-level shims (spec §7 module-level rows) ---------------
# The names in MODULE_SHIMS are the OLD names a migrator greps for.
# Their resolution through __init__'s module __getattr__ is what
# emits the warning. Deleted in 2.1 with the rest of this file.

MODULE_SHIMS: dict[str, str] = {
    "Receiver": "LyngdorfReceiver",
    "async_create_receiver": "create_receiver",
    "async_find_receiver_model": "discover_model",
    # Pure string lookup, NOT discover_model - that is an async network
    # probe. A consumer resolving a stored config value must not be made
    # to touch the device to do it. Briefly deleted during the 2.0
    # rewrite, which stopped every such consumer starting at all.
    "lookup_receiver_model": "lookup_model",
    "async_get_device_serial": "discover_ssdp_location + fetch_device_serial",
}


async def legacy_get_device_serial(host: str, timeout: float = 5.0) -> str | None:
    """1.x's async_get_device_serial: the UDP search and the HTTP fetch
    in one call. 2.0 splits them (spec §2.1) so a caller holding an
    ssdp_location skips UDP entirely; this composes the two for callers
    that have not migrated, reproducing 1.x behaviour exactly.

    Imported inside the body: this module is imported by receiver.py, and
    discovery.py imports receiver.py.
    """
    from .discovery import discover_ssdp_location, fetch_device_serial

    location = await discover_ssdp_location(host, timeout)
    if location is None:
        return None
    return await fetch_device_serial(location, timeout=timeout)
