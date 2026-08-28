"""Deprecated 1.x import location — deleted in 2.1.

A package-level ``__getattr__`` (PEP 562) cannot rescue a submodule path:
``from lyngdorf.device import X`` resolves the submodule before the
package's ``__getattr__`` is ever consulted, so the only mechanism that
keeps such an import working is a real module. This is that module.

Everything here re-exports its 2.0 home. Import from ``lyngdorf``
directly instead; see MIGRATION.md.
"""

from __future__ import annotations

import warnings
from typing import Any

from .discovery import (
    create_receiver as _create_receiver,
)
from .discovery import (
    discover_model as _discover_model,
)
from .discovery import (
    discover_ssdp_location as _discover_ssdp_location,
)
from .discovery import (
    fetch_device_serial as _fetch_device_serial,
)
from .discovery import lookup_model as _lookup_model
from .models import LyngdorfModel
from .receiver import LyngdorfReceiver

warnings.warn(
    "lyngdorf.device is deprecated and will be removed in lyngdorf 2.1; "
    "import from lyngdorf directly",
    DeprecationWarning,
    stacklevel=2,
)

#: 1.x name for :class:`~lyngdorf.receiver.LyngdorfReceiver`.
Receiver = LyngdorfReceiver

#: 1.x name for :func:`~lyngdorf.discovery.lookup_model`.
lookup_receiver_model = _lookup_model


async def async_create_receiver(*args: Any, **kwargs: Any) -> LyngdorfReceiver:
    """1.x name for :func:`~lyngdorf.discovery.create_receiver`."""
    # Returned directly: create_receiver is now annotated with the
    # concrete type. This previously bound to a typed local purely to
    # silence no-any-return - treating the symptom of the `-> Any` above
    # rather than the cause.
    return await _create_receiver(*args, **kwargs)


async def async_find_receiver_model(*args: Any, **kwargs: Any) -> LyngdorfModel | None:
    """1.x name for :func:`~lyngdorf.discovery.discover_model`."""
    # Concrete, not Any. A passthrough's *args/**kwargs have to be Any -
    # it genuinely forwards anything - but that says nothing about what
    # comes back, and a caller writing `model = await
    # async_find_receiver_model(host)` on a deprecated path deserves the
    # same checking as one on the new path. Being deprecated is a reason
    # to type it, not an excuse: this is the surface people have not
    # migrated off yet.
    return await _discover_model(*args, **kwargs)


async def async_get_device_serial(host: str, timeout: float = 5.0) -> str | None:
    """1.x's combined UDP-then-HTTP serial lookup.

    2.0 splits this so a caller holding an ``ssdp_location`` skips UDP
    entirely; this composes the two halves for callers that have not
    migrated, reproducing 1.x behaviour exactly.
    """
    location = await _discover_ssdp_location(host, timeout=timeout)
    if location is None:
        return None
    return await _fetch_device_serial(location, timeout=timeout)


__all__ = [
    "Receiver",
    "async_create_receiver",
    "async_find_receiver_model",
    "async_get_device_serial",
    "lookup_receiver_model",
]
