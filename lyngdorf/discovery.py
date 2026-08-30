"""Discovery: three functions, three transports, one job each (design §2.1, §8).

discover_model       — TCP  :84, the 1.x port-84 model probe, moved verbatim
discover_ssdp_location — UDP  SSDP  M-SEARCH, the one retained executor hop (D8)
fetch_device_serial  — HTTP aiohttp, pure, no UDP anywhere on this path

The split's reason: a caller who already knows the UPnP location
(Home Assistant's SSDP cache) skips UDP entirely and calls
fetch_device_serial directly. Deliberately asymmetric — exactly two
entry points take `session` (create_receiver, fetch_device_serial);
the other two do not, and must not gain one (spec §2.1, restated in D9).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import TYPE_CHECKING
from xml.etree import ElementTree

import aiohttp

from .const import DEFAULT_LYNGDORF_PORT
from .exceptions import LyngdorfError
from .models import LyngdorfModel

if TYPE_CHECKING:
    # Import-time this module cannot see receiver.py - discovery.py is
    # imported from the package root before receiver.py finishes - so the
    # concrete import lives inside create_receiver's body. `from __future__ import
    # annotations` makes every annotation a string, so this block is
    # enough for the return type without reinstating the cycle.
    from .receiver import LyngdorfReceiver

_LOGGER = logging.getLogger(__package__)


class UnsupportedModelError(LyngdorfError):
    """The device at this host did not name a supported model.

    Replaces 1.x's NotImplementedError, which is a builtin that normally
    means "abstract method" — a library should not raise it (spec §2.1).
    """


_SSDP_PORT = 1900
_SSDP_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: urn:schemas-upnp-org:device:MediaRenderer:2\r\n"
    "\r\n"
).encode("ascii")


async def discover_model(host: str, timeout: float = 5.0) -> LyngdorfModel | None:
    """Discover a Lyngdorf device model on port 84.

    Returns:
        LyngdorfModel if a supported model is detected, None otherwise.

    Raises:
        TimeoutError: If connection times out
        OSError: If connection is refused
    """
    # The device does not volunteer its identity on connect - it must be
    # asked. An earlier 2.0 draft opened the connection and read a
    # `protocol.banner` attribute that has never existed, silenced by a
    # `type: ignore[attr-defined]`; it raised AttributeError on every call
    # and was caught only by running it against a real MP-60. Hence the
    # explicit request/response below, and no ignore comment.
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, DEFAULT_LYNGDORF_PORT), timeout=timeout
        )
        writer.write(b"!DEVICE?\r")
        await writer.drain()
        buf = await asyncio.wait_for(reader.readuntil(b"\r"), timeout=timeout)
    except (ConnectionRefusedError, OSError) as ex:
        _LOGGER.error("Connection refused during model discovery: %s", ex)
        return None
    except asyncio.IncompleteReadError:
        _LOGGER.warning("Connection to %s closed before a complete reply", host)
        return None
    except TimeoutError as ex:
        _LOGGER.error("Timeout during model discovery: %s", ex)
        raise
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    # Reply shape: `!DEVICE("MP-60")` - take what is between the parens.
    message = buf.decode("utf-8", errors="replace").lstrip("!")
    start, end = message.find("("), message.find(")")
    if not 0 <= start < end:
        _LOGGER.warning("Unexpected DEVICE reply from %s: %r", host, message.strip())
        return None
    model = lookup_model(message[start + 1 : end].strip('"'))
    if model is None:
        _LOGGER.warning("Model at %s is not supported: %r", host, message.strip())
    return model


async def discover_ssdp_location(host: str, timeout: float = 5.0) -> str | None:
    """Unicast SSDP M-SEARCH to a known host, returning its UPnP
    description URL (the LOCATION header), or None.

    UDP only — no HTTP, no session. Callers that already know the
    location (Home Assistant's own SSDP cache gives it as
    `ssdp_location`) skip this function entirely and go straight to
    `fetch_device_serial`; that avoidability is the point of the split.

    Deliberately takes NO session parameter: this speaks UDP, and a
    session here would misstate what it does (spec §2.1).
    """

    loop = asyncio.get_running_loop()
    reply: asyncio.Future[str] = loop.create_future()

    class _Protocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: object) -> None:
            if reply.done():
                return
            for line in data.decode(errors="replace").splitlines():
                if line.lower().startswith("location:"):
                    reply.set_result(line.split(":", 1)[1].strip())
                    return

        def error_received(self, exc: Exception) -> None:
            # ICMP port-unreachable and friends. Fail fast rather than
            # sitting out the whole timeout for a host that has answered.
            if not reply.done():
                reply.set_exception(exc)

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _Protocol, local_addr=("0.0.0.0", 0), family=socket.AF_INET
        )
    except OSError:
        _LOGGER.debug("SSDP search to %s could not open a socket", host)
        return None

    try:
        # NOT connected to the remote: the address goes on the datagram.
        # A connected socket would drop a reply arriving from any source
        # port other than 1900, and a device is not obliged to answer
        # from the port it was asked on.
        transport.sendto(_SSDP_MSEARCH, (host, _SSDP_PORT))
        return await asyncio.wait_for(reply, timeout)
    except (TimeoutError, OSError):
        _LOGGER.debug("SSDP search to %s failed", host)
        return None
    finally:
        transport.close()


async def fetch_device_serial(
    location: str,
    *,
    session: aiohttp.ClientSession | None = None,
    timeout: float = 5.0,
) -> str | None:
    """Fetch the UPnP description XML at `location` and extract the
    device serial. Pure HTTP via aiohttp — no UDP anywhere on this path.

    THE PORT IS NOT FIXED, and must not be documented as though it were.
    Measured against a real MP-60: the SSDP LOCATION header pointed at a
    high, device-assigned port in the ephemeral range, serving a
    UUID-named XML file — not port 8080, not port 80, and not a
    predictable path. It was stable across repeated M-SEARCHes within one
    session, which says nothing about across a reboot; GUPnP, which the
    device's own SERVER header names, ordinarily binds an arbitrary free
    port at startup.

    8080 in particular is a plausible wrong answer and worth naming as
    one: `STREAMMAGIC_PORT` is 8080 and that IS a real Lyngdorf HTTP
    service, but it is the streaming module's JSON API, a different
    daemon from the UPnP description server. On the measured device
    :8080 and the description port were not the same service, and :80
    served the web UI. Do not conflate the three.

    So this function takes `location` verbatim and never assumes a port,
    and anyone documenting firewall requirements should write "the HTTP
    port advertised in the device's UPnP description" rather than a
    number. The fixed ports are TCP 84 (control) and UDP 1900 (the
    unicast M-SEARCH); the description port is discovered, not known.

    An injected session is used and never closed (spec §8); with none
    supplied the function creates one for the single request and closes
    it. Returns None on any network or parse failure rather than raising:
    a config flow calls this against a host it is still validating.
    """
    http = session if session is not None else aiohttp.ClientSession()
    try:
        async with http.get(
            location,
            timeout=aiohttp.ClientTimeout(total=timeout + 1),
            headers={"Connection": "close"},
        ) as resp:
            if resp.status != 200:
                return None
            xml_text = (await resp.read()).decode(errors="replace")
    except (TimeoutError, OSError, aiohttp.ClientError):
        _LOGGER.debug("Failed to fetch UPnP description from %s", location)
        return None
    finally:
        if session is None:
            await http.close()

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        _LOGGER.debug("Failed to parse UPnP XML from %s", location)
        return None
    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    serial_el = root.find(".//d:device/d:serialNumber", ns)
    if serial_el is not None and serial_el.text:
        return serial_el.text.strip().lower()
    return None


def lookup_model(model_name: str) -> LyngdorfModel | None:
    """Look up a LyngdorfModel by its string model name.

    Case-insensitive: ``"mp-60"``, ``"MP-60"`` and ``"Mp-60"`` all
    resolve to ``LyngdorfModel.MP_60``.

    Public, and deliberately distinct from `discover_model`: this is a
    pure string lookup with no I/O, for resolving a model name a caller
    already holds - a stored config value, an SSDP `modelName` field.
    `discover_model` is an async network probe against a live device.
    They are not interchangeable, and a consumer resolving a persisted
    setting must not be forced to touch the network to do it.

    Was `lookup_receiver_model` in 1.x; that name is shimmed. It was
    briefly private during the 2.0 rewrite, which broke every consumer
    that resolves a stored model at setup - caught by running a real
    integration against the branch.
    """
    search = model_name.lower()
    for model in LyngdorfModel:
        if model.config.model_name.lower() == search:
            return model
    return None


async def create_receiver(
    host: str,
    model: LyngdorfModel | None = None,
    *,
    session: aiohttp.ClientSession | None = None,
) -> LyngdorfReceiver:
    """Create (but do not connect) a LyngdorfReceiver.

    Returns the concrete type, not Any. This was annotated `-> Any` for
    the whole of 2.0.0/2.0.1/1.11.0, and it is the single worst place in
    the package for that: it is the factory for the main object, so a
    consumer writing the obvious `receiver = await create_receiver(...)`
    got Any and every attribute access on it went unchecked. Nothing
    reported the loss - shipping py.typed asserts the package is typed,
    and one Any at the entry point quietly made that untrue for the
    object every consumer holds. Absence of a signal, not a failure.

    The Any was a workaround for the import cycle above rather than a
    deliberate widening; a TYPE_CHECKING import is the correct form.

    With model=None, probes the device over :84 to identify it.
    Raises UnsupportedModelError if the reply names no supported model,
    TimeoutError/OSError on connection failure (propagated, as today).

    Two-phase by design, unchanged from 1.x: consumers register callbacks
    between creation and connect().

    `session` is used for all :8080 streaming-module HTTP and is never
    closed by the library. When None, the library creates its own on
    first use and closes it on disconnect().
    """
    from .receiver import LyngdorfReceiver

    if model is None:
        model = await discover_model(host)
        if model is None:
            raise UnsupportedModelError(
                f"No supported Lyngdorf model answered at {host}"
            )
    return LyngdorfReceiver(host, model, session=session)
