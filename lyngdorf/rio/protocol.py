"""Framing for the :84 RIO protocol: the asyncio.Protocol implementation
and the quote-aware closing-paren scan its caller needs to split a reply.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

_LOGGER = logging.getLogger(__package__)


def _find_closing_paren(message: str, start: int) -> int:
    """Index of the first ``)`` at or after ``start`` that is not inside a
    quoted section, or -1 if there is none.

    A plain ``find(")")`` is wrong for any model that puts the name inside
    the parens. TDAI replies are shaped ``!SRCNAME(0,"Digital 1 (Coax)")``,
    so the first ``)`` is the one closing "(Coax)" and the name is cut short.
    Scanning past quoted sections keeps that intact while leaving the MP and
    P shape - ``!SRC(0)"HDMI"``, name outside the parens - parsed exactly as
    before. Note this is why ``rfind`` would not do instead: on the MP shape
    the last ``)`` is the one inside the name.
    """
    in_quotes = False
    for index in range(start, len(message)):
        character = message[index]
        if character == '"':
            in_quotes = not in_quotes
        elif character == ")" and not in_quotes:
            return index
    return -1


class LyngdorfProtocol(asyncio.Protocol):
    """Protocol for the Lyngdorf interface."""

    def __init__(
        self,
        on_message: Callable[[str], None],
        on_connection_lost: Callable[[], None],
    ) -> None:
        """Initialize the protocol."""
        self._buffer = b""
        self.transport: asyncio.Transport | None = None
        self._on_message = on_message
        self._on_connection_lost = on_connection_lost

    @property
    def connected(self) -> bool:
        """Return True if transport is connected."""
        if self.transport is None:
            return False
        return not self.transport.is_closing()

    def write(self, data: str) -> None:
        """Write data to the transport."""
        if self.transport is None or self.transport.is_closing():
            return
        self.transport.write(data.encode("utf-8"))

    def close(self) -> None:
        """Close the connection."""
        if self.transport is not None:
            self.transport.close()

    def eof_received(self) -> bool | None:
        _LOGGER.info("Pipe closed")
        self.close()
        self._on_connection_lost()
        return True

    def data_received(self, data: bytes) -> None:
        """Handle data received.

        Messages are terminated with CR, but the TDAI family follows that
        CR with an LF. Splitting on CR alone would leave the LF at the head
        of the next message, where it defeats the leading-"!" check in
        LyngdorfApi._process_event and the message is dropped in silence -
        so every reply after the first goes missing. Strip the framing off
        each line rather than assuming which terminator a model uses.
        """
        self._buffer += data
        while b"\r" in self._buffer:
            line, _, self._buffer = self._buffer.partition(b"\r")
            with contextlib.suppress(UnicodeDecodeError):
                message = line.decode("utf-8").strip("\r\n")
                if message:
                    self._on_message(message)

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        """Handle connection made."""
        _LOGGER.debug("connection made")
        self.transport = transport

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost."""
        self.close()
        self._on_connection_lost()
        return super().connection_lost(exc)
