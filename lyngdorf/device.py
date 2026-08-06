"""
Lyngdorf Audio Control Library - Device Module.

Main receiver classes and factory functions for all supported models.

Supported Models:
- MP-40, MP-50, MP-60 (Multichannel Processors)
- TDAI-1120, TDAI-2170, TDAI-3400 (Integrated Amplifiers)
- P100, P200, P300 (Multichannel Processors)

All communication via TCP/IP on port 84 (no serial port support).
"""

import asyncio
import logging
from collections.abc import Callable

from .api import LyngdorfApi
from .base import CountingNumberDict
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
    TDAI3400_STREAM_TYPES,
    LyngdorfModel,
    Msg,
)
from .exceptions import LyngdorfInvalidValueError

_LOGGER = logging.getLogger(__package__)


def convert_decibel(value: float | str) -> float:
    """Convert volume to float."""
    return float(value) / 10.0


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
        self._trim_bass: float | None = None
        self._trim_centre: float | None = None
        self._trim_height: float | None = None
        self._trim_lfe: float | None = None
        self._trim_surround: float | None = None
        self._trim_treble: float | None = None

    def _register_callback(self, msg: Msg, callback: Callable) -> None:
        """Register a callback for a message, skipping cleanly if the
        connected model's protocol doesn't define that message.

        Model capability flags (has_zone_b_feature, has_video_feature,
        has_surround_feature) are the primary gate for the messages we know
        are model-specific. This catch is a safety net for any message a
        model doesn't support that isn't covered by those flags - so an
        unexpected protocol gap degrades a single feature instead of
        breaking connection setup entirely.
        """
        try:
            command = self.lookup_command(msg)
        except KeyError:
            _LOGGER.warning(
                "Model %s does not support message %s; skipping callback registration",
                self._model,
                msg,
            )
            return
        self._api.register_callback(command, callback)

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

    async def async_connect(self):
        # Basics
        self._register_callback(Msg.DEVICE, self._name_callback)

        # Volumes and Mutes
        self._register_callback(Msg.VOLUME, self._volume_callback)
        if self._model.has_mute_state_in_parameter():
            # TDAI family: state arrives as `!MUTE(ON)` / `!MUTE(OFF)`
            self._register_callback(Msg.MUTE, self._mute_callback)
        else:
            # MP and P families: distinct `!MUTEON` / `!MUTEOFF` messages
            self._register_callback(Msg.MUTE_ON, self._mute_on_callback)
            self._register_callback(Msg.MUTE_OFF, self._mute_off_callback)

        # Sources
        self._register_callback(Msg.SOURCES_COUNT, self._sources.count_callback)
        # Some models can't populate source names the default way:
        # TDAI-1120/3400 carry the name under a differently-shaped SRCNAME
        # message instead of the source-query reply; TDAI-2170 has a fixed
        # hardware source list gated by a SRCENABLED bitmask rather than
        # any enumeration burst at all.
        if self._model.supports_message(Msg.SOURCE_NAME):
            self._register_callback(Msg.SOURCE_NAME, self._source_name_callback)
        elif self._model.supports_message(Msg.SOURCES_ENABLED):
            self._register_callback(Msg.SOURCES_ENABLED, self._sources_enabled_callback)
            self._register_callback(Msg.SOURCE, self._fixed_source_callback)
        else:
            self._register_callback(Msg.SOURCE, self._source_callback)
        self._register_callback(Msg.STREAM_TYPE, self._stream_type_callback)

        # Power
        self._register_callback(Msg.POWER, self._power_callback)

        # Video routing - only models with video inputs/outputs
        if self._model.has_video_feature():
            self._register_callback(Msg.AUDIO_IN, self._audio_input_callback)
            self._register_callback(Msg.VIDEO_IN, self._video_input_callback)
            self._register_callback(Msg.VIDEO_TYPE, self._video_info_callback)

        # Zone B (Zone 2) - only models with Zone B support these messages
        if self._model.has_zone_b_feature():
            self._register_callback(Msg.ZONE_B_VOLUME, self._zone_b_volume_callback)
            self._register_callback(Msg.ZONE_B_MUTE_ON, self._zone_b_mute_on_callback)
            self._register_callback(Msg.ZONE_B_MUTE_OFF, self._zone_b_mute_off_callback)
            self._register_callback(
                Msg.ZONE_B_SOURCES_COUNT, self._zone_b_sources.count_callback
            )
            self._register_callback(Msg.ZONE_B_SOURCE, self._zone_b_source_callback)
            self._register_callback(
                Msg.ZONE_B_AUDIO_IN, self._zone_b_audio_input_callback
            )
            self._register_callback(
                Msg.ZONE_B_STREAM_TYPE, self._zone_b_stream_type_callback
            )
            self._register_callback(Msg.ZONE_B_POWER, self._zone_b_power_callback)

        # Audio Tuning
        self._register_callback(
            Msg.ROOM_PERFECT_POSITIONS_COUNT,
            self._room_perfect_positions.count_callback,
        )
        # TDAI-2170 has a fixed set of RoomPerfect positions gated by an
        # RPSTATUS bitmask rather than an RPLIST/RPFOCS enumeration burst.
        if self._model.supports_message(Msg.ROOM_PERFECT_POSITIONS_PRESENT):
            self._register_callback(
                Msg.ROOM_PERFECT_POSITIONS_PRESENT,
                self._room_perfect_positions_present_callback,
            )
            self._register_callback(
                Msg.ROOM_PERFECT_POSITION,
                self._fixed_room_perfect_position_callback,
            )
        else:
            self._register_callback(
                Msg.ROOM_PERFECT_POSITION, self._room_perfect_position_callback
            )
        self._register_callback(
            Msg.ROOM_PERFECT_VOICINGS_COUNT, self._voicings.count_callback
        )
        # Same story for voicings: TDAI-2170 gates a fixed list with
        # VOIENABLED rather than a VOILIST/RPVOIS burst.
        if self._model.supports_message(Msg.ROOM_PERFECT_VOICINGS_ENABLED):
            self._register_callback(
                Msg.ROOM_PERFECT_VOICINGS_ENABLED, self._voicings_enabled_callback
            )
            self._register_callback(
                Msg.ROOM_PERFECT_VOICING, self._fixed_voicing_callback
            )
        else:
            self._register_callback(Msg.ROOM_PERFECT_VOICING, self._voicing_callback)

        # Trim and audio modes - not every model has these (the defensive
        # catch in _register_callback logs and skips whichever don't apply)
        self._register_callback(Msg.TRIM_BASS, self._trim_bass_callback)
        self._register_callback(Msg.TRIM_TREBLE, self._trim_treble_callback)
        self._register_callback(Msg.AUDIO_TYPE, self._audio_info_callback)
        self._register_callback(Msg.AUDIO_MODES_COUNT, self._sound_modes.count_callback)
        self._register_callback(Msg.AUDIO_MODE, self._sound_mode_callback)
        self._register_callback(Msg.LIP_SYNC, self._lipsync_callback)

        # Discrete channel trims - only models with multichannel speaker trims
        if self._model.has_surround_feature():
            self._register_callback(Msg.TRIM_CENTRE, self._trim_centre_callback)
            self._register_callback(Msg.TRIM_HEIGHT, self._trim_height_callback)
            self._register_callback(Msg.TRIM_LFE, self._trim_lfe_callback)
            self._register_callback(Msg.TRIM_SURROUND, self._trim_surround_callback)

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
    def register_notification_callback(self, callback: Callable[[], None]) -> None:
        self._notification_callbacks.append(callback)

    def un_register_notification_callback(self, callback: Callable[[], None]) -> None:
        self._notification_callbacks.remove(callback)

    def _notify_notification_callbacks(self) -> None:
        asyncio.create_task(self._async_notify_notification_callbacks())

    async def _async_notify_notification_callbacks(self) -> None:
        for callback in self._notification_callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.exception("Event callback caused an unhandled exception")

    # Basics

    def _name_callback(self, param1: str, param2: str) -> None:
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
        self._notify_notification_callbacks()

    def _zone_b_power_callback(self, param1: str, param2: str):
        self._zone_b_power_on = self._model.power_state_on_value() == param1
        self._notify_notification_callbacks()

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

    def _lipsync_callback(self, param1: str, param2: str):
        self._lipsync = int(param1)
        self._notify_notification_callbacks()

    @property
    def lipsync(self):
        return self._lipsync

    @lipsync.setter
    def lipsync(self, lipsync: int):
        self._api.change_lipsync(lipsync)

    # trims
    def _trim_bass_callback(self, param1: str, ignored: str) -> None:
        self._trim_bass = convert_decibel(param1)
        self._notify_notification_callbacks()

    @property
    def trim_bass(self):
        return self._trim_bass

    @trim_bass.setter
    def trim_bass(self, trim: float):
        self._api.change_trim_bass(trim)

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
        self._api.change_trim_centre(trim)

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
        self._api.change_trim_height(trim)

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
        self._api.change_trim_lfe(trim)

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
        self._api.change_trim_surround(trim)

    def trim_surround_up(self):
        self._api.trim_surround_up()

    def trim_surround_down(self):
        self._api.trim_surround_down()

    def _trim_treble_callback(self, param1: str, ignored: str) -> None:
        self._trim_treble = convert_decibel(param1)
        self._notify_notification_callbacks()

    @property
    def trim_treble(self):
        return self._trim_treble

    @trim_treble.setter
    def trim_treble(self, trim: float):
        self._api.change_trim_treble(trim)

    def trim_treble_up(self):
        self._api.trim_treble_up()

    def trim_treble_down(self):
        self._api.trim_treble_down()


