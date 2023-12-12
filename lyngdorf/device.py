import logging
import traceback
import asyncio
import socket
from attr import field, validators
from typing import Union, Callable, List
from .api import LyngdorfApi
from .base import CountingNumberDict
from .const import POWER_ON, LyngdorfModel, Msg, DEFAULT_LYNGDORF_PORT
from .exceptions import LyngdorfInvalidValueError

_LOGGER = logging.getLogger(__package__)


def convert_decibel(value: Union[float, str]) -> float:
    """Convert volume to float."""
    return float(value) / 10.0


class Receiver:
    """Lyngdorf client class."""

    _api: LyngdorfApi
    _model: LyngdorfModel = None
    _host: str = None
    
    _stream_types=dict()
    _audio_inputs=dict()
    _video_inputs=dict()
    
    _notification_callbacks: List = list()

    _name: str = None
    _volume: float = field(validator=[validators.ge(-99.9), validators.lt(10.0)],default=None)
    _zone_b_volume: float = field(validator=[validators.ge(-99.9), validators.lt(10.0)],default=None)
    _mute_enabled: bool = None
    _zone_b_mute_enabled: bool = None
    _sources = CountingNumberDict()
    _source: str = None
    _zone_b_sources = CountingNumberDict()
    _zone_b_source: str = None
    _sound_modes = CountingNumberDict()
    _sound_mode: str = None
    _audio_input: str = None
    _zone_b_audio_input: str = None
    _video_input: str = None
    _audio_info: str = None
    _video_info: str = None
    _streaming_source: str = None
    _zone_b_streaming_source: str = None
    _zone_b_audio_info: str = None
    _power_on: bool = None
    _zone_b_power_on: bool = None
    
    # Trims
    _trim_bass: float = field(validator=[validators.ge(-12.0), validators.lt(12.0)],default=None)
    _trim_centre: float = field(validator=[validators.ge(-10.0), validators.lt(10.0)],default=None)
    _trim_height: float = field(validator=[validators.ge(-10.0), validators.lt(10.0)],default=None)
    _trim_lfe: float = field(validator=[validators.ge(-10.0), validators.lt(10.0)],default=None)
    _trim_surround: float = field(validator=[validators.ge(-10.0), validators.lt(10.0)],default=None)
    _trim_treble: float = field(validator=[validators.ge(-12.0), validators.lt(12.0)],default=None)
    
    
    # Audio Tuning
    _room_perfect_positions = CountingNumberDict()
    _room_perfect_position: str = None
    _voicings = CountingNumberDict()
    _voicing: str = None
    _lipsync: int = None

    def __init__(self, host: str, model: LyngdorfModel):
        """Initialize the client."""
        self._host=host
        self._model=model
        assert model
        assert host
        self._api: LyngdorfApi = LyngdorfApi(host, model)

    async def async_connect(self):
        # Basics
        self._api.register_callback(self.lookup_command(Msg.DEVICE), self._name_callback)

        # Volumes and Mutes
        self._api.register_callback(self.lookup_command(Msg.VOLUME), self._volume_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_VOLUME), self._zone_b_volume_callback)
        self._api.register_callback(self.lookup_command(Msg.MUTE_ON), self._mute_on_callback)
        self._api.register_callback(self.lookup_command(Msg.MUTE_OFF), self._mute_off_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_MUTE_ON), self._zone_b_mute_on_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_MUTE_OFF), self._zone_b_mute_off_callback)

        # Sources
        self._api.register_callback(self.lookup_command(Msg.SOURCES_COUNT), self._sources.count_callback)
        self._api.register_callback(self.lookup_command(Msg.SOURCE), self._source_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_SOURCES_COUNT), self._zone_b_sources.count_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_SOURCE), self._zone_b_source_callback)
        self._api.register_callback(self.lookup_command(Msg.AUDIO_IN), self._audio_input_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_AUDIO_IN), self._zone_b_audio_input_callback)
        self._api.register_callback(self.lookup_command(Msg.VIDEO_IN), self._video_input_callback)
        self._api.register_callback(self.lookup_command(Msg.STREAM_TYPE), self._stream_type_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_STREAM_TYPE), self._zone_b_stream_type_callback)
        self._api.register_callback(self.lookup_command(Msg.VIDEO_TYPE), self._video_info_callback)
        self._api.register_callback(self.lookup_command(Msg.AUDIO_TYPE), self._audio_info_callback)

        self._api.register_callback(self.lookup_command(Msg.AUDIO_MODES_COUNT), self._sound_modes.count_callback)
        self._api.register_callback(self.lookup_command(Msg.AUDIO_MODE), self._sound_mode_callback)

        # Power
        self._api.register_callback(self.lookup_command(Msg.POWER), self._power_callback)
        self._api.register_callback(self.lookup_command(Msg.ZONE_B_POWER), self._zone_b_power_callback)
        
        # Audio Tuning
        self._api.register_callback(self.lookup_command(Msg.ROOM_PERFECT_POSITIONS_COUNT), self._room_perfect_positions.count_callback)
        self._api.register_callback(self.lookup_command(Msg.ROOM_PERFECT_POSITION), self._room_perfect_position_callback)
        self._api.register_callback(self.lookup_command(Msg.ROOM_PERFECT_VOICINGS_COUNT), self._voicings.count_callback)
        self._api.register_callback(self.lookup_command(Msg.ROOM_PERFECT_VOICING), self._voicing_callback)
        self._api.register_callback(self.lookup_command(Msg.LIP_SYNC), self._lipsync_callback)
        
        # Trim
        self._api.register_callback(self.lookup_command(Msg.TRIM_BASS), self._trim_bass_callback)
        self._api.register_callback(self.lookup_command(Msg.TRIM_CENTRE), self._trim_centre_callback)
        self._api.register_callback(self.lookup_command(Msg.TRIM_HEIGHT), self._trim_height_callback)
        self._api.register_callback(self.lookup_command(Msg.TRIM_LFE), self._trim_lfe_callback)
        self._api.register_callback(self.lookup_command(Msg.TRIM_SURROUND), self._trim_surround_callback)
        self._api.register_callback(self.lookup_command(Msg.TRIM_TREBLE), self._trim_treble_callback)

        
        
        await self._api.async_connect()

    async def async_disconnect(self):
        await self._api.async_disconnect()
        
    def lookup_command(self, key: Msg):
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
    
    @property
    def host(self) -> str:
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
                "%s is not a valid zone b source name, and cannot be chosen", zone_b_source
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
            self._audio_input =f'audio-{param1}'
            _LOGGER.warning(f'audio_input({param1} is not known, so ignoring)')
        self._notify_notification_callbacks()


    @property
    def zone_b_audio_input(self):
        return self._zone_b_audio_input

    def _zone_b_audio_input_callback(self, param1: str, param2: str):
        if int(param1) in self._audio_inputs:
            self._zone_b_audio_input = self._audio_inputs[int(param1)]
        else:
            self._zone_b_audio_input =f'audio-{param1}'
            _LOGGER.warning(f'zone_b_audio_input({param1}) is not known, so ignoring')
        self._notify_notification_callbacks()

    @property
    def video_input(self):
        return self._video_input

    def _video_input_callback(self, param1: str, param2: str):
        if int(param1) in self._video_inputs:
            self._video_input = self._video_inputs[int(param1)]
        else:
            self._video_input =f'video-{param1}'
            _LOGGER.warning(f'zone_b_audio_input({param1}) is not known, so ignoring')
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
            self._streaming_source =f'video-{param1}'
            _LOGGER.warning(f'stream_type({param1}) is not known, so ignoring')
        self._notify_notification_callbacks()

    def _zone_b_stream_type_callback(self, param1: str, param2: str):
        if int(param1) in self._stream_types:
            self._zone_b_streaming_source = self._stream_types[int(param1)]
        else:
            self._zone_b_streaming_source =f'video-{param1}'
            _LOGGER.warning(f'zone_b_stream_type({param1}) is not known, so ignoring')
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
        
    # Audio Tuning
    def _room_perfect_position_callback(self, param1: str, param2: str):
        if self._room_perfect_positions.is_full():
            self._room_perfect_position = param2
            self._notify_notification_callbacks()
        else:
            self._room_perfect_positions.add(int(param1), param2)
            
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
                "%s is not a valid room_perfect_position name, and cannot be chosen", room_perfect_position
            )
            
    def _voicing_callback(self, param1: str, param2: str):
        if self._voicings.is_full():
            self._voicing = param2
            self._notify_notification_callbacks()
        else:
            self._voicings.add(int(param1), param2)
    
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
        self._lipsync=int(param1)
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
        
        
        
        
from .const import MP60_AUDIO_INPUTS, MP60_VIDEO_INPUTS, MP60_STREAM_TYPES       
class MP60Receiver(Receiver):

    def __init__(self, host: str):
        """Initialize the client."""
        self._audio_inputs=MP60_AUDIO_INPUTS
        self._video_inputs=MP60_VIDEO_INPUTS
        self._stream_types=MP60_STREAM_TYPES
        super().__init__(host, LyngdorfModel.MP_60)
    
