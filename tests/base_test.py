import asyncio
import logging
import pytest

from lyngdorf.base import  CountingNumberDict

_LOGGER = logging.getLogger(__package__)

def test_counting_dictionary_test():
    cd: CountingNumberDict = CountingNumberDict(3)
    
    cd.add(0, "zero")
    cd.add(1, "one")
    assert False ==  cd.is_full() 
    cd.add(2, "two")
    
    assert cd.is_full()
    
    assert 1 == cd.lookupIndex('one')
    assert 'zero,one,two' == ','.join(cd.values())
    
    
    _LOGGER.debug("nothng to see here")
    
    