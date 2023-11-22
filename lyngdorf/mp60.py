import logging
import traceback
import asyncio
from attr import field, validators
from typing import Union, Callable, List
from .api import LyngdorfApi
from .base import CountingNumberDict
from .const import POWER_ON, MP60_STREAM_TYPES, MP60_VIDEO_INPUTS, MP60_AUDIO_INPUTS
from .exceptions import LyngdorfInvalidValueError

_LOGGER = logging.getLogger(__package__)


def convert_volume(value: Union[float, str]) -> float:
    """Convert volume to float."""
    return float(value) / 10.0


# @s(auto_attribs=True, init=False)
class LyngdorfMP60Client:
    """Lyngdorf client class."""

    _api: LyngdorfApi
    _notification_callbacks: List = list()

    _name: str
    _volume: float = field(validator=[validators.ge(-99.9), validators.lt(10.0)])
    _zone_b_volume: float = field(validator=[validators.ge(-99.9), validators.lt(10.0)])
    _mute_enabled: bool
    _zone_b_mute_enabled: bool
    _sources = CountingNumberDict()
    _sound_modes = CountingNumberDict()
    _source: str = None
    _audio_input: str = None
    _video_input: str = None
    _video_info: str = None
    _streaming_source: str = None
    _zone_b_streaming_source: str = None
    _power_on: bool
    _zone_b_power_on: bool

    def __init__(self, host: str):
        """Initialize the client."""
        self._api: LyngdorfApi = LyngdorfApi(host)

    async def async_connect(self):
        # Basics
        self._api.register_callback("DEVICE", self._name_callback)

        # Volumes and Mutes
        self._api.register_callback("VOL", self._volume_callback)
        self._api.register_callback("ZVOL", self._zone_b_volume_callback)
        self._api.register_callback("MUTEON", self._mute_on_callback)
        self._api.register_callback("MUTEOFF", self._mute_off_callback)
        self._api.register_callback("ZMUTEON", self._zone_b_mute_on_callback)
        self._api.register_callback("ZMUTEOFF", self._zone_b_mute_off_callback)

        # Sources
        self._api.register_callback("SRCCOUNT", self._sources.count_callback)
        self._api.register_callback("SRC", self._source_callback)
        self._api.register_callback("AUDIN", self._audio_input_callback)
        self._api.register_callback("VIDIN", self._video_input_callback)
        self._api.register_callback("STREAMTYPE", self._stream_type_callback)
        self._api.register_callback("ZSTREAMTYPE", self._zone_b_stream_type_callback)
        self._api.register_callback("VIDTYPE", self._video_info_callback)
        self._api.register_callback("AUDMODECOUNT", self._sound_modes.count_callback)
        self._api.register_callback("AUDMODE", self._sound_mode_callback)

        # Power
        self._api.register_callback("POWER", self._power_callback)
        self._api.register_callback("POWERZONE2", self._zone_b_power_callback)

        await self._api.async_connect()

    async def async_disconnect(self):
        await self._api.async_disconnect()

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
            except Exception as err:
                # TIM. TODO. need to log the stack trace of the error found here, as at the moment v hard to find errors

                _LOGGER.error(
                    "Event callback caused an unhandled exception  (%s)",
                    traceback.format_exc(),
                )

    # Basics

    def _name_callback(self, param1: str, param2: str) -> None:
        self._name = param1

    @property
    def name(self):
        return self._name

    # Volumes

    def _volume_callback(self, param1: str, ignored: str) -> None:
        self._volume = convert_volume(param1)
        self._notify_notification_callbacks()

    def _zone_b_volume_callback(self, param1: str, ignored: str) -> None:
        self._zone_b_volume = convert_volume(param1)
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
    def volume(self, value):
        self._api.volume(value)

    @property
    def zone_b_volume(self):
        return self._zone_b_volume

    @zone_b_volume.setter
    def zone_b_volume(self, value):
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

    @property
    def available_sources(self):
        return list(self._sources.values())

    @property
    def audio_input(self):
        return self._audio_input

    def _audio_input_callback(self, param1: str, param2: str):
        self._audio_input = MP60_AUDIO_INPUTS[int(param1)]
        self._notify_notification_callbacks()

    @property
    def video_input(self):
        return self._video_input

    def _video_input_callback(self, param1: str, param2: str):
        self._video_input = MP60_VIDEO_INPUTS[int(param1)]
        self._notify_notification_callbacks()

    @property
    def streaming_source(self):
        return self._streaming_source

    @property
    def zone_b_streaming_source(self):
        return self._zone_b_streaming_source

    def _stream_type_callback(self, param1: str, param2: str):
        self._streaming_source = MP60_STREAM_TYPES[int(param1)]
        self._notify_notification_callbacks()

    def _zone_b_stream_type_callback(self, param1: str, param2: str):
        self._zone_b_streaming_source = MP60_STREAM_TYPES[int(param1)]
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
    def available_sound_modes(self):
        return list(self._sound_modes.values())

    def _power_callback(self, param1: str, param2: str):
        self._power_on = POWER_ON == param1
        self._notify_notification_callbacks()

    def _zone_b_power_callback(self, param1: str, param2: str):
        self._zone_b_power_on = POWER_ON == param1
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
