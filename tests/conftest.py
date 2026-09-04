import asyncio
import contextlib
import logging

import pytest
import pytest_asyncio

from lyngdorf.api import LyngdorfApi
from lyngdorf.models import LyngdorfModel
from lyngdorf.rio import RioClient

_LOGGER = logging.getLogger(__package__)

#: Bound on how long a single receiver's teardown disconnect may take.
#: Since the 2.0 aiohttp port, disconnect cancels the poll's in-flight
#: HTTP request outright, so this should never be hit - it stays as a
#: guard so a regression stalls one test by 2s with a warning, never the
#: whole suite. See `_guarantee_disconnect` below.
_DISCONNECT_TEARDOWN_TIMEOUT = 2.0


@pytest_asyncio.fixture(autouse=True)
async def _close_every_streaming_session(monkeypatch):
    """Close every aiohttp session this test caused to be created.

    Sibling of `_guarantee_disconnect`, and needed for the same reason at
    a lower level. That fixture tracks `LyngdorfApi.async_connect`, so it
    only sees receivers a test actually connects. Plenty of tests build a
    `NowPlayingPoll` or a `StreamingClient` directly, or start a poll
    without ever disconnecting, and those sessions are created lazily
    deep inside the poll loop (`_session()` on first request) where no
    test can see them to clean up.

    The result was aiohttp's "Unclosed client session" at interpreter
    exit - one line, attributed to whichever test happened to be running
    when the garbage collector got round to it, rather than to the test
    that leaked it. Instrumenting showed 15 leaked sessions behind that
    single message.

    This tracks construction instead of use, so it catches them wherever
    they come from. `close()` is idempotent and never touches an injected
    session, so closing one a test already closed is free.
    """
    from lyngdorf.streaming import client as _client_mod

    created: list[_client_mod.StreamingClient] = []
    original_init = _client_mod.StreamingClient.__init__

    def _tracking_init(self, *args: object, **kwargs: object) -> None:
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(_client_mod.StreamingClient, "__init__", _tracking_init)

    yield

    for client in created:
        with contextlib.suppress(Exception):
            await client.close()


async def _close_owned_streaming_session(api: LyngdorfApi) -> None:
    """Close a streaming session the api created for itself.

    `async_disconnect` already does this on the happy path. This exists
    for the path the fixture is *for*: a disconnect that hangs, fails, or
    - as in tests/disconnect_guarantee_test.py - has been monkeypatched
    to do nothing at all. In those cases the aiohttp session survives the
    test and surfaces as "Unclosed client session" at interpreter exit,
    attributed to whatever happened to be running at GC time rather than
    to the test that leaked it.

    Guaranteeing the disconnect without guaranteeing this left the
    fixture half-finished. Safe to call twice; `StreamingClient.close()`
    is idempotent and never touches an injected session.
    """
    poll = getattr(api, "_poll", None)
    if poll is None or not getattr(api, "_owns_poll", False):
        return
    with contextlib.suppress(Exception):
        await poll.aclose()
    with contextlib.suppress(Exception):
        await poll._streaming.close()


@pytest_asyncio.fixture(autouse=True)
async def _guarantee_disconnect(monkeypatch):
    """Teardown guarantee: every receiver a test connects gets disconnected.

    Connecting a streaming-capable model starts a background now-playing
    poll (`LyngdorfApi._start_now_playing_poll`). If a test fails or
    returns before calling `async_disconnect()`, nothing ever tells that
    poll to stop, and it would keep retrying into the next test.

    This tracks every `LyngdorfApi` a test connects (by wrapping
    `async_connect`, so no per-test opt-in is needed) and disconnects each
    one during teardown - on the failure path as well as the success path.

    History: this fixture was written for issue #45, when the poll's HTTP
    ran as `http.client` inside an executor thread and an in-flight
    request could not be interrupted by anything (see KNOWN_ISSUES.md's
    resolved section). The 2.0 aiohttp port made those calls genuinely
    cancellable, so cancelling the poll now aborts its request outright;
    the bounded disconnect below (`_DISCONNECT_TEARDOWN_TIMEOUT`) remains
    as a regression guard rather than a workaround.
    """
    connected: list[LyngdorfApi] = []
    original_connect = LyngdorfApi.async_connect

    async def _tracking_connect(
        self: LyngdorfApi, *args: object, **kwargs: object
    ) -> None:
        if self not in connected:
            connected.append(self)
        await original_connect(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(LyngdorfApi, "async_connect", _tracking_connect)

    yield

    for api in connected:
        try:
            await asyncio.wait_for(
                api.async_disconnect(), timeout=_DISCONNECT_TEARDOWN_TIMEOUT
            )
            await _close_owned_streaming_session(api)
        except TimeoutError:
            await _close_owned_streaming_session(api)
            _LOGGER.warning(
                "%s: async_disconnect() did not complete within %ss during "
                "test teardown - unexpected since the aiohttp port made "
                "streaming HTTP calls cancellable; continuing rather than "
                "blocking the suite",
                api.host,
                _DISCONNECT_TEARDOWN_TIMEOUT,
            )


@pytest.fixture(autouse=True)
def _no_setup_command_pacing(monkeypatch):
    """Tests don't talk to real hardware, so the inter-command delay in
    LyngdorfApi._writeSetup (needed to avoid overwhelming a real device with
    a rapid-fire command burst - see SETUP_COMMAND_DELAY in const.py) would
    only slow the suite down for no benefit."""
    monkeypatch.setattr(LyngdorfApi, "setup_command_delay", 0)
    # Same reasoning for the runtime outbound command queue's own pacing
    # (see COMMAND_PACING_MS in const.py and LyngdorfApi._drain_write_queue) -
    # a test that specifically wants to observe real pacing overrides this
    # back up on its own `api`/`client._api` instance, same pattern as
    # `setup_command_delay` above.
    monkeypatch.setattr(LyngdorfApi, "command_pacing_seconds", 0)


async def flush_write_queue(api: LyngdorfApi, max_iterations: int = 200) -> None:
    """Pump the event loop until `api`'s outbound command queue drains.

    Real writes go through a paced, coalescing queue (see
    `LyngdorfApi._writeCommand`/`_drain_write_queue`) serviced by a
    background task rather than landing on the transport synchronously. A
    test that fires off several commands and then immediately inspects
    what reached the (mocked) transport must give that task a chance to
    run first. Relies on `command_pacing_seconds` being zeroed (see
    `_no_setup_command_pacing` above) - each loop iteration then lets the
    drain task write at most one more already-queued command, since the
    write itself happens synchronously, before that item's own
    `asyncio.sleep`, the moment it is popped.
    """
    for _ in range(max_iterations):
        if not api._write_queue:
            return
        await asyncio.sleep(0)
    raise AssertionError(
        f"write queue for {api.host} did not drain within {max_iterations} "
        "event loop iterations"
    )


class RecordingRio(RioClient):
    """RioClient test double that records wire commands instead of
    queueing them.

    Unit tests for the 2.0 controls/components assert the EXACT wire
    strings the real per-model writer methods produce - the writers
    themselves run for real (scale math, token lookup, TDAI overrides);
    only the queue/transport underneath is replaced. Pacing and
    coalescing are covered separately by command_queue_test.py.
    """

    def __init__(self, model: LyngdorfModel) -> None:
        super().__init__("127.0.0.1", model)
        self.writes: list[str] = []

    def _writeCommand(self, command: str) -> None:
        self.writes.append(command)
