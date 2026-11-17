"""Structural value objects: Reading, Selector and Switch.

A feature a model's protocol table does not define has no object at all,
so presence of the object is the capability check (design §5). Objects own
cached state behind internal `_update*` methods; the receiver's wire
callbacks hand finished values in. Writes go through constructor-injected
senders, so nothing here knows protocol framing.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping, Sequence

from .base import CountingNumberDict
from .const import Msg
from .exceptions import LyngdorfInvalidValueError
from .rio import RioClient


def warn_deprecated(old: str, replacement: str, *, stacklevel: int = 3) -> None:
    warnings.warn(
        f"{old} is deprecated and will be removed in lyngdorf 3.0; use {replacement}",
        DeprecationWarning,
        stacklevel=stacklevel,
    )


class Reading:
    """A read-only string value, None until the device reports it.

    `options` is the fixed vocabulary the value is drawn from, or `[]`
    where there is none.
    """

    def __init__(
        self, options: Mapping[int, str] | Sequence[str] | None = None
    ) -> None:
        self._options = options if options is not None else []
        self._value: str | None = None

    @property
    def value(self) -> str | None:
        return self._value

    @property
    def options(self) -> list[str]:
        if isinstance(self._options, Mapping):
            return list(self._options.values())
        return list(self._options)

    def _update(self, value: str | None) -> None:
        self._value = value


class Selector(Reading):
    """A Reading the caller can also change, by name.

    The wire carries an index, so a name outside `options` has no index to
    send: it raises LyngdorfInvalidValueError and sends nothing.
    """

    def __init__(self, options: Mapping[int, str], send: Callable[[int], None]) -> None:
        super().__init__(options)
        self._map = options
        self._send = send

    async def select(self, name: str) -> None:
        """Choose `name` (queued for paced delivery)."""
        for index, candidate in self._map.items():
            if candidate == name:
                self._send(index)
                return
        raise LyngdorfInvalidValueError(
            f"{name} is not a valid choice, and cannot be chosen"
        )


class Switch:
    """An on/off state, None until the device reports it."""

    def __init__(self, send: Callable[[bool], None]) -> None:
        self._send = send
        self._value: bool | None = None

    @property
    def value(self) -> bool | None:
        return self._value

    async def set(self, on: bool) -> None:
        """Turn on or off (queued for paced delivery)."""
        self._send(on)

    def _update(self, value: bool | None) -> None:
        self._value = value


def build_reading(
    rio: RioClient,
    msg: Msg,
    options: Mapping[int, str] | Sequence[str] | None = None,
) -> Reading | None:
    """The Reading for `msg`, or None on a model whose protocol lacks it."""
    if msg not in rio._model.config.messages:
        return None
    return Reading(options)


def build_selector(
    rio: RioClient,
    msg: Msg,
    send: Callable[[int], None],
    options: CountingNumberDict | None = None,
) -> Selector | None:
    """The Selector for `msg`, or None on a model whose protocol lacks it.
    `options` lets the caller keep the CountingNumberDict that the wire
    callbacks fill."""
    if msg not in rio._model.config.messages:
        return None
    return Selector(options if options is not None else CountingNumberDict(), send)
