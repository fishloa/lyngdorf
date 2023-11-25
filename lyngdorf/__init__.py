import sys
import logging

from enum import StrEnum
from lyngdorf.mp60 import LyngdorfMP60Client

stdout_handler = logging.StreamHandler(stream=sys.stdout)

logging.basicConfig(level=logging.DEBUG, handlers=[stdout_handler])

class LyngdorfModel(StrEnum):
    MP_60 = "mp-60"
    
def create_client(model: LyngdorfModel, host: str):
    if (model == LyngdorfModel.MP_60):
        return LyngdorfMP60Client(host)
    raise NotImplementedError()


    