"""Lyngdorf Audio Control Library — control Lyngdorf A/V processors and
integrated amplifiers over IP.

Usage against the 2.0 surface:
    from lyngdorf import create_receiver, LyngdorfModel
    receiver = await create_receiver("192.168.1.50", LyngdorfModel.MP_60)
    await receiver.connect()
    await receiver.volume.set(-25.0)
"""

from importlib.metadata import PackageNotFoundError, version

from .components import Player, Remote, ZoneB

# Force const to load first (before components/controls/models chain)
# so its bottom-of-file imports from .models complete before models
# imports from it. See WP4 task 5 circular-import note.
from .const import Msg  # noqa: F401
from .controls import NumericControl, SteppableControl, Trim
from .discovery import (
    create_receiver,
    discover_model,
    discover_ssdp_location,
    fetch_device_serial,
    lookup_model,
)
from .exceptions import (
    LyngdorfError,
    LyngdorfInvalidValueError,
    LyngdorfUnsupportedError,
    UnsupportedModelError,
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
    "UnsupportedModelError",
    "create_receiver",
    "discover_model",
    "lookup_model",
    "discover_ssdp_location",
    "fetch_device_serial",
]


try:
    __version__ = version("lyngdorf")
except PackageNotFoundError:
    __version__ = "0.0.0"