class MP40Receiver(Receiver):
    """Lyngdorf MP-40 receiver client."""

    def __init__(self, host: str):
        """Initialize the MP-40 client."""
        self._audio_inputs = MP40_AUDIO_INPUTS
        self._video_inputs = MP40_VIDEO_INPUTS
        self._stream_types = MP40_STREAM_TYPES
        super().__init__(host, LyngdorfModel.MP_40)


class MP50Receiver(Receiver):
    """Lyngdorf MP-50 receiver client."""

    def __init__(self, host: str):
        """Initialize the MP-50 client."""
        self._audio_inputs = MP50_AUDIO_INPUTS
        self._video_inputs = MP50_VIDEO_INPUTS
        self._video_outputs = MP50_VIDEO_OUTPUTS
        self._stream_types = MP50_STREAM_TYPES
        super().__init__(host, LyngdorfModel.MP_50)


class MP60Receiver(Receiver):

    def __init__(self, host: str):
        """Initialize the client."""
        self._audio_inputs = MP60_AUDIO_INPUTS
        self._video_inputs = MP60_VIDEO_INPUTS
        self._stream_types = MP60_STREAM_TYPES
        super().__init__(host, LyngdorfModel.MP_60)


class TDAI1120Receiver(Receiver):

    def __init__(self, host: str):
        """Initialize the client."""
        self._audio_inputs = {}  # TDAI-1120 uses dynamic source list
        self._video_inputs = {}  # TDAI-1120 has no video inputs
        self._stream_types = TDAI1120_STREAM_TYPES
        super().__init__(host, LyngdorfModel.TDAI_1120)


