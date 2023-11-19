import logging
from attr import define, field, s, validators
from typing import Optional, Union
from .api import LyngdorfApi, LyngdorfProtocol
from .base import CountingNumberDict
from .const import POWER_ON, POWER_OFF, MP60_STREAM_TYPES, MP60_VIDEO_INPUTS, MP60_AUDIO_INPUTS

_LOGGER = logging.getLogger(__package__)


def convert_volume(value: Union[float, str]) -> float:
    """Convert volume to float."""
    return float(value) / 10.0


# @s(auto_attribs=True, init=False)
class LyngdorfMP60Client:
    """Lyngdorf client class."""

    _api: LyngdorfApi
    _volume: float = field(validator=[validators.ge(-99.9), validators.lt(10.0) ])
    _zone_b_volume: float = field(validator=[validators.ge(-99.9), validators.lt(10.0) ])
    _mute_enabled: bool
    _zone_b_mute_enabled: bool
    _sources = CountingNumberDict()
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
        # Volumes and Mutes
        self._api.register_callback("VOL", self.volume_callback)
        self._api.register_callback("ZVOL", self.zone_b_volume_callback)
        self._api.register_callback("MUTEON", self.mute_on_callback)
        self._api.register_callback("MUTEOFF", self.mute_off_callback)
        self._api.register_callback("ZMUTEON", self.zone_b_mute_on_callback)
        self._api.register_callback("ZMUTEOFF", self.zone_b_mute_off_callback)
        
        # Sources
        self._api.register_callback("SRCCOUNT", self._sources.count_callback)
        self._api.register_callback("SRC", self.source_callback)
        self._api.register_callback("AUDIN", self.audio_input_callback)
        self._api.register_callback("VIDIN", self.video_input_callback)
        self._api.register_callback("STREAMTYPE", self.stream_type_callback)
        self._api.register_callback("ZSTREAMTYPE", self.zone_b_stream_type_callback)
        self._api.register_callback("VIDTYPE", self.video_info_callback)

        
        # Power
        self._api.register_callback("POWER", self.power_callback)
        self._api.register_callback("POWERZONE2", self.zone_b_power_callback)

        await self._api.async_connect()

    async def async_disconnect(self):
        await self._api.async_disconnect()

    def volume_callback(self, param1: str, ignored: str) -> None:
        self._volume = convert_volume(param1)
        
    def zone_b_volume_callback(self, param1: str, ignored: str) -> None:
        self._zone_b_volume = convert_volume(param1)
        
    def mute_on_callback(self, param1: str, param2: str):
        self._mute_enabled = True

    def mute_off_callback(self, param1: str, param2: str):
        self._mute_enabled = False

    def zone_b_mute_on_callback(self, param1: str, param2: str):
        self._zone_b_mute_enabled = True

    def zone_b_mute_off_callback(self, param1: str, param2: str):
        self._zone_b_mute_enabled = False

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        self._api.volume(value)
        
        
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
            _LOGGER.warning(source, " is not a valid source name, and cannot be chosen")

    def source_callback(self, param1: str, param2: str):
        if self._sources.is_full():
            self._source = param2
        else:
            self._sources.add(int(param1), param2)

    @property
    def available_sources(self):
        return self._sources.values()
    
    @property
    def audio_input(self):
        return self._audio_input
    
    def audio_input_callback(self, param1: str, param2: str):
        self._audio_input=MP60_AUDIO_INPUTS[int(param1)]
        
    @property
    def video_input(self):
        return self._video_input
    
    def video_input_callback(self, param1: str, param2: str):
        self._video_input=MP60_VIDEO_INPUTS[int(param1)]
        
    @property
    def streaming_source(self):
        return self._streaming_source
    
    @property
    def zone_b_streaming_source(self):
        return self._zone_b_streaming_source
    
    def stream_type_callback(self, param1: str, param2: str):
        self._streaming_source=MP60_STREAM_TYPES[int(param1)]
    
    def zone_b_stream_type_callback(self, param1: str, param2: str):
        self._zone_b_streaming_source=MP60_STREAM_TYPES[int(param1)]
        
    @property
    def video_information(self):
        return self._video_info
    
    def video_info_callback(self, param1: str, param2: str):
        self._video_info = param1
    
    def power_callback(self, param1: str, param2: str):
        self._power_on = POWER_ON == param1

    def zone_b_power_callback(self, param1: str, param2: str):
        self._zone_b_power_on = POWER_ON == param1
        
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