"""Lyngdorf Audio Control Library - Device Module.

Main receiver classes and factory functions for all supported models.

Supported models are defined by `LyngdorfModel` (see `lyngdorf/models/`);
the README carries the human-readable list.

All communication via TCP/IP on port 84 (no serial port support).
"""

import asyncio
import logging

from .const import DEFAULT_LYNGDORF_PORT  # noqa: I001
from .models import LyngdorfModel  # noqa: I001
from .receiver import LyngdorfReceiver

_LOGGER = logging.getLogger(__package__)


async def async_create_receiver(
    host: str, model: LyngdorfModel | None = None
) -> LyngdorfReceiver:
    """Deprecated-in-place: WP5 renames this to create_receiver (with
    session injection) and ships its shim. Until then it keeps its 1.x
    name and its 1.x NotImplementedError contract for an unknown model
    (UnsupportedModelError arrives with WP5's discovery module)."""
    if not model:
        model = await async_find_receiver_model(host)
        if not model:
            raise NotImplementedError("Unknown Receiver")
    return LyngdorfReceiver(host, model)


async def async_find_receiver_model(
    host: str, timeout: float = 5.0
) -> LyngdorfModel | None:
    """Discover a Lyngdorf device model on port 84.

    Returns:
        LyngdorfModel if a supported model is detected, None otherwise.

    Raises:
        ValueError: If host is invalid
        TimeoutError: If connection times out
    """
    from .rio import LyngdorfProtocol  # type: ignore[attr-defined]

    try:
        _, protocol = await asyncio.wait_for(
            asyncio.get_event_loop().create_connection(
                lambda: LyngdorfProtocol(), host, DEFAULT_LYNGDORF_PORT  # type: ignore[call-arg,arg-type]
            ),
            timeout=timeout,
        )
    except (ConnectionRefusedError, OSError) as ex:
        _LOGGER.error("Connection refused during model discovery: %s", ex)
        return None
    except TimeoutError as ex:
        _LOGGER.error("Timeout during model discovery: %s", ex)
        raise

    try:
        return lookup_receiver_model(protocol.banner)  # type: ignore[attr-defined]
    finally:
        protocol.close()


async def async_get_device_serial(host: str, timeout: float = 5.0) -> str | None:
    """Interrogate a Lyngdorf device for its serial number over the :84
    telnet port.

    Returns:
        The device's serial number as a string, or None if the device
        does not answer the query within `timeout` seconds.
    """
    from .rio import LyngdorfProtocol  # type: ignore[attr-defined]

    try:
        _, protocol = await asyncio.wait_for(
            asyncio.get_event_loop().create_connection(
                lambda: LyngdorfProtocol(), host, DEFAULT_LYNGDORF_PORT  # type: ignore[call-arg,arg-type]
            ),
            timeout=timeout,
        )
    except (TimeoutError, ConnectionRefusedError, OSError):
        return None

    try:
        protocol.sendLine("!SERIAL?")  # type: ignore[attr-defined]
        response = await asyncio.wait_for(protocol.readMessage(), timeout=5.0)  # type: ignore[attr-defined]
        if response and response.startswith("!SERIAL("):
            return response[8:].rstrip(")")  # type: ignore[no-any-return]
        return None
    except TimeoutError:
        return None
    finally:
        protocol.close()


def lookup_receiver_model(model_name: str) -> LyngdorfModel | None:
    """Look up a LyngdorfModel by its string model name.

    Case-insensitive: ``"mp-60"``, ``"MP-60"`` and ``"Mp-60"`` all
    resolve to ``LyngdorfModel.MP_60``.
    """
    search = model_name.lower()
    for model in LyngdorfModel:
        if model.config.model_name.lower() == search:
            return model
    return None
