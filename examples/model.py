import asyncio
import logging

from lyngdorf.device import async_find_receiver_model

_LOGGER = logging.getLogger(__package__)


async def main():
    model = await async_find_receiver_model("192.168.16.16")
    _LOGGER.warning(f"found {model}")


if __name__ == "__main__":
    asyncio.run(main())
