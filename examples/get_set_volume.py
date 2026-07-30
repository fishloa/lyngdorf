import asyncio
import logging

from lyngdorf.device import Receiver, async_create_receiver

_LOGGER = logging.getLogger(__package__)


async def main():
    client: Receiver = await async_create_receiver("192.168.16.16")
    await client.async_connect()
    await asyncio.sleep(2)
    _LOGGER.warning(f"{client.volume}")


if __name__ == "__main__":
    asyncio.run(main())
