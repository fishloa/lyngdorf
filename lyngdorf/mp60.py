import logging
from attr import define, field, s, validators
from typing import Optional, Union
from .api import LyngdorfApi, LyngdorfProtocol
from .base import CountingNumberDict

_LOGGER = logging.getLogger(__package__)


def convert_volume(value: Union[float, str]) -> float:
    """Convert volume to float."""
    return float(value) / 10.0


@s(auto_attribs=True, init=False)
class LyngdorfMP60Client:
    """Lyngdorf client class."""

    _api: LyngdorfApi = field()
    _volume: float = field()  # validator=[validators.ge(-99.9), validators.lt(10.0) ])

    def __init__(self, host: str):
        """Initialize the client."""
        self._api: LyngdorfApi = LyngdorfApi(host)
        self._audio_sources = CountingNumberDict()
        self._audio_source: str = None
        self._volume = -99.9

    async def async_connect(self):
        self._api.register_callback("VOL", self.volume_callback)
        self._api.register_callback("SRCCOUNT", self._audio_sources.count_callback)
        self._api.register_callback("SRC", self.audio_source_callback)

        await self._api.async_connect()

    async def async_disconnect(self):
        await self._api.async_disconnect()

    def volume_callback(self, param1: str, ignored: str) -> None:
        self._volume = convert_volume(param1)

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        self._api.volume(value)

    @property
    def audio_source(self):
        return self._audio_source

    @audio_source.setter
    def audio_source(self, source: str):
        index = self._audio_sources.lookupIndex(source)
        if index > -1:
            self._api.change_source(index)
        else:
            _LOGGER.warning(source, " is not a valid source name, and cannot be chosen")

    def audio_source_callback(self, param1: str, param2: str):
        if self._audio_sources.is_full():
            self._audio_source = param2
        else:
            self._audio_sources.add(int(param1), param2)

    @property
    def available_sources(self):
        return self._audio_sources.values()
