"""The :84 RIO wire protocol: framing, the paced write queue, connection
lifecycle, and per-family registration tables.

Internal to lyngdorf - nothing here is part of the public API. `rio` knows
how to talk to the device; it never imports from `device`, `api`, or
`streaming` (see the 2.0 design doc, §4's import-direction rule).
"""

from .protocol import LyngdorfProtocol

__all__ = [
    "LyngdorfProtocol",
]
