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
from typing import Any
from xml.etree import ElementTree

import aiohttp

from .const import DEFAULT_LYNGDORF_PORT
from .exceptions import LyngdorfError
from .models import LyngdorfModel

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
    model = _lookup_model(message[start + 1 : end].strip('"'))
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

    def _search() -> str | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        try:
            sock.sendto(_SSDP_MSEARCH, (host, _SSDP_PORT))
            data, _ = sock.recvfrom(4096)
            for line in data.decode(errors="replace").splitlines():
                if line.lower().startswith("location:"):
                    return line.split(":", 1)[1].strip()
        except (OSError, TimeoutError):
            pass
        finally:
            sock.close()
        return None

    # ------------------------------------------------------------------
    # This is the library's ONE run_in_executor, and it is deliberate.
    # Do not "fix" it into an asyncio datagram endpoint.
    #
    # Ruled in spec D8 on evidence from Home Assistant (#50): of the 86
    # libraries behind platinum-tier integrations, 17 use run_in_executor,
    # to_thread or a thread pool — several for exactly this class of
    # blocking socket call. `xknx/io/util.py:93` offloading
    # socket.gethostbyname is the direct parallel; aioshelly offloads
    # address resolution, brother SNMP engine setup, androidtvremote2 a
    # cert-chain load. The practical `async-dependency` bar is "nothing
    # blocks the event loop", not "no thread ever".
    #
    # The hop is bounded twice — sock.settimeout(timeout) stops the
    # thread, wait_for(timeout + 1) stops the await — discovery-time
    # only, and avoidable: a caller with an ssdp_location calls
    # fetch_device_serial directly and never reaches here. HA owns SSDP
    # scanning centrally (46 integrations declare ssdp: matchers), so
    # this must not be grown either; it serves manual entry, which exists
    # precisely for the devices HA's scanner did not see.
    # ------------------------------------------------------------------
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _search), timeout=timeout + 1
        )
    except (TimeoutError, OSError):
        _LOGGER.debug("SSDP search to %s failed", host)
        return None


async def fetch_device_serial(
    location: str,
    *,
    session: aiohttp.ClientSession | None = None,
    timeout: float = 5.0,
) -> str | None:
    """Fetch the UPnP description XML at `location` and extract the
    device serial. Pure HTTP via aiohttp — no UDP anywhere on this path.

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


def _lookup_model(model_name: str) -> LyngdorfModel | None:
    """Look up a LyngdorfModel by its string model name.

    Case-insensitive: ``"mp-60"``, ``"MP-60"`` and ``"Mp-60"`` all
    resolve to ``LyngdorfModel.MP_60``.
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
) -> Any:
    """Create (but do not connect) a LyngdorfReceiver.

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
