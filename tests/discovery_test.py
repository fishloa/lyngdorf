"""Discovery: three transports, three functions (spec §2.1, §8, D8).

The split's whole point is that a caller who already knows the UPnP
location never takes the UDP hop, so these tests exercise each half
independently and then the compose path, exactly as the two real callers
do (Home Assistant's discovered flow; its manual-entry flow).
"""

import asyncio
import inspect
import socket

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer

from lyngdorf.discovery import (
    _lookup_model,
    discover_model,
    discover_ssdp_location,
    fetch_device_serial,
)
from lyngdorf.models import LyngdorfModel

_DESCRIPTION_XML = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>Lyngdorf MP-60</friendlyName>
    <serialNumber>ABC123def</serialNumber>
  </device>
</root>"""

_SSDP_PORT = 1900


async def _search_against(port: int) -> str | None:
    """Call discover_ssdp_location against a local UDP responder bound to
    `port` rather than the default 1900."""
    import lyngdorf.discovery as mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "_SSDP_PORT", port)
        return await discover_ssdp_location("127.0.0.1", timeout=1.0)


@pytest_asyncio.fixture
async def description_server():
    """Serves the UPnP description document, counting requests."""
    hits: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        hits.append(request.path)
        return web.Response(text=_DESCRIPTION_XML, content_type="text/xml")

    async def not_found(request: web.Request) -> web.Response:
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/desc.xml", handler)
    app.router.add_get("/missing.xml", not_found)
    server = TestServer(app)
    await server.start_server()
    server.hits = hits  # type: ignore[attr-defined]
    yield server
    await server.close()


class TestFetchDeviceSerial:
    @pytest.mark.asyncio
    async def test_owned_session_path(self, description_server):
        """No session supplied: the function creates and closes its own."""
        url = str(description_server.make_url("/desc.xml"))
        assert await fetch_device_serial(url) == "abc123def"

    @pytest.mark.asyncio
    async def test_injected_session_is_used_and_never_closed(self, description_server):
        """spec §8: an injected session is used for the description fetch
        and is never closed by the library."""
        url = str(description_server.make_url("/desc.xml"))
        async with aiohttp.ClientSession() as session:
            assert await fetch_device_serial(url, session=session) == "abc123def"
            assert not session.closed
        assert description_server.hits == ["/desc.xml"]

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, description_server):
        url = str(description_server.make_url("/missing.xml"))
        assert await fetch_device_serial(url) is None

    @pytest.mark.asyncio
    async def test_unreachable_returns_none_rather_than_raising(self):
        """The helpers' never-raises contract (spec §8) covers this path:
        a config flow calls it on a host it is still validating."""
        assert await fetch_device_serial("http://127.0.0.1:1/desc.xml") is None

    @pytest.mark.asyncio
    async def test_malformed_xml_returns_none(self):
        async def handler(request):
            return web.Response(text="<not-xml", content_type="text/xml")

        app = web.Application()
        app.router.add_get("/desc.xml", handler)
        server = TestServer(app)
        await server.start_server()
        try:
            assert await fetch_device_serial(str(server.make_url("/desc.xml"))) is None
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_no_udp_on_this_path(self, description_server, monkeypatch):
        """The point of the split: reaching the HTTP half must not touch
        UDP. A SOCK_DGRAM socket() call of any kind fails this test."""

        _real_socket = socket.socket

        def _boom(family=-1, type=-1, proto=-1, fileno=None):
            if type == socket.SOCK_DGRAM:
                raise AssertionError("fetch_device_serial opened a UDP socket")
            return _real_socket(family, type, proto, fileno)

        monkeypatch.setattr(socket, "socket", _boom)
        url = str(description_server.make_url("/desc.xml"))
        assert await fetch_device_serial(url) == "abc123def"


class TestDiscoverSsdpLocation:
    @pytest.mark.asyncio
    async def test_returns_location_header(self):
        """A real UDP responder on loopback — the executor hop runs."""
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

        def _respond() -> None:
            data, addr = sock.recvfrom(4096)
            assert b"M-SEARCH" in data
            sock.sendto(
                b"HTTP/1.1 200 OK\r\nLOCATION: http://127.0.0.1:8008/desc.xml\r\n\r\n",
                addr,
            )

        responder = loop.run_in_executor(None, _respond)
        try:
            location = await _search_against(port)
            assert location == "http://127.0.0.1:8008/desc.xml"
        finally:
            await responder
            sock.close()

    @pytest.mark.asyncio
    async def test_no_reply_returns_none_within_the_timeout(self):
        """Both bounds work: sock.settimeout(timeout) stops the thread and
        wait_for(timeout + 1) stops the await."""
        started = asyncio.get_running_loop().time()
        assert await discover_ssdp_location("127.0.0.1", timeout=0.5) is None
        assert asyncio.get_running_loop().time() - started < 3.0


class TestSignatureAsymmetryIsDeliberate:
    """spec §2.1, restated in D9: exactly two entry points carry `session`.
    This is a design decision with a docstring explaining it, not an
    omission — so it gets a test rather than a comment."""

    def test_session_bearing_entry_points(self):
        assert "session" in inspect.signature(fetch_device_serial).parameters

    @pytest.mark.parametrize("fn", [discover_model, discover_ssdp_location])
    def test_session_free_entry_points(self, fn):
        assert "session" not in inspect.signature(fn).parameters


class TestLookupModel:
    """Ported from basic_wiring_test's lookup_receiver_model cases; the
    function is now private (it never appeared in lyngdorf.__all__, in
    spec §7, or in the consumer fixture)."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("mp-60", LyngdorfModel.MP_60),
            ("MP-60", LyngdorfModel.MP_60),
            ("Mp-60", LyngdorfModel.MP_60),
            ("tdai-1120", LyngdorfModel.TDAI_1120),
            ("TDAI-1120", LyngdorfModel.TDAI_1120),
            ("unknown-model", None),
        ],
    )
    def test_lookup(self, name, expected):
        assert _lookup_model(name) is expected
