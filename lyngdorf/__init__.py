"""Lyngdorf Audio Control Library — control Lyngdorf A/V processors and
integrated amplifiers over IP.

Usage against the 2.0 surface:
    from lyngdorf import create_receiver, LyngdorfModel
    receiver = await create_receiver("192.168.1.50", LyngdorfModel.MP_60)
    await receiver.connect()
    await receiver.volume.set(-25.0)
"""

import warnings
from importlib.metadata import PackageNotFoundError, version

from . import _compat
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


def __getattr__(name: str) -> object:
    """D9 module-level shims — deleted in 2.1 with _compat.py.

    PEP 562: this runs only when normal lookup fails, so the warning
    fires when a legacy name is first *resolved*. For
    `from lyngdorf import async_create_receiver` that is once, at the
    importing module's import — which is how CPython's own module
    deprecations behave, and enough for a consumer to find every site.
    """
    target = _MODULE_SHIM_TARGETS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(
        f"{name} is deprecated and will be removed in lyngdorf 2.1; "
        f"use {_compat.MODULE_SHIMS[name]}",
        DeprecationWarning,
        stacklevel=2,
    )
    return target


_MODULE_SHIM_TARGETS = {
    "Receiver": LyngdorfReceiver,
    "lookup_receiver_model": lookup_model,
    "async_create_receiver": create_receiver,
    "async_find_receiver_model": discover_model,
    "async_get_device_serial": _compat.legacy_get_device_serial,
}


try:
    __version__ = version("lyngdorf")
except PackageNotFoundError:
    __version__ = "0.0.0"
