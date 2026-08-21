"""Connect to a device, read its volume, then disconnect cleanly.

Usage:
    python examples/get_set_volume.py <host>
"""

import asyncio
import logging
import sys

from lyngdorf.device import Receiver, async_create_receiver

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


async def main(host: str) -> None:
    client: Receiver = await async_create_receiver(host)
    await client.async_connect()
    try:
        # Give the setup burst a moment to populate initial state.
        await asyncio.sleep(2)
        _LOGGER.info("volume: %s dB", client.volume)
    finally:
        # Always disconnect, including on failure. On a streaming-capable
        # model, connecting starts a now-playing poll loop that runs
        # `while self._connection_enabled:` - a flag only async_disconnect()
        # clears. Skipping this leaves that loop retrying forever, each
        # retry stranding another blocking HTTP call in an executor thread.
        # See KNOWN_ISSUES.md.
        await client.async_disconnect()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <host>")
    asyncio.run(main(sys.argv[1]))
