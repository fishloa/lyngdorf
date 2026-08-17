"""
Lyngdorf Audio Control Library - Device Module.

Main receiver classes and factory functions for all supported models.

Supported models are defined by `LyngdorfModel` (see `lyngdorf/models/`);
the README carries the human-readable list.

All communication via TCP/IP on port 84 (no serial port support).
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from .api import LyngdorfApi
from .base import CountingNumberDict, register_in_list
from .const import (
    DEFAULT_LYNGDORF_PORT,
    MP40_AUDIO_INPUTS,
    MP40_STREAM_TYPES,
    MP40_VIDEO_INPUTS,
    MP50_AUDIO_INPUTS,
    MP50_STREAM_TYPES,
    MP50_VIDEO_INPUTS,
    MP50_VIDEO_OUTPUTS,
    MP60_AUDIO_INPUTS,
    MP60_STREAM_TYPES,
    MP60_VIDEO_INPUTS,
    P100_VIDEO_INPUTS,
    P_AUDIO_INPUTS,
    P_VIDEO_INPUTS,
    STATE_ON,
    TDAI1120_STREAM_TYPES,
    TDAI2170_STREAM_TYPES,
    TDAI2210_STREAM_TYPES,
    TDAI3400_STREAM_TYPES,
    LyngdorfModel,
    Msg,
)
from .exceptions import LyngdorfInvalidValueError
from .models import NumericRange
from .states import Control, PlayMode, Repeat
from .streaming import NowPlaying

_LOGGER = logging.getLogger(__package__)


def convert_decibel(value: float | str, scale: float = 10.0) -> float:
    """Convert a wire-protocol numeric parameter to dB.

    `scale` is how many wire units make up 1 dB. Volume is always in
    tenths of a dB on both the MP and TDAI families, so the default of
    10.0 covers every volume call site unchanged. Bass/treble trim is
    NOT uniform across families - the MP series shares volume's tenths
    encoding but the TDAI series' `!BASS`/`!TREBLE` are whole dB only
    (see ModelConfig.trim_bass_treble_scale) - so callers on that path
    must pass the model's own scale explicitly rather than relying on
    this default. See issue #41.
    """
    return float(value) / scale


class Receiver:
    """Lyngdorf client class."""

    def __init__(self, host: str, model: LyngdorfModel):
        """Initialize the client."""
        self._host = host
        self._model = model
        assert model
        assert host
        self._api: LyngdorfApi = LyngdorfApi(host, model)

        # Initialize mutable containers as instance attributes
        # (subclasses set these before calling super())
        if not hasattr(self, "_stream_types"):
            self._stream_types: dict[int, str] = {}
        if not hasattr(self, "_audio_inputs"):
            self._audio_inputs: dict[int, str] = {}
        if not hasattr(self, "_video_inputs"):
            self._video_inputs: dict[int, str] = {}
        self._notification_callbacks: list[Callable[[], None]] = []
        self._sources = CountingNumberDict()
        self._zone_b_sources = CountingNumberDict()
        self._sound_modes = CountingNumberDict()
        self._room_perfect_positions = CountingNumberDict()
        self._voicings = CountingNumberDict()

        # Initialize state attributes
        self._name: str | None = None
        self._volume: float | None = None
        self._max_volume: float | None = None
        self._zone_b_volume: float | None = None
        self._mute_enabled: bool | None = None
        self._zone_b_mute_enabled: bool | None = None
        self._source: str | None = None
        self._zone_b_source: str | None = None
        self._sound_mode: str | None = None
        self._audio_input: str | None = None
        self._zone_b_audio_input: str | None = None
        self._video_input: str | None = None
        self._audio_info: str | None = None
        self._video_info: str | None = None
        self._streaming_source: str | None = None
        self._zone_b_streaming_source: str | None = None
        self._zone_b_audio_info: str | None = None
        self._power_on: bool | None = None
        self._zone_b_power_on: bool | None = None
        self._room_perfect_position: str | None = None
        self._voicing: str | None = None
        self._lipsync: int | None = None
        # Seeded from the documented default (see ModelConfig.lipsync_default_range),
        # not None - a live LIPSYNCRANGE? reply (queried at startup on the
        # MP and P families) overwrites it via _lipsync_range_callback once
        # it arrives. None permanently on a model with no lip sync control
        # at all (the TDAI family).
        self._lipsync_range: NumericRange | None = self._model.lipsync_default_range()
        self._trim_bass: float | None = None
        self._trim_centre: float | None = None
        self._trim_height: float | None = None
        self._trim_lfe: float | None = None
        self._trim_surround: float | None = None
        self._trim_treble: float | None = None
        self._now_playing: NowPlaying | None = None

        # Wired here rather than in async_connect: it is pure Python
        # object plumbing (turning an api-level now-playing update into
        # the Receiver's notification callback) with no dependency on an
        # actual socket connection, so capability properties like
        # `can_pause` stay live even before `async_connect` is called.
        if self._model.has_streaming_feature():
            self._api.register_now_playing_callback(self._now_playing_changed)
            # Play mode changes only on user action (a shuffle/repeat toggle
            # from the front panel or the controlling app), so forwarding
            # every change to the notification callbacks is cheap and
            # correct - unlike position, which is NOT wired this way (see
            # `position_ms`/`register_position_jump_callback` below):
            # position arrives about once a second while playing, and
            # forwarding that would mean a Home Assistant entity state
            # write every second for a value the frontend already
            # extrapolates from `position_ms` plus `position_updated_at`.
            # The asymmetry is deliberate, not an oversight - do not "fix"
            # it by adding position here too.
            self._api.register_play_mode_callback(self._play_mode_changed)

    def _register_callback(
        self, msg: Msg, callback: Callable
    ) -> Callable[[], None] | None:
        """Register a callback for a message, skipping cleanly if the
        connected model's protocol doesn't define that message.

        Model-specific registration (which messages apply to a given
        family, and under what shape) is handled by the per-family
        `_register_*_callbacks` hooks overridden in each Receiver
        subclass. This catch is a safety net for anything not covered by
        those hooks - so an unexpected protocol gap degrades a single
        feature instead of breaking connection setup entirely.

        Returns the unsubscribe from the underlying `LyngdorfApi.register_callback`,
        or None when the model doesn't support the message (nothing was
        registered, so there is nothing to unsubscribe).
        """
        try:
            command = self.lookup_command(msg)
        except KeyError:
            _LOGGER.warning(
                "Model %s does not support message %s; skipping callback registration",
                self._model,
                msg,
            )
            return None
        return self._api.register_callback(command, callback)

    @staticmethod
    def _populate_fixed_list(
        target: CountingNumberDict, fixed_names: dict[int, str], bitmask: str
    ) -> None:
        """Populate a dict of fixed, hardware-defined names filtered by a
        bitmask reply (e.g. TDAI-2170's SRCENABLED/RPSTATUS/VOIENABLED).

        Bit 0 is the least-significant bit, i.e. the rightmost character
        of the bitmask string, per the vendor manual.
        """
        enabled_indices = [i for i, bit in enumerate(reversed(bitmask)) if bit == "1"]
        target.count_callback(str(len(enabled_indices)), "")
        for index in enabled_indices:
            if index in fixed_names:
                target.add(index, fixed_names[index])

    # Per-model-family registration hooks. Each one has a default (MP/P
    # family) implementation here; subclasses override the ones where
    # their protocol genuinely differs, instead of branching on model
    # flags/messages at connect time. See MPReceiver/PReceiver (video +
    # Zone B), MPReceiver (discrete channel trims) and TDAIReceiverBase /
    # TDAI2170Receiver (mute, source, RoomPerfect position/voicing shape).

    def _register_mute_callbacks(self) -> None:
        """MP/P shape: distinct `!MUTEON` / `!MUTEOFF` messages."""
        self._register_callback(Msg.MUTE_ON, self._mute_on_callback)
        self._register_callback(Msg.MUTE_OFF, self._mute_off_callback)

    def _register_source_callbacks(self) -> None:
        self._register_callback(Msg.SOURCES_COUNT, self._sources.count_callback)
        self._register_callback(Msg.SOURCE, self._source_callback)
        self._register_callback(Msg.STREAM_TYPE, self._stream_type_callback)

    def _register_room_perfect_position_callbacks(self) -> None:
        self._register_callback(
            Msg.ROOM_PERFECT_POSITIONS_COUNT,
            self._room_perfect_positions.count_callback,
        )
        self._register_callback(
            Msg.ROOM_PERFECT_POSITION, self._room_perfect_position_callback
        )

    def _register_voicing_callbacks(self) -> None:
        self._register_callback(
            Msg.ROOM_PERFECT_VOICINGS_COUNT, self._voicings.count_callback
        )
        self._register_callback(Msg.ROOM_PERFECT_VOICING, self._voicing_callback)

    def _register_video_callbacks(self) -> None:
        """No-op by default - only models with video inputs/outputs
        override this (MPReceiver, PReceiver)."""

    def _register_zone_b_callbacks(self) -> None:
        """No-op by default - only models with Zone B override this
        (MPReceiver, PReceiver)."""

    def _register_surround_trim_callbacks(self) -> None:
        """No-op by default - only models with discrete multichannel
        speaker trims override this (MPReceiver)."""

    async def async_connect(self):
        # Basics
        self._register_callback(Msg.DEVICE, self._name_callback)
        self._register_callback(Msg.VOLUME, self._volume_callback)
        self._register_callback(Msg.MAX_VOLUME, self._max_volume_callback)
        self._register_callback(Msg.POWER, self._power_callback)
        self._register_mute_callbacks()
        self._register_source_callbacks()
        self._register_video_callbacks()
        self._register_zone_b_callbacks()
        self._register_room_perfect_position_callbacks()
        self._register_voicing_callbacks()

        # Trim and audio modes - not every model has these (the defensive
        # catch in _register_callback logs and skips whichever don't apply)
        self._register_callback(Msg.TRIM_BASS, self._trim_bass_callback)
        self._register_callback(Msg.TRIM_TREBLE, self._trim_treble_callback)
        self._register_callback(Msg.AUDIO_TYPE, self._audio_info_callback)
        self._register_callback(Msg.AUDIO_MODES_COUNT, self._sound_modes.count_callback)
        self._register_callback(Msg.AUDIO_MODE, self._sound_mode_callback)
        self._register_callback(Msg.LIP_SYNC, self._lipsync_callback)
        self._register_callback(Msg.LIP_SYNC_MIN_MAX, self._lipsync_range_callback)
        self._register_surround_trim_callbacks()

        await self._api.async_connect()

    @property
    def connected(self) -> bool:
        """Return True if the receiver connection is active."""
        return self._api.connected

    async def async_disconnect(self):
        await self._api.async_disconnect()

    def lookup_command(self, key: Msg) -> str:
        assert self._model is not None
        return self._model.lookup_command(key)

    # Notifications Support
    def register_notification_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback, returning a callable that unregisters it.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return register_in_list(self._notification_callbacks, callback)

    def un_register_notification_callback(self, callback: Callable[[], None]) -> None:
        with contextlib.suppress(ValueError):
            self._notification_callbacks.remove(callback)

    def _notify_notification_callbacks(self) -> None:
        # Scheduled as a task when a loop is running (the normal case: this
        # fires from inside async message/now-playing processing, and
        # deferring avoids re-entrancy into that processing). Falls back to
        # calling synchronously when there is no running loop - e.g. a bare
        # `Receiver` driven directly from synchronous test code via
        # `_api._update_now_playing`, with no connection ever established.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            for callback in self._notification_callbacks:
                try:
                    callback()
                except Exception:
                    _LOGGER.exception("Event callback caused an unhandled exception")
            return
        asyncio.create_task(self._async_notify_notification_callbacks())

    async def _async_notify_notification_callbacks(self) -> None:
        for callback in self._notification_callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.exception("Event callback caused an unhandled exception")

    # Basics

    def _name_callback(self, param1: str, param2: str) -> None:
        # DEVICE is also the keep-alive probe (ModelConfig.keepalive_message),
        # so this fires every MONITOR_INTERVAL on an idle connection with an
        # unchanged reply - skip the reassignment rather than redo it on
        # every poll for no reason.
        if param1 != self._name:
            self._name = param1

    @property
    def name(self):
        return self._name

    @property
    def host(self) -> str | None:
        return self._host

    @property
    def model(self):
        return self._model

    # Volumes

    def _volume_callback(self, param1: str, ignored: str) -> None:
        self._volume = convert_decibel(param1)
        self._notify_notification_callbacks()

    def _max_volume_callback(self, param1: str, ignored: str) -> None:
        self._max_volume = convert_decibel(param1)
        self._notify_notification_callbacks()

    def _zone_b_volume_callback(self, param1: str, ignored: str) -> None:
        self._zone_b_volume = convert_decibel(param1)
        self._notify_notification_callbacks()

    def _mute_callback(self, param1: str, param2: str):
        self._mute_enabled = STATE_ON == param1
        self._notify_notification_callbacks()

    def _mute_on_callback(self, param1: str, param2: str):
        self._mute_enabled = True
        self._notify_notification_callbacks()

    def _mute_off_callback(self, param1: str, param2: str):
        self._mute_enabled = False
        self._notify_notification_callbacks()

    def _zone_b_mute_on_callback(self, param1: str, param2: str):
        self._zone_b_mute_enabled = True
        self._notify_notification_callbacks()

    def _zone_b_mute_off_callback(self, param1: str, param2: str):
        self._zone_b_mute_enabled = False
        self._notify_notification_callbacks()

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._api.volume(value)

    @property
    def max_volume(self) -> float | None:
        """The device's current MAXVOL setting, in dB, or None on models
        that do not report it. The MP and P families both map
        Msg.MAX_VOLUME (docs/mp-40.md, docs/mp-50.md, docs/mp-60.md,
        docs/p-series.md all document `!MAXVOL`) - contrary to issue #40's
        original premise that this was MP-only. The TDAI family's manuals
        (docs/tdai-1120.md, docs/tdai-2170.md, docs/tdai-3400.md) document
        no MAXVOL command at all, so it stays None there.

        The vendor-documented bounds are not reliable enough to validate
        against: docs/mp-40.md/docs/mp-60.md give -55.0..-20.0 dB while
        docs/p-series.md gives -55.0..+24.0 dB for the very same command,
        and a real MP-60 on firmware 5.4.2 answered !MAXVOL(0), i.e.
        0.0 dB - outside the MP-40/MP-60 documented range. This value is
        therefore read and surfaced as-is, never validated against any
        range - do not add validation here.

        This is a user-settable safety ceiling, not the hardware's
        physical volume range - it can be changed at runtime from the
        front panel or the official app, the same way
        `homeassistant-projects/hass-lyngdorf`'s get_max()/set_max() work
        against this same command. Do not treat it as a fixed slider
        maximum; poll or subscribe to notification callbacks rather than
        caching it once.
        """
        return self._max_volume

    @property
    def zone_b_volume(self):
        return self._zone_b_volume

    @zone_b_volume.setter
    def zone_b_volume(self, value: float) -> None:
        self._api.zone_b_volume(value)

    def volume_up(self):
        self._api.volume_up()

    def volume_down(self):
        self._api.volume_down()

    def zone_b_volume_up(self):
        self._api.zone_b_volume_up()

    def zone_b_volume_down(self):
        self._api.zone_b_volume_down()

    @property
    def mute_enabled(self):
        return self._mute_enabled

    @mute_enabled.setter
    def mute_enabled(self, enabled: bool):
        self._api.mute_enabled(enabled)

    @property
    def zone_b_mute_enabled(self):
        return self._zone_b_mute_enabled

    @zone_b_mute_enabled.setter
    def zone_b_mute_enabled(self, enabled: bool):
        self._api.zone_b_mute_enabled(enabled)

    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, source: str):
        index = self._sources.lookupIndex(source)
        if index > -1:
            self._api.change_source(index)
        else:
            raise LyngdorfInvalidValueError(
                "%s is not a valid source name, and cannot be chosen", source
            )

    def _source_callback(self, param1: str, param2: str):
        if self._sources.is_full():
            self._source = param2
            self._notify_notification_callbacks()
        else:
            self._sources.add(int(param1), param2)

    def _source_name_callback(self, param1: str, param2: str):
        """Handle a SRCNAME reply (TDAI): index and name arrive comma-
        separated inside one set of parens - "!SRCNAME(0,\"HDMI\")" - not
        split into two fields the way MP's "!SRC(0)\"HDMI\"" is, so this
        can't reuse _source_callback's parsing.
        """
        index_str, _, name = param1.partition(",")
        name = name.strip('"')
        if self._sources.is_full():
            self._source = name
            self._notify_notification_callbacks()
        else:
            self._sources.add(int(index_str), name)

    def _sources_enabled_callback(self, param1: str, param2: str) -> None:
        """Handle a SRCENABLED reply (TDAI-2170): populate the fixed source
        table filtered by which of its entries are enabled."""
        self._populate_fixed_list(
            self._sources, self._model.config.fixed_sources or {}, param1
        )

    def _fixed_source_callback(self, param1: str, param2: str) -> None:
        """Handle a SRC reply on a model with a fixed source table
        (TDAI-2170): the reply is a bare index with no name, so resolve it
        against the table _sources_enabled_callback already populated."""
        self._source = self._sources.get(int(param1))
        self._notify_notification_callbacks()

    @property
    def available_sources(self) -> list[str]:
        return list(self._sources.values())

    @property
    def zone_b_source(self):
        return self._zone_b_source

    @zone_b_source.setter
    def zone_b_source(self, zone_b_source: str):
        index = self._zone_b_sources.lookupIndex(zone_b_source)
        if index > -1:
            self._api.change_zone_b_source(index)
        else:
            raise LyngdorfInvalidValueError(
                "%s is not a valid zone b source name, and cannot be chosen",
                zone_b_source,
            )

    def _zone_b_source_callback(self, param1: str, param2: str):
        if self._zone_b_sources.is_full():
            self._zone_b_source = param2
            self._notify_notification_callbacks()
        else:
            self._zone_b_sources.add(int(param1), param2)

    @property
    def zone_b_available_sources(self) -> list[str]:
        return list(self._zone_b_sources.values())

    @property
    def audio_input(self):
        return self._audio_input

    def _audio_input_callback(self, param1: str, param2: str):
        if int(param1) in self._audio_inputs:
            self._audio_input = self._audio_inputs[int(param1)]
        else:
            self._audio_input = f"audio-{param1}"
            _LOGGER.warning(f"audio_input({param1} is not known, so ignoring)")
        self._notify_notification_callbacks()

    @property
    def available_audio_inputs(self) -> list[str]:
        """Every audio input name this model's protocol defines.

        Empty for a model with no audio input table at all (e.g. a TDAI).

        Unrecognised wire values deliberately escape this table (see
        `audio_input`/`_audio_input_callback`), so the current
        `audio_input` value is not guaranteed to be a member of this
        list - a consumer building a closed-option enum (e.g. Home
        Assistant's `SensorDeviceClass.ENUM`) must treat a value outside
        this list as unknown/unmapped rather than invalid.
        """
        return list(self._audio_inputs.values())

    @property
    def zone_b_audio_input(self):
        return self._zone_b_audio_input

    def _zone_b_audio_input_callback(self, param1: str, param2: str):
        if int(param1) in self._audio_inputs:
            self._zone_b_audio_input = self._audio_inputs[int(param1)]
        else:
            self._zone_b_audio_input = f"audio-{param1}"
            _LOGGER.warning(f"zone_b_audio_input({param1}) is not known, so ignoring")
        self._notify_notification_callbacks()

    @property
    def video_input(self):
        return self._video_input

    def _video_input_callback(self, param1: str, param2: str):
        if int(param1) in self._video_inputs:
            self._video_input = self._video_inputs[int(param1)]
        else:
            self._video_input = f"video-{param1}"
            _LOGGER.warning(f"zone_b_video_input({param1}) is not known, so ignoring")
        self._notify_notification_callbacks()

    @property
    def available_video_inputs(self) -> list[str]:
        """Every video input name this model's protocol defines.

        Empty for a model with no video input table at all (e.g. a TDAI,
        which has no video inputs).

        Unrecognised wire values deliberately escape this table (see
        `video_input`/`_video_input_callback`), so the current
        `video_input` value is not guaranteed to be a member of this
        list - a consumer building a closed-option enum (e.g. Home
        Assistant's `SensorDeviceClass.ENUM`) must treat a value outside
        this list as unknown/unmapped rather than invalid.
        """
        return list(self._video_inputs.values())

    @property
    def streaming_source(self):
        return self._streaming_source

    @property
    def zone_b_streaming_source(self):
        return self._zone_b_streaming_source

    def _stream_type_callback(self, param1: str, param2: str):
        if int(param1) in self._stream_types:
            self._streaming_source = self._stream_types[int(param1)]
        else:
            self._streaming_source = f"video-{param1}"
            _LOGGER.warning(f"stream_type({param1}) is not known, so ignoring")
        self._notify_notification_callbacks()

    def _zone_b_stream_type_callback(self, param1: str, param2: str):
        if int(param1) in self._stream_types:
            self._zone_b_streaming_source = self._stream_types[int(param1)]
        else:
            self._zone_b_streaming_source = f"video-{param1}"
            _LOGGER.warning(f"zone_b_stream_type({param1}) is not known, so ignoring")
        self._notify_notification_callbacks()

    @property
    def available_stream_types(self) -> list[str]:
        """Every streaming source type name this model's protocol
        defines.

        Empty for a model with no stream type table at all.

        Unrecognised wire values deliberately escape this table (see
        `streaming_source`/`_stream_type_callback`), so the current
        `streaming_source` value is not guaranteed to be a member of
        this list - a consumer building a closed-option enum (e.g. Home
        Assistant's `SensorDeviceClass.ENUM`) must treat a value outside
        this list as unknown/unmapped rather than invalid.
        """
        return list(self._stream_types.values())

    @property
    def audio_information(self):
        return self._audio_info

    def _audio_info_callback(self, param1: str, param2: str):
        self._audio_info = param1
        self._notify_notification_callbacks()

    @property
    def video_information(self):
        return self._video_info

    def _video_info_callback(self, param1: str, param2: str):
        self._video_info = param1
        self._notify_notification_callbacks()

    @property
    def sound_mode(self):
        return self._sound_mode

    @sound_mode.setter
    def sound_mode(self, sound_mode: str):
        index = self._sound_modes.lookupIndex(sound_mode)
        if index > -1:
            self._api.change_sound_mode(index)
        else:
            raise LyngdorfInvalidValueError(
                "%s is not a valid sound mode name, and cannot be chosen", sound_mode
            )

    def _sound_mode_callback(self, param1: str, param2: str):
        if self._sound_modes.is_full():
            self._sound_mode = param2
            self._notify_notification_callbacks()
        else:
            self._sound_modes.add(int(param1), param2)

    @property
    def available_sound_modes(self) -> list[str]:
        return list(self._sound_modes.values())

    def _power_callback(self, param1: str, param2: str):
        self._power_on = self._model.power_state_on_value() == param1
        if self._power_on:
            self._requery_mute()
        # Only poll the streaming module while the device is actually on.
        self._api.set_power_state(self._power_on)
        self._notify_notification_callbacks()

    def _requery_mute(self) -> None:
        """Re-query mute status from the device.

        Power cycling can silently clear mute without a push notification,
        leaving stale cached state. See #26.
        """
        mute_cmd = self._model.lookup_command(Msg.MUTE)
        self._api._writeCommand(f"{mute_cmd}?")

    def _zone_b_power_callback(self, param1: str, param2: str):
        self._zone_b_power_on = self._model.power_state_on_value() == param1
        if self._zone_b_power_on:
            self._requery_zone_b_mute()
        self._notify_notification_callbacks()

    def _requery_zone_b_mute(self) -> None:
        """Re-query Zone B mute status. See _requery_mute / #26."""
        if not self._model.has_zone_b_feature():
            return
        try:
            mute_cmd = self._model.lookup_command(Msg.ZONE_B_MUTE)
            self._api._writeCommand(f"{mute_cmd}?")
        except KeyError:
            pass

    @property
    def power_on(self):
        return self._power_on

    @power_on.setter
    def power_on(self, enabled: bool):
        self._api.power_on(enabled)

    @property
    def zone_b_power_on(self):
        return self._zone_b_power_on

    @zone_b_power_on.setter
    def zone_b_power_on(self, enabled: bool):
        self._api.zone_b_power_on(enabled)

    # Audio Tuning
    def _room_perfect_position_callback(self, param1: str, param2: str):
        if self._room_perfect_positions.is_full():
            self._room_perfect_position = param2
            self._notify_notification_callbacks()
        else:
            self._room_perfect_positions.add(int(param1), param2)

    def _room_perfect_position_name_callback(self, param1: str, param2: str):
        """Handle an RPNAME reply (TDAI-1120/3400): index and name arrive
        comma-separated inside one set of parens - !RPNAME(0,"Bypass") -
        rather than split into two fields the way MP's !RPFOC(0)"Bypass"
        is, so this can't reuse _room_perfect_position_callback's parsing.
        Mirrors _source_name_callback.
        """
        index_str, _, name = param1.partition(",")
        name = name.strip('"')
        if self._room_perfect_positions.is_full():
            self._room_perfect_position = name
            self._notify_notification_callbacks()
        else:
            self._room_perfect_positions.add(int(index_str), name)

    def _room_perfect_positions_present_callback(
        self, param1: str, param2: str
    ) -> None:
        """Handle an RPSTATUS reply (TDAI-2170): populate the fixed
        RoomPerfect position table filtered by which are present."""
        self._populate_fixed_list(
            self._room_perfect_positions,
            self._model.config.room_perfect_positions or {},
            param1,
        )

    def _fixed_room_perfect_position_callback(self, param1: str, param2: str) -> None:
        """Handle an RP reply on a model with a fixed position table
        (TDAI-2170): the reply is a bare index with no name, so resolve it
        against the table _room_perfect_positions_present_callback already
        populated."""
        self._room_perfect_position = self._room_perfect_positions.get(int(param1))
        self._notify_notification_callbacks()

    @property
    def available_room_perfect_positions(self) -> list[str]:
        return list(self._room_perfect_positions.values())

    @property
    def room_perfect_position(self):
        return self._room_perfect_position

    @room_perfect_position.setter
    def room_perfect_position(self, room_perfect_position: str):
        index = self._room_perfect_positions.lookupIndex(room_perfect_position)
        if index > -1:
            self._api.change_room_perfect_position(index)
        else:
            raise LyngdorfInvalidValueError(
                "%s is not a valid room_perfect_position name, and cannot be chosen",
                room_perfect_position,
            )

    def _voicing_callback(self, param1: str, param2: str):
        if self._voicings.is_full():
            self._voicing = param2
            self._notify_notification_callbacks()
        else:
            self._voicings.add(int(param1), param2)

    def _voicing_name_callback(self, param1: str, param2: str):
        """Handle a VOINAME reply (TDAI-1120/3400): same comma-packed shape
        as RPNAME and SRCNAME - !VOINAME(0,"Neutral").
        """
        index_str, _, name = param1.partition(",")
        name = name.strip('"')
        if self._voicings.is_full():
            self._voicing = name
            self._notify_notification_callbacks()
        else:
            self._voicings.add(int(index_str), name)

    def _voicings_enabled_callback(self, param1: str, param2: str) -> None:
        """Handle a VOIENABLED reply (TDAI-2170): populate the fixed
        voicing table filtered by which are enabled."""
        self._populate_fixed_list(
            self._voicings, self._model.config.fixed_voicings or {}, param1
        )

    def _fixed_voicing_callback(self, param1: str, param2: str) -> None:
        """Handle a VOI reply on a model with a fixed voicing table
        (TDAI-2170): the reply is a bare index with no name, so resolve it
        against the table _voicings_enabled_callback already populated."""
        self._voicing = self._voicings.get(int(param1))
        self._notify_notification_callbacks()

    @property
    def available_voicings(self) -> list[str]:
        return list(self._voicings.values())

    @property
    def voicing(self):
        return self._voicing

    @voicing.setter
    def voicing(self, voicing: str):
        index = self._voicings.lookupIndex(voicing)
        if index > -1:
            self._api.change_voicing(index)
        else:
            raise LyngdorfInvalidValueError(
                "%s is not a valid voicing name, and cannot be chosen", voicing
            )

    def _lipsync_range_callback(self, param1: str, ignored: str) -> None:
        """Handle a LIPSYNCRANGE reply - `!LIPSYNCRANGE(min,max)` arrives
        as a single comma-separated field (see `LyngdorfApi._process_event`,
        which only splits on the first top-level `(`/`)` pair), not two
        distinct positional params the way most two-value replies do.
        Confirmed against a real MP-60 on firmware 5.4.2: `!LIPSYNCRANGE(0,500)`.
        """
        min_str, _, max_str = param1.partition(",")
        self._lipsync_range = NumericRange(
            min=float(min_str), max=float(max_str), step=1.0
        )
        self._notify_notification_callbacks()

    @property
    def lipsync_range(self) -> NumericRange | None:
        """The device's valid lipsync range, in ms.

        Reflects a live `!LIPSYNCRANGE(min,max)` reply once one has
        arrived (queried at startup on the MP and P families - see
        `mp_series.MP_SETUP_MESSAGES`/`p_series.P_SETUP_MESSAGES`); until
        then, the documented default (`NumericRange(0, 500, 1)`, matching
        a real MP-60's measured reply). None on a model with no lip sync
        control at all (the TDAI family - see `has_lipsync_feature`).
        """
        return self._lipsync_range

    def _validate_numeric(
        self, name: str, value: float, range_: NumericRange | None
    ) -> None:
        """Raise LyngdorfInvalidValueError if `value` is outside `range_`,
        or if `range_` is None - meaning the connected model has no such
        setting at all, e.g. `trim_centre` on a TDAI, or `lipsync` on any
        TDAI. Consistent with how `source`/`zone_b_source`/`voicing`/
        `room_perfect_position` already raise on an invalid choice, rather
        than with `trim_bass_up`'s warn-and-ignore for a model that can't
        step - an absolute setter has no discrete "nearest valid choice"
        to silently fall back to the way a stepping command does, so
        raising is the only option that does not either send a
        wire command the model does not define or silently drop a
        genuine caller bug.
        """
        if range_ is None:
            raise LyngdorfInvalidValueError(
                f"{name} is not supported by model {self._model.model_name}"
            )
        if not range_.min <= value <= range_.max:
            raise LyngdorfInvalidValueError(
                f"{name} {value} is outside {range_.min}..{range_.max}"
            )

    def _lipsync_callback(self, param1: str, param2: str):
        self._lipsync = int(param1)
        self._notify_notification_callbacks()

    @property
    def lipsync(self):
        return self._lipsync

    @lipsync.setter
    def lipsync(self, lipsync: int):
        self._validate_numeric("lipsync", lipsync, self.lipsync_range)
        self._api.change_lipsync(lipsync)

    # trims
    def _trim_bass_callback(self, param1: str, ignored: str) -> None:
        self._trim_bass = convert_decibel(param1, self._model.trim_bass_treble_scale())
        self._notify_notification_callbacks()

    @property
    def trim_bass(self):
        return self._trim_bass

    @trim_bass.setter
    def trim_bass(self, trim: float):
        self._validate_numeric("trim_bass", trim, self.trim_bass_range)
        self._api.change_trim_bass(trim)

    @property
    def trim_bass_range(self) -> NumericRange | None:
        """The documented dB range (and UI step) for `trim_bass`, or None
        on a model with no bass trim at all (TDAI-2170)."""
        return self._model.trim_bass_range()

    def trim_bass_up(self):
        self._api.trim_bass_up()

    def trim_bass_down(self):
        self._api.trim_bass_down()

    def _trim_centre_callback(self, param1: str, ignored: str) -> None:
        self._trim_centre = convert_decibel(param1)
        self._notify_notification_callbacks()

    @property
    def trim_centre(self):
        return self._trim_centre

    @trim_centre.setter
    def trim_centre(self, trim: float):
        self._validate_numeric("trim_centre", trim, self.trim_centre_range)
        self._api.change_trim_centre(trim)

    @property
    def trim_centre_range(self) -> NumericRange | None:
        """The documented dB range (and UI step) for `trim_centre`, or
        None on a model with no discrete channel trims at all (see
        `has_surround_feature`)."""
        return self._model.trim_centre_range()

    def trim_centre_up(self):
        self._api.trim_centre_up()

    def trim_centre_down(self):
        self._api.trim_centre_down()

    def _trim_height_callback(self, param1: str, ignored: str) -> None:
        self._trim_height = convert_decibel(param1)
        self._notify_notification_callbacks()

    @property
    def trim_height(self):
        return self._trim_height

    @trim_height.setter
    def trim_height(self, trim: float):
        self._validate_numeric("trim_height", trim, self.trim_height_range)
        self._api.change_trim_height(trim)

    @property
    def trim_height_range(self) -> NumericRange | None:
        """The documented dB range (and UI step) for `trim_height`, or
        None on a model with no discrete channel trims at all (see
        `has_surround_feature`)."""
        return self._model.trim_height_range()

    def trim_height_up(self):
        self._api.trim_height_up()

    def trim_height_down(self):
        self._api.trim_height_down()

    def _trim_lfe_callback(self, param1: str, ignored: str) -> None:
        self._trim_lfe = convert_decibel(param1)
        self._notify_notification_callbacks()

    @property
    def trim_lfe(self):
        return self._trim_lfe

    @trim_lfe.setter
    def trim_lfe(self, trim: float):
        self._validate_numeric("trim_lfe", trim, self.trim_lfe_range)
        self._api.change_trim_lfe(trim)

    @property
    def trim_lfe_range(self) -> NumericRange | None:
        """The documented dB range (and UI step) for `trim_lfe`, or None
        on a model with no discrete channel trims at all (see
        `has_surround_feature`)."""
        return self._model.trim_lfe_range()

    def trim_lfe_up(self):
        self._api.trim_lfe_up()

    def trim_lfe_down(self):
        self._api.trim_lfe_down()

    def _trim_surround_callback(self, param1: str, ignored: str) -> None:
        self._trim_surround = convert_decibel(param1)
        self._notify_notification_callbacks()

    @property
    def trim_surround(self):
        return self._trim_surround

    @trim_surround.setter
    def trim_surround(self, trim: float):
        self._validate_numeric("trim_surround", trim, self.trim_surround_range)
        self._api.change_trim_surround(trim)

    @property
    def trim_surround_range(self) -> NumericRange | None:
        """The documented dB range (and UI step) for `trim_surround`, or
        None on a model with no discrete channel trims at all (see
        `has_surround_feature`)."""
        return self._model.trim_surround_range()

    def trim_surround_up(self):
        self._api.trim_surround_up()

    def trim_surround_down(self):
        self._api.trim_surround_down()

    def _trim_treble_callback(self, param1: str, ignored: str) -> None:
        self._trim_treble = convert_decibel(
            param1, self._model.trim_bass_treble_scale()
        )
        self._notify_notification_callbacks()

    @property
    def trim_treble(self):
        return self._trim_treble

    @trim_treble.setter
    def trim_treble(self, trim: float):
        self._validate_numeric("trim_treble", trim, self.trim_treble_range)
        self._api.change_trim_treble(trim)

    @property
    def trim_treble_range(self) -> NumericRange | None:
        """The documented dB range (and UI step) for `trim_treble`, or
        None on a model with no treble trim at all (TDAI-2170)."""
        return self._model.trim_treble_range()

    def trim_treble_up(self):
        self._api.trim_treble_up()

    def trim_treble_down(self):
        self._api.trim_treble_down()

    # Now-playing metadata (streaming-capable models only)

    @property
    def now_playing(self) -> NowPlaying | None:
        return self._now_playing

    def _now_playing_changed(self, np: NowPlaying | None) -> None:
        self._now_playing = np
        self._notify_notification_callbacks()

    def _play_mode_changed(self, mode: PlayMode | None) -> None:
        """Forward a play-mode change to the notification callbacks.

        Fixes a defect where changing shuffle/repeat from the front panel
        or the controlling app updated `Receiver.play_mode` silently: no
        notification fired, so a Home Assistant entity showed stale
        shuffle/repeat state until something unrelated triggered a write.
        See the registration in `__init__` for why position is NOT
        forwarded the same way.
        """
        self._notify_notification_callbacks()

    def register_position_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        """Register a callback for every raw position change.

        Delegates to `LyngdorfApi.register_position_callback` - see there
        for the full contract, including the once-a-second firing rate
        while playing. For a consumer where each call costs something, use
        `register_position_jump_callback` instead.
        """
        return self._api.register_position_callback(callback)

    def register_position_jump_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        """Register a callback for position *discontinuities* only.

        Delegates to `LyngdorfApi.register_position_jump_callback` - see
        there for the full contract. Unlike play mode, position is never
        forwarded to `_notify_notification_callbacks`: the consumer chooses
        which stream it wants (this one, or the raw per-tick position via
        `register_position_callback`), and the library does not decide
        that for it.
        """
        return self._api.register_position_jump_callback(callback)

    @property
    def has_position(self) -> bool:
        """Whether this model can report playback position at all.

        Position comes from the embedded streaming module, which only
        some models have - the TDAI-2170 and the P series have no
        streaming hardware, so there is nothing to report on those.
        """
        return self._model.has_streaming_feature()

    @property
    def position_ms(self) -> int | None:
        """Elapsed playback position in milliseconds, or None if unknown.

        Always None on models without a streaming module.
        """
        if not self.has_position:
            return None
        return self._api.position_ms

    @property
    def position_updated_at(self) -> datetime | None:
        """When `position_ms` was last refreshed from the device."""
        if not self.has_position:
            return None
        return self._api.position_updated_at

    @property
    def position_percent(self) -> float | None:
        """Fraction of the current track played, 0.0-1.0.

        None when either position or duration is unknown, or when the
        duration is zero - live streams report a duration of 0, and a
        progress fraction is meaningless for them.
        """
        duration = self._now_playing.duration_ms if self._now_playing else None
        if self.position_ms is None or not duration:
            return None
        return min(1.0, self.position_ms / duration)

    @property
    def can_pause(self) -> bool:
        """Whether the current source offers pause.

        Narrows and widens as the source changes, and is False whenever
        nothing is playing.
        """
        return Control.PAUSE in self._api.available_controls

    @property
    def can_next(self) -> bool:
        """Whether the current source offers skip-forward."""
        return Control.NEXT_TRACK in self._api.available_controls

    @property
    def can_previous(self) -> bool:
        """Whether the current source offers skip-back."""
        return Control.PREVIOUS_TRACK in self._api.available_controls

    @property
    def can_seek(self) -> bool:
        """Whether the current source offers seek.

        AirPlay does not; Spotify Connect does. Note the payload's `live`
        and `audioType` fields say nothing useful about this - both
        sources report `live: true`.
        """
        return Control.SEEK in self._api.available_controls

    @property
    def available_play_modes(self) -> frozenset[PlayMode]:
        """Shuffle/repeat modes the current source offers."""
        return self._api.available_play_modes

    @property
    def play_mode(self) -> PlayMode | None:
        """Current shuffle/repeat mode, or None if unknown/unavailable."""
        return self._api.play_mode

    @property
    def shuffle(self) -> bool | None:
        """Current shuffle setting, or None if unknown/unavailable.

        Mirrors Home Assistant's own model: shuffle as a bool, repeat as a
        separate `Repeat` value, rather than one combined string.
        """
        return self._api.shuffle

    @property
    def repeat(self) -> Repeat | None:
        """Current repeat setting, or None if unknown/unavailable."""
        return self._api.repeat

    @property
    def can_shuffle(self) -> bool:
        """Whether shuffle can be toggled independently of repeat."""
        return self._api.can_shuffle

    @property
    def available_repeat_modes(self) -> frozenset[Repeat]:
        """Repeat values reachable from the current shuffle setting."""
        return self._api.available_repeat_modes

    async def async_pause(self) -> bool:
        """Toggle pause on the current source.

        There is no separate resume: on a source the device streams
        itself this pauses a playing track and resumes a paused one.

        On AirPlay and other controller-driven sources it instead ends the
        session, and the device cannot restart it - only the controlling
        app can. Afterwards the device reports no controls at all, so
        `can_pause` becomes False.
        """
        return await self._api.async_pause()

    async def async_next(self) -> bool:
        """Skip to the next track."""
        return await self._api.async_next()

    async def async_previous(self) -> bool:
        """Skip to the previous track."""
        return await self._api.async_previous()

    async def async_seek(self, position_ms: int) -> bool:
        """Seek to an absolute position, in milliseconds."""
        return await self._api.async_seek(position_ms)

    async def async_set_play_mode(self, mode: PlayMode) -> bool:
        """Set the combined shuffle/repeat mode."""
        return await self._api.async_set_play_mode(mode)

    async def async_set_shuffle(self, shuffle: bool) -> bool:
        """Set shuffle, carrying the current repeat setting over unchanged.

        See `LyngdorfApi.async_set_shuffle` - the current repeat setting is
        preserved rather than left to the device to infer.
        """
        return await self._api.async_set_shuffle(shuffle)

    async def async_set_repeat(self, repeat: Repeat) -> bool:
        """Set repeat, carrying the current shuffle setting over unchanged.

        See `LyngdorfApi.async_set_repeat`.
        """
        return await self._api.async_set_repeat(repeat)


if TYPE_CHECKING:
    _ReceiverMixinBase = Receiver
else:
    _ReceiverMixinBase = object


class _VideoZoneBReceiverMixin(_ReceiverMixinBase):
    """Shared video-routing and Zone B registration for the MP and P
    families - the only two with either feature. Relies on
    `_register_callback` from `Receiver`, always mixed in alongside it -
    the TYPE_CHECKING base above is only so mypy knows that, since at
    runtime this mixes in ahead of the real `Receiver` base instead."""

    def _register_video_callbacks(self) -> None:
        self._register_callback(Msg.AUDIO_IN, self._audio_input_callback)
        self._register_callback(Msg.VIDEO_IN, self._video_input_callback)
        self._register_callback(Msg.VIDEO_TYPE, self._video_info_callback)

    def _register_zone_b_callbacks(self) -> None:
        self._register_callback(Msg.ZONE_B_VOLUME, self._zone_b_volume_callback)
        self._register_callback(Msg.ZONE_B_MUTE_ON, self._zone_b_mute_on_callback)
        self._register_callback(Msg.ZONE_B_MUTE_OFF, self._zone_b_mute_off_callback)
        self._register_callback(
            Msg.ZONE_B_SOURCES_COUNT, self._zone_b_sources.count_callback
        )
        self._register_callback(Msg.ZONE_B_SOURCE, self._zone_b_source_callback)
        self._register_callback(Msg.ZONE_B_AUDIO_IN, self._zone_b_audio_input_callback)
        self._register_callback(
            Msg.ZONE_B_STREAM_TYPE, self._zone_b_stream_type_callback
        )
        self._register_callback(Msg.ZONE_B_POWER, self._zone_b_power_callback)


class MPReceiver(_VideoZoneBReceiverMixin, Receiver):
    """Shared MP-family behaviour: video routing, Zone B, and discrete
    multichannel speaker trims, all on top of the default (MP/P-shaped)
    mute/source/RoomPerfect registration."""

    def _register_surround_trim_callbacks(self) -> None:
        self._register_callback(Msg.TRIM_CENTRE, self._trim_centre_callback)
        self._register_callback(Msg.TRIM_HEIGHT, self._trim_height_callback)
        self._register_callback(Msg.TRIM_LFE, self._trim_lfe_callback)
        self._register_callback(Msg.TRIM_SURROUND, self._trim_surround_callback)


class PReceiver(_VideoZoneBReceiverMixin, Receiver):
    """Shared P-family behaviour: video routing and Zone B, but no
    discrete channel trims (the base no-op default applies)."""


class TDAIReceiverBase(Receiver):
    """Shared TDAI-1120/3400 behaviour (also the base for TDAI-2170,
    which overrides source/RoomPerfect registration again below): mute
    arrives as a `!MUTE(ON)`/`!MUTE(OFF)` parameter rather than distinct
    MUTEON/MUTEOFF messages, and source/RoomPerfect-position/voicing
    names arrive under SRCNAME/RPNAME/VOINAME (comma-packed) rather than
    alongside the bare index/count burst. No video, Zone B, or discrete
    channel trims (the base no-op defaults apply)."""

    def _register_mute_callbacks(self) -> None:
        self._register_callback(Msg.MUTE, self._mute_callback)

    def _register_source_callbacks(self) -> None:
        self._register_callback(Msg.SOURCES_COUNT, self._sources.count_callback)
        self._register_callback(Msg.SOURCE_NAME, self._source_name_callback)
        self._register_callback(Msg.STREAM_TYPE, self._stream_type_callback)

    def _register_room_perfect_position_callbacks(self) -> None:
        self._register_callback(
            Msg.ROOM_PERFECT_POSITIONS_COUNT,
            self._room_perfect_positions.count_callback,
        )
        self._register_callback(
            Msg.ROOM_PERFECT_POSITION_NAME,
            self._room_perfect_position_name_callback,
        )

    def _register_voicing_callbacks(self) -> None:
        self._register_callback(
            Msg.ROOM_PERFECT_VOICINGS_COUNT, self._voicings.count_callback
        )
        self._register_callback(
            Msg.ROOM_PERFECT_VOICING_NAME, self._voicing_name_callback
        )


class MP40Receiver(MPReceiver):
    """Lyngdorf MP-40 receiver client."""

    def __init__(self, host: str):
        """Initialize the MP-40 client."""
        self._audio_inputs = MP40_AUDIO_INPUTS
        self._video_inputs = MP40_VIDEO_INPUTS
        self._stream_types = MP40_STREAM_TYPES
        super().__init__(host, LyngdorfModel.MP_40)


class MP50Receiver(MPReceiver):
    """Lyngdorf MP-50 receiver client."""

    def __init__(self, host: str):
        """Initialize the MP-50 client."""
        self._audio_inputs = MP50_AUDIO_INPUTS
        self._video_inputs = MP50_VIDEO_INPUTS
        self._video_outputs = MP50_VIDEO_OUTPUTS
        self._stream_types = MP50_STREAM_TYPES
        super().__init__(host, LyngdorfModel.MP_50)


class MP60Receiver(MPReceiver):

    def __init__(self, host: str):
        """Initialize the client."""
        self._audio_inputs = MP60_AUDIO_INPUTS
        self._video_inputs = MP60_VIDEO_INPUTS
        self._stream_types = MP60_STREAM_TYPES
        super().__init__(host, LyngdorfModel.MP_60)


class TDAI1120Receiver(TDAIReceiverBase):

    def __init__(self, host: str):
        """Initialize the client."""
        self._audio_inputs = {}  # TDAI-1120 uses dynamic source list
        self._video_inputs = {}  # TDAI-1120 has no video inputs
        self._stream_types = TDAI1120_STREAM_TYPES
        super().__init__(host, LyngdorfModel.TDAI_1120)


class TDAI2170Receiver(TDAIReceiverBase):
    """Lyngdorf TDAI-2170 receiver client: fixed hardware source/
    RoomPerfect-position/voicing tables gated by bitmask replies
    (SRCENABLED/RPSTATUS/VOIENABLED) rather than a dynamic enumeration
    burst - see models/tdai_series.py."""

    def __init__(self, host: str):
        """Initialize the TDAI-2170 client."""
        self._audio_inputs = {}  # TDAI-2170 uses dynamic source list
        self._video_inputs = {}  # TDAI-2170 has no video inputs
        self._stream_types = TDAI2170_STREAM_TYPES
        super().__init__(host, LyngdorfModel.TDAI_2170)

    def _register_source_callbacks(self) -> None:
        self._register_callback(Msg.SOURCES_ENABLED, self._sources_enabled_callback)
        self._register_callback(Msg.SOURCE, self._fixed_source_callback)

    def _register_room_perfect_position_callbacks(self) -> None:
        self._register_callback(
            Msg.ROOM_PERFECT_POSITIONS_PRESENT,
            self._room_perfect_positions_present_callback,
        )
        self._register_callback(
            Msg.ROOM_PERFECT_POSITION,
            self._fixed_room_perfect_position_callback,
        )

    def _register_voicing_callbacks(self) -> None:
        self._register_callback(
            Msg.ROOM_PERFECT_VOICINGS_ENABLED, self._voicings_enabled_callback
        )
        self._register_callback(Msg.ROOM_PERFECT_VOICING, self._fixed_voicing_callback)


class TDAI2210Receiver(TDAIReceiverBase):
    """Lyngdorf TDAI-2210 receiver client (same protocol as TDAI-1120)."""

    def __init__(self, host: str):
        """Initialize the TDAI-2210 client."""
        self._audio_inputs = {}
        self._video_inputs = {}
        self._stream_types = TDAI2210_STREAM_TYPES
        super().__init__(host, LyngdorfModel.TDAI_2210)


class TDAI3400Receiver(TDAIReceiverBase):
    """Lyngdorf TDAI-3400 receiver client."""

    def __init__(self, host: str):
        """Initialize the TDAI-3400 client."""
        self._audio_inputs = {}  # TDAI-3400 uses dynamic source list
        self._video_inputs = {}  # TDAI-3400 has no video inputs
        self._stream_types = TDAI3400_STREAM_TYPES
        super().__init__(host, LyngdorfModel.TDAI_3400)


class P100Receiver(PReceiver):
    """Steinway Lyngdorf P100 receiver client."""

    def __init__(self, host: str):
        """Initialize the P100 client."""
        self._audio_inputs = P_AUDIO_INPUTS
        self._video_inputs = P100_VIDEO_INPUTS
        super().__init__(host, LyngdorfModel.P_100)


class P200Receiver(PReceiver):
    """Steinway Lyngdorf P200 receiver client."""

    def __init__(self, host: str):
        """Initialize the P200 client."""
        self._audio_inputs = P_AUDIO_INPUTS
        self._video_inputs = P_VIDEO_INPUTS
        super().__init__(host, LyngdorfModel.P_200)


class P300Receiver(PReceiver):
    """Steinway Lyngdorf P300 receiver client."""

    def __init__(self, host: str):
        """Initialize the P300 client."""
        self._audio_inputs = P_AUDIO_INPUTS
        self._video_inputs = P_VIDEO_INPUTS
        super().__init__(host, LyngdorfModel.P_300)


async def async_create_receiver(
    host: str, model: LyngdorfModel | None = None
) -> Receiver | None:
    if not model:
        model = await async_find_receiver_model(host)
        if not model:
            raise NotImplementedError("Unknown Receiver")
    if model == LyngdorfModel.MP_40:
        return MP40Receiver(host)
    if model == LyngdorfModel.MP_50:
        return MP50Receiver(host)
    if model == LyngdorfModel.MP_60:
        return MP60Receiver(host)
    if model == LyngdorfModel.TDAI_1120:
        return TDAI1120Receiver(host)
    if model == LyngdorfModel.TDAI_2170:
        return TDAI2170Receiver(host)
    if model == LyngdorfModel.TDAI_2210:
        return TDAI2210Receiver(host)
    if model == LyngdorfModel.TDAI_3400:
        return TDAI3400Receiver(host)
    if model == LyngdorfModel.P_100:
        return P100Receiver(host)
    if model == LyngdorfModel.P_200:
        return P200Receiver(host)
    if model == LyngdorfModel.P_300:
        return P300Receiver(host)
    raise NotImplementedError("Unknown Receiver")


async def async_find_receiver_model(
    host: str, timeout: float = 5.0
) -> LyngdorfModel | None:
    """Probe a Lyngdorf device for its model over TCP :84.

    Returns the matching LyngdorfModel, or None if the reply doesn't
    identify a supported model.

    Raises:
        TimeoutError: connection or read timed out.
        OSError: TCP connection failed (refused, unreachable, etc.).
    """
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, DEFAULT_LYNGDORF_PORT), timeout=timeout
        )
        writer.write(b"!DEVICE?\r")
        await writer.drain()
        buf = await asyncio.wait_for(reader.readuntil(b"\r"), timeout=timeout)
        message = buf.decode("utf-8")
        message = message[1:]  # strip leading '!'
        if 1 < message.find("(") < message.find(")"):
            model_name = message[1 + message.find("(") : message.find(")")]
            model = lookup_receiver_model(model_name)
            if model:
                return model
            _LOGGER.warning(
                "Model %s found at %s but is not supported", model_name, host
            )
        else:
            _LOGGER.warning(
                "Unexpected DEVICE reply from %s: %r", host, message.strip()
            )
    except asyncio.IncompleteReadError:
        _LOGGER.warning("Connection to %s closed before a complete reply", host)
    finally:
        if writer:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
    return None


async def async_get_device_serial(host: str, timeout: float = 5.0) -> str | None:
    """Get the serial number of a Lyngdorf device via unicast SSDP discovery.

    Sends a unicast SSDP M-SEARCH to the device, then fetches the UPnP
    device description XML to extract the serial number.

    Args:
        host: The IP address or hostname of the device.
        timeout: Timeout in seconds for each network operation.

    Returns:
        The serial number string, or None if it could not be determined.
    """
    import socket
    from xml.etree import ElementTree

    location = None

    # Step 1: Unicast SSDP M-SEARCH to get the Location header
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 3\r\n"
        "ST: urn:schemas-upnp-org:device:MediaRenderer:2\r\n"
        "\r\n"
    )

    loop = asyncio.get_running_loop()

    def _ssdp_search() -> str | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        try:
            sock.sendto(msg.encode(), (host, 1900))
            data, _ = sock.recvfrom(4096)
            response = data.decode(errors="replace")
            for line in response.splitlines():
                if line.lower().startswith("location:"):
                    return line.split(":", 1)[1].strip()
        except (OSError, TimeoutError):
            pass
        finally:
            sock.close()
        return None

    try:
        location = await asyncio.wait_for(
            loop.run_in_executor(None, _ssdp_search),
            timeout=timeout + 1,
        )
    except (TimeoutError, OSError):
        _LOGGER.debug("SSDP search to %s failed", host)
        return None

    if not location:
        _LOGGER.debug("No SSDP location found for %s", host)
        return None

    # Step 2: Fetch the UPnP device description XML
    import http.client
    from urllib.parse import urlparse

    def _fetch_xml() -> str | None:
        parsed = urlparse(location)
        if not parsed.hostname:
            return None
        try:
            conn = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=timeout
            )
            conn.request("GET", parsed.path)
            resp = conn.getresponse()
            if resp.status == 200:
                return resp.read().decode(errors="replace")
        except (OSError, TimeoutError):
            pass
        finally:
            conn.close()
        return None

    try:
        xml_text = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_xml),
            timeout=timeout + 1,
        )
    except (TimeoutError, OSError):
        _LOGGER.debug("Failed to fetch UPnP description from %s", location)
        return None

    if not xml_text:
        return None

    # Step 3: Parse serial number from XML
    try:
        root = ElementTree.fromstring(xml_text)
        ns = {"d": "urn:schemas-upnp-org:device-1-0"}
        serial_el = root.find(".//d:device/d:serialNumber", ns)
        if serial_el is not None and serial_el.text:
            return serial_el.text.strip().lower()
    except ElementTree.ParseError:
        _LOGGER.debug("Failed to parse UPnP XML from %s", location)

    return None


def lookup_receiver_model(model_name: str) -> LyngdorfModel | None:
    """Look up a LyngdorfModel by its model string identifier.

    Args:
        model_name: The model identifier string (e.g., "mp-60", "tdai-1120").

    Returns:
        The matching LyngdorfModel, or None if not found.
    """
    for model in LyngdorfModel:
        if model.model_name.casefold() == model_name.casefold():
            return model
    return None
