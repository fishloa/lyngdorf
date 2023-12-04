import pytest
import asyncio
from lyngdorf.device import Receiver
import logging

_LOGGER = logging.getLogger(__package__)

async def main():
    client: Receiver = Receiver("192.168.16.16")
    await client.async_connect()
    await asyncio.sleep(2)
    _LOGGER.warning(f'{client.volume}')

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