class TDAI2170Receiver(Receiver):
    """Lyngdorf TDAI-2170 receiver client."""

    def __init__(self, host: str):
        """Initialize the TDAI-2170 client."""
        self._audio_inputs = {}  # TDAI-2170 uses dynamic source list
        self._video_inputs = {}  # TDAI-2170 has no video inputs
        self._stream_types = TDAI2170_STREAM_TYPES
        super().__init__(host, LyngdorfModel.TDAI_2170)


class TDAI3400Receiver(Receiver):
    """Lyngdorf TDAI-3400 receiver client."""

    def __init__(self, host: str):
        """Initialize the TDAI-3400 client."""
        self._audio_inputs = {}  # TDAI-3400 uses dynamic source list
        self._video_inputs = {}  # TDAI-3400 has no video inputs
        self._stream_types = TDAI3400_STREAM_TYPES
        super().__init__(host, LyngdorfModel.TDAI_3400)


class P100Receiver(Receiver):
    """Steinway Lyngdorf P100 receiver client."""

    def __init__(self, host: str):
        """Initialize the P100 client."""
        self._audio_inputs = P_AUDIO_INPUTS
        self._video_inputs = P100_VIDEO_INPUTS
        super().__init__(host, LyngdorfModel.P_100)


class P200Receiver(Receiver):
    """Steinway Lyngdorf P200 receiver client."""

    def __init__(self, host: str):
        """Initialize the P200 client."""
        self._audio_inputs = P_AUDIO_INPUTS
        self._video_inputs = P_VIDEO_INPUTS
        super().__init__(host, LyngdorfModel.P_200)


class P300Receiver(Receiver):
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
        try:
            model = await async_find_receiver_model(host)
        except Exception:
            return None
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
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, DEFAULT_LYNGDORF_PORT), timeout=timeout
        )
        writer.write(b"!DEVICE?\r")
        await writer.drain()
        buf = await asyncio.wait_for(reader.read(20), timeout=timeout)
        message = buf.decode("utf-8")
        message = message[1:]
        if 1 < message.find("(") < message.find(")"):
            modelName = message[1 + message.find("(") : message.find(")")]
            model = lookup_receiver_model(modelName)
            if model:
                return model
            _LOGGER.warning(
                f"model {modelName} receiver found at {host}, but we cannot use it as it is not implemented"
            )
    except TimeoutError:
        _LOGGER.warning(f"Connection to {host} timed out")
    except OSError as exc:
        _LOGGER.warning(f"Attempting to connect with {host}, but we failed: {exc}")
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
