"""
Lyngdorf Audio Control Library.

Python library to control Lyngdorf A/V processors and integrated amplifiers.

Supported Models:
- MP-40, MP-50, MP-60 (Multichannel Processors)
- TDAI-1120, TDAI-2170, TDAI-3400 (Integrated Amplifiers)

Example:
    >>> from lyngdorf import async_create_receiver, LyngdorfModel
    >>> receiver = await async_create_receiver("192.168.1.100")
    >>> await receiver.async_connect()
    >>> receiver.power_on(True)
    >>> receiver.volume = -25.0
"""

from .const import LyngdorfModel, supported_models
from .device import (
    MP40Receiver,
    MP50Receiver,
    MP60Receiver,
    Receiver,
    TDAI1120Receiver,
    TDAI2170Receiver,
    TDAI3400Receiver,
    async_create_receiver,
    async_find_receiver_model,
)

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
    "async_create_receiver",
    "async_find_receiver_model",
]

__version__ = "0.7.0"
