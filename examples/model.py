"""Probe a host and report which Lyngdorf model answered.

Usage:
    python examples/model.py <host>

No disconnect is needed here: discover_model opens and closes
its own short-lived connection and never starts a receiver, so there is
no now-playing poll loop to stop.
"""

import asyncio
import logging
import sys

from lyngdorf import discover_model

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


async def main(host: str) -> None:
    model = await discover_model(host)
    if model is None:
        _LOGGER.warning("no supported Lyngdorf model found at %s", host)
    else:
        _LOGGER.info("found %s at %s", model.config.model_name, host)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <host>")
    asyncio.run(main(sys.argv[1]))
