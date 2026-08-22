"""Connect to a device, read its volume, then disconnect cleanly.

Usage:
    python examples/get_set_volume.py <host>
"""

import asyncio
import logging
import sys

from lyngdorf import create_receiver

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


async def main(host: str) -> None:
    receiver = await create_receiver(host)
    await receiver.connect()
    try:
        # Give the setup burst a moment to populate initial state.
        await asyncio.sleep(2)
        _LOGGER.info("volume: %s dB", receiver.volume.value)
    finally:
        await receiver.disconnect()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <host>")
    asyncio.run(main(sys.argv[1]))
