#!/usr/bin/env python3
"""
This module implements the handler for volume of Lyngdorf receivers.

:license: MIT, see LICENSE for more details.
"""

import contextlib
import logging
from collections.abc import Callable
from typing import TypeVar

_LOGGER = logging.getLogger(__package__)

_T = TypeVar("_T")


def register_in_list(registry: list[_T], callback: _T) -> Callable[[], None]:
    """Add `callback` to `registry`, returning an idempotent unsubscribe.

    Registering the same callback twice collapses to a single entry (so it
    fires once, not twice) and both calls get back a working unsubscribe for
    that shared entry. The returned unsubscribe is safe to call more than
    once, or after the callback has already been removed some other way -
    teardown paths run more than once in practice, so it is a no-op rather
    than an error.

    Pure list operations only: no I/O, no tasks, no awaits.
    """
    if callback not in registry:
        registry.append(callback)

    def unsubscribe() -> None:
        with contextlib.suppress(ValueError):
            registry.remove(callback)

    return unsubscribe


class CountingNumberDict(dict[int, str]):
    """An integer:String map, that keeps track of how many elements it should have"""

    def __init__(self, count: int = 0):
        super().__init__()
        self.count: int = count

    def is_full(self) -> bool:
        return len(self.keys()) >= self.count

    def count_callback(self, param1: str, ignored: str) -> None:
        self.clear()
        self.count = int(param1)

    def add(self, index: int, value: str) -> None:
        self.__setitem__(index, value)

    @property
    def list_of_values(self) -> list[str]:
        return list(self.values())

    def lookupIndex(self, value: str) -> int:
        for k, v in self.items():
            if value == v:
                return k
        return -1
