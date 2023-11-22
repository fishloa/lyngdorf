#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This module implements the handler for volume of Lyngdorf receivers.

:license: MIT, see LICENSE for more details.
"""

import logging

from attr import s, field

_LOGGER = logging.getLogger(__package__)


@s(auto_attribs=True, init=False)
class CountingNumberDict(dict):
    """An integer:String map, that keeps track of how many elements it should have"""

    count: int = 0

    def __init__(self, count: int = 0):
        super().__init__()
        self.count: int = count

    def is_full(self) -> bool:
        return len(self.keys()) >= self.count

    def count_callback(self, param1: str, ignored: str):
        self.clear()
        self.count = int(param1)

    def add(self, index: int, value: str):
        self.__setitem__(index, value)
        
    @property
    def list_of_values(self): 
        return list(self.values()) 

    def lookupIndex(self, value: str):
        for k, v in self.items():
            if value == v:
                return k
        return -1
