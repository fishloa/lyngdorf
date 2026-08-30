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
    UnsupportedModelError,
    create_receiver,
    discover_model,
    discover_ssdp_location,
    fetch_device_serial,
    lookup_model,
)
from lyngdorf.exceptions import LyngdorfError
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver

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
        assert lookup_model(name) is expected


class TestCreateReceiver:
    @pytest.mark.asyncio
    async def test_returns_receiver_never_none(self):
        r = await create_receiver("127.0.0.1", LyngdorfModel.MP_60)
        assert isinstance(r, LyngdorfReceiver)
        assert r.host == "127.0.0.1"
        assert r.model is LyngdorfModel.MP_60

    @pytest.mark.asyncio
    async def test_unknown_model_raises_typed_error(self, monkeypatch):
        """spec §2.1 / behavioural change 3: UnsupportedModelError, never
        NotImplementedError, and never a None return."""

        async def _no_model(host, timeout=5.0):
            return None

        monkeypatch.setattr("lyngdorf.discovery.discover_model", _no_model)
        with pytest.raises(UnsupportedModelError):
            await create_receiver("127.0.0.1")

    @pytest.mark.asyncio
    async def test_unsupported_model_error_is_a_lyngdorf_error(self):
        """spec §2.1: subclasses LyngdorfError only, not
        NotImplementedError."""
        assert issubclass(UnsupportedModelError, LyngdorfError)
        assert not issubclass(UnsupportedModelError, NotImplementedError)

    @pytest.mark.asyncio
    async def test_probe_path_uses_discover_model(self, monkeypatch):
        calls: list[str] = []

        async def _probe(host, timeout=5.0):
            calls.append(host)
            return LyngdorfModel.TDAI_3400

        monkeypatch.setattr("lyngdorf.discovery.discover_model", _probe)
        r = await create_receiver("10.0.0.9")
        assert calls == ["10.0.0.9"] and r.model is LyngdorfModel.TDAI_3400


class TestSessionOwnership:
    """spec §8, and §12's three named WP5 done-whens."""

    async def _noop_disconnect(self) -> None:
        pass

    @pytest.mark.asyncio
    async def test_ownership_decided_at_construction(self):
        owned = await create_receiver("127.0.0.1", LyngdorfModel.MP_60)
        assert owned._owns_session is True

        async with aiohttp.ClientSession() as injected:
            r = await create_receiver(
                "127.0.0.1", LyngdorfModel.MP_60, session=injected
            )
            assert r._owns_session is False
            assert r._session is injected

    @pytest.mark.asyncio
    async def test_injected_session_is_never_closed(self):
        """The inject-websession contract: HA owns it, we do not."""
        async with aiohttp.ClientSession() as injected:
            r = await create_receiver(
                "127.0.0.1", LyngdorfModel.MP_60, session=injected
            )
            # Mock the RIO disconnect so we don't hit the network
            r._api.async_disconnect = self._noop_disconnect  # type: ignore[method-assign]
            await r.disconnect()
            assert not injected.closed

    @pytest.mark.asyncio
    async def test_streaming_client_is_built_on_streaming_models(self):
        r = await create_receiver("127.0.0.1", LyngdorfModel.MP_60)
        assert r._streaming is not None

    @pytest.mark.parametrize(
        "model", [LyngdorfModel.TDAI_2170, LyngdorfModel.P_100, LyngdorfModel.P_300]
    )
    @pytest.mark.asyncio
    async def test_non_streaming_model_never_creates_a_streaming_client(self, model):
        """spec §8: streaming client is None, the poll loop never starts,
        and no session is ever created when none was injected."""
        r = await create_receiver("127.0.0.1", model)
        assert r._streaming is None
        # disconnect() on a never-connected non-streaming receiver
        r._api.async_disconnect = self._noop_disconnect  # type: ignore[method-assign]
        await r.disconnect()  # must not raise

    @pytest.mark.asyncio
    async def test_injected_session_on_a_non_streaming_model_is_held_unused(self):
        """Harmless by design — it keeps the factory signature uniform so
        a consumer needs no per-model conditional (spec §8)."""
        async with aiohttp.ClientSession() as injected:
            r = await create_receiver(
                "127.0.0.1", LyngdorfModel.TDAI_2170, session=injected
            )
            assert r._session is injected and r._streaming is None
            r._api.async_disconnect = self._noop_disconnect  # type: ignore[method-assign]
            await r.disconnect()
            assert not injected.closed


class TestNoBlockingCalls:
    """Home Assistant's `async-dependency` rule, pinned.

    "your library should also use asyncio. There are no exceptions to
    this rule." Written as an absolute, so evidence that other platinum
    libraries use executors does not help - it would be arguing against
    the rule's text in review.

    Spec decision D8 ruled the SSDP executor hop acceptable on exactly
    that evidence. D8 is reversed; these tests are what stop it coming
    back, because the executor form is the obvious way to write a
    blocking socket call and nothing else in the suite would object.
    """

    def test_the_library_contains_no_executor_or_thread_offload(self):
        """Population form, over every source file. A test naming
        discovery.py would pass while the next blocking call went into
        streaming/ or rio/."""
        import pathlib

        offenders = []
        root = pathlib.Path(__file__).parent.parent / "lyngdorf"
        for path in sorted(root.rglob("*.py")):
            text = path.read_text()
            for marker in ("run_in_executor", "to_thread", "ThreadPoolExecutor"):
                if marker in text:
                    offenders.append(f"{path.relative_to(root.parent)}: {marker}")
        assert (
            not offenders
        ), "Home Assistant's async-dependency rule admits no exceptions: " + ", ".join(
            offenders
        )

    @pytest.mark.asyncio
    async def test_ssdp_search_spawns_no_thread(self):
        """The observable form of the same thing. A future rewrite could
        drop the literal `run_in_executor` and still offload - this
        counts threads instead of reading source.

        Points at an address that will not answer, so it exercises the
        timeout path: the failing case is the one most likely to be
        implemented with a blocking socket.
        """
        import threading

        before = threading.active_count()
        assert await discover_ssdp_location("192.0.2.1", timeout=0.5) is None
        assert threading.active_count() == before, "SSDP search offloaded to a thread"
