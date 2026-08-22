"""The D9 deprecation shim layer: every 1.x name that was RENAMED or
RELOCATED, as a DeprecationWarning-emitting delegate on LyngdorfReceiver.

Time-boxed scaffolding with a demolition date: this file (and the fenced
has_*_feature block in models/__init__.py, plus the module __getattr__
aliases in lyngdorf/__init__.py) is deleted WHOLESALE in 2.1 - a recorded
work item (design §12), not an intention.

Two things are deliberately absent, and a future reader must not
"complete" the layer (design D9):

- The 18 property setters. Removal is self-enforcing (assignment to a
  read-only property is a static [misc] error locating every consumer
  site), and no compatible shim can be safe: it would be the synchronous
  enqueue issue #51 exists to remove.
- The two reused names, `volume` and `lipsync` - 2.0 reuses them at a new
  type, so one name cannot be a float shim and a control object at once.

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
    pass


def _deprecated(old: str, new: str) -> None:
    warnings.warn(
        f"{old} is deprecated and will be removed in lyngdorf 2.1; use {new}",
        DeprecationWarning,
        stacklevel=3,
    )


async def _noop() -> None:
    """Awaitable no-op - the warn-and-ignore stepper shims return this."""


class _CompatShims:
    """Mixin carrying every receiver-level shim. LyngdorfReceiver
    inherits it; 2.1 deletes the file and drops the base."""

    # ---- shape 1: read shims (read-only properties) -----------------------

    @property
    def mute_enabled(self) -> bool | None:
        _deprecated("mute_enabled", "muted")
        return self.muted

    @property
    def volume_range(self) -> NumericRange:
        _deprecated("volume_range", "volume.range")
        return self.volume.range

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

    @property
    def trim_treble(self) -> float | None:
        _deprecated("trim_treble", "trims[Trim.TREBLE].value")
        ctl = self.trims.get(Trim.TREBLE)
        return ctl.value if ctl is not None else None

    @property
    def trim_centre(self) -> float | None:
        _deprecated("trim_centre", "trims[Trim.CENTER].value")
        ctl = self.trims.get(Trim.CENTER)
        return ctl.value if ctl is not None else None

    @property
    def trim_height(self) -> float | None:
        _deprecated("trim_height", "trims[Trim.HEIGHT].value")
        ctl = self.trims.get(Trim.HEIGHT)
        return ctl.value if ctl is not None else None

    @property
    def trim_lfe(self) -> float | None:
        _deprecated("trim_lfe", "trims[Trim.LFE].value")
        ctl = self.trims.get(Trim.LFE)
        return ctl.value if ctl is not None else None

    @property
    def trim_surround(self) -> float | None:
        _deprecated("trim_surround", "trims[Trim.SURROUND].value")
        ctl = self.trims.get(Trim.SURROUND)
        return ctl.value if ctl is not None else None

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
        return self.lipsync.range if self.lipsync is not None else None

    @property
    def zone_b_power_on(self) -> bool | None:
        _deprecated("zone_b_power_on", "zone_b.power_on")
        return self.zone_b.power_on if self.zone_b is not None else None

    @property
    def zone_b_mute_enabled(self) -> bool | None:
        _deprecated("zone_b_mute_enabled", "zone_b.muted")
        return self.zone_b.muted if self.zone_b is not None else None

    @property
    def zone_b_source(self) -> str | None:
        _deprecated("zone_b_source", "zone_b.source")
        return self.zone_b.source if self.zone_b is not None else None

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
        return self.volume.set(value)

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
        if self.lipsync is None:
            raise LyngdorfInvalidValueError(
                f"lipsync is not supported by model " f"{self.model.config.model_name}"
            )
        return self.lipsync.set(ms)

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
        return self.volume.up()

    def volume_down(self) -> Coroutine[Any, Any, None]:
        _deprecated("volume_down", "volume.down")
        return self.volume.down()

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

    def async_connect(self) -> Coroutine[Any, Any, None]:
        _deprecated("async_connect", "connect")
        return self.connect()

    def async_disconnect(self) -> Coroutine[Any, Any, None]:
        _deprecated("async_disconnect", "disconnect")
        return self.disconnect()

    def async_pause(self) -> Coroutine[Any, Any, bool]:
        _deprecated("async_pause", "player.pause")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.pause()

    def async_next(self) -> Coroutine[Any, Any, bool]:
        _deprecated("async_next", "player.next_track")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.next_track()

    def async_previous(self) -> Coroutine[Any, Any, bool]:
        _deprecated("async_previous", "player.previous_track")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.previous_track()

    def async_seek(self, position_ms: int) -> Coroutine[Any, Any, bool]:
        _deprecated("async_seek", "player.seek")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.seek(position_ms)

    def async_set_play_mode(self, mode: PlayMode) -> Coroutine[Any, Any, bool]:
        _deprecated("async_set_play_mode", "player.set_play_mode")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.set_play_mode(mode)

    def async_set_shuffle(self, shuffle: bool) -> Coroutine[Any, Any, bool]:
        _deprecated("async_set_shuffle", "player.set_shuffle")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.set_shuffle(shuffle)

    def async_set_repeat(self, repeat: Repeat) -> Coroutine[Any, Any, bool]:
        _deprecated("async_set_repeat", "player.set_repeat")
        if self.player is None:
            return _noop_raise_unsupported()
        return self.player.set_repeat(repeat)

    # ---- shape 5: callback renames ------------------------------------------

    def register_notification_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        _deprecated("register_notification_callback", "on_change")
        return self.on_change(callback)

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
