
from lyngdorf.device import find_receiver_model
import logging

_LOGGER = logging.getLogger(__package__)

def main():
    model=find_receiver_model("192.168.16.16")
    _LOGGER.warn(f'found {model}')
