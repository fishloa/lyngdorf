"""The :84 RIO wire protocol: framing, the paced write queue, connection
lifecycle, and per-family registration tables.

Internal to lyngdorf - nothing here is part of the public API. `rio` knows
how to talk to the device; it never imports from `device`, `api`, or
`streaming` (see the 2.0 design doc, §4's import-direction rule).
"""

from .client import RioClient
from .protocol import LyngdorfProtocol
from .queue import (
    _ABSOLUTE_SETTER_SHAPE,
    _absolute_setter_tokens_for_model,
    _coalesce_key,
    _QueuedWrite,
)

__all__ = [
    "LyngdorfProtocol",
    "RioClient",
    "_ABSOLUTE_SETTER_SHAPE",
    "_QueuedWrite",
    "_absolute_setter_tokens_for_model",
    "_coalesce_key",
]
