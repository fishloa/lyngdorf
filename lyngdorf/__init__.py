"""Lyngdorf Audio Control Library - control Lyngdorf A/V processors and
integrated amplifiers over IP.

Usage against the 2.0 surface:
    from lyngdorf import async_create_receiver, LyngdorfModel
    receiver = await async_create_receiver("192.168.1.50", LyngdorfModel.MP_60)
    await receiver.connect()
    await receiver.volume.set(-25.0)
"""

import warnings
from importlib.metadata import PackageNotFoundError, version

from .components import Player, Remote, ZoneB

# Force const to load first (before components/controls/models chain)
# so its bottom-of-file imports from .models complete before models
# imports from it. See WP4 task 5 circular-import note.
from .const import Msg  # noqa: F401
from .controls import NumericControl, SteppableControl, Trim
from .device import (
    async_create_receiver,
    async_find_receiver_model,
    async_get_device_serial,
)
from .exceptions import (
    LyngdorfError,
    LyngdorfInvalidValueError,
    LyngdorfUnsupportedError,
)
from .models import LyngdorfModel, NumericRange
from .receiver import LyngdorfReceiver
from .remote import RemoteKey
from .states import Control, PlaybackState, PlayMode, Repeat
from .streaming import NowPlaying

__all__ = [
    "LyngdorfReceiver",
    "NumericControl",
    "SteppableControl",
    "Trim",
    "ZoneB",
    "Player",
    "Remote",
    "LyngdorfModel",
    "NumericRange",
    "NowPlaying",
    "Control",
    "PlaybackState",
    "PlayMode",
    "Repeat",
    "RemoteKey",
    "LyngdorfError",
    "LyngdorfInvalidValueError",
    "LyngdorfUnsupportedError",
    # 1.x module-level names, renamed by WP5 (which ships their shims):
    "async_create_receiver",
    "async_find_receiver_model",
    "async_get_device_serial",
]


def __getattr__(name: str) -> object:
    # D9 module-level shims - deleted in 2.1 with _compat.py.
    if name == "Receiver":
        warnings.warn(
            "Receiver is deprecated and will be removed in lyngdorf 2.1; "
            "use LyngdorfReceiver",
            DeprecationWarning,
            stacklevel=2,
        )
        return LyngdorfReceiver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


try:
    __version__ = version("lyngdorf")
except PackageNotFoundError:
    __version__ = "0.0.0"
