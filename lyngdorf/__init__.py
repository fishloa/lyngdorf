import sys
import logging

from enum import Enum
from dataclasses import dataclass

# stdout_handler = logging.StreamHandler(stream=sys.stdout)

# logging.basicConfig(level=logging.DEBUG, handlers=[stdout_handler])

@dataclass
class LyngdorfModelMixin:
    model: str
    manufacterer: str

class LyngdorfModel(LyngdorfModelMixin, Enum):
    MP_60 = "mp-60", "Lyngdorf"



    