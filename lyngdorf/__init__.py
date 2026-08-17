"""
Lyngdorf Audio Control Library.

Python library to control Lyngdorf A/V processors and integrated amplifiers.

Supported Models:
- MP-40, MP-50, MP-60 (Multichannel Processors)
- TDAI-1120, TDAI-2170, TDAI-3400 (Integrated Amplifiers)
- P100, P200, P300 (Multichannel Processors)

Example:
    >>> from lyngdorf import async_create_receiver, LyngdorfModel
    >>> receiver = await async_create_receiver("192.168.1.100")
    >>> await receiver.async_connect()
    >>> receiver.power_on(True)
    >>> receiver.volume = -25.0
"""

from importlib.metadata import PackageNotFoundError, version

from .const import LyngdorfModel, supported_models
from .device import (
    MP40Receiver,
    MP50Receiver,
    MP60Receiver,
    P100Receiver,
    P200Receiver,
    P300Receiver,
    Receiver,
    TDAI1120Receiver,
    TDAI2170Receiver,
    TDAI3400Receiver,
    async_create_receiver,
    async_find_receiver_model,
    async_get_device_serial,
)
from .states import Control, PlaybackState, PlayMode, Repeat
from .streaming import NowPlaying

__all__ = [
    "LyngdorfModel",
    "supported_models",
    "Receiver",
    "MP40Receiver",
    "MP50Receiver",
    "MP60Receiver",
    "TDAI1120Receiver",
    "TDAI2170Receiver",
    "TDAI3400Receiver",
    "P100Receiver",
    "P200Receiver",
    "P300Receiver",
    "async_create_receiver",
    "async_find_receiver_model",
    "async_get_device_serial",
    "NowPlaying",
    "Control",
    "PlaybackState",
    "PlayMode",
    "Repeat",
]

try:
    __version__ = version("lyngdorf")
except PackageNotFoundError:
    # Package not installed (e.g. running from a checkout without `poetry install`)
    __version__ = "0.0.0"