def create_receiver(host: str, model: LyngdorfModel=None, ) -> Receiver: 
    if not (model):
        try:
            model = find_receiver_model(host)
        except:
            return None
        if not (model):
            raise NotImplementedError("Unknown Receiver")    
    if (model == LyngdorfModel.MP_60):
        return MP60Receiver(host)
    raise NotImplementedError("Unknown Receiver")

def find_receiver_model(host: str) -> LyngdorfModel: 
    sock: socket=None
    try:
        modelName:str=None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, DEFAULT_LYNGDORF_PORT))
        sock.sendall("!DEVICE?\r".encode("utf-8"))
        buf=sock.recv(20)
        message=buf.decode("utf-8")
        try:
            sock.close()
        except:
            pass
        message = message[1:]
        if 1 < message.find("(") < message.find(")"):
            cmd = message[: message.find("(")]
            modelName = message[1 + message.find("(") : message.find(")")]
            model: LyngdorfModel=lookup_receiver_model(modelName)
            if (model):
                return model
            _LOGGER.warn(f'model {modelName} receiver found at {host}, but we cannot use it as it is not implemented')
    except socket.error as exc:
        _LOGGER.warn(f'Attempting to connect with {host}, but we we failed {exc}')
        if (sock):
            try:
                sock.close()
            except:
                pass
        return None
    return None

def lookup_receiver_model(modelName: str) -> LyngdorfModel:  
    for model in LyngdorfModel:
        if (model.model.casefold() == modelName.casefold()):
            return model
    return None