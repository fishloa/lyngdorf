import asyncio
import logging

import pytest
import pytest_asyncio

from lyngdorf.api import LyngdorfApi

_LOGGER = logging.getLogger(__package__)

#: Bound on how long a single receiver's teardown disconnect may take. See
#: `_guarantee_disconnect` below - this must stay short, since it is spent
#: on *every* test that connects, and a receiver that genuinely can't stop
#: (see KNOWN_ISSUES.md) should be reported, not left to stall the suite.
_DISCONNECT_TEARDOWN_TIMEOUT = 2.0


@pytest_asyncio.fixture(autouse=True)
async def _guarantee_disconnect(monkeypatch):
    """Regression fixture for issue #45 (see KNOWN_ISSUES.md).

    Connecting a streaming-capable model starts a background now-playing
    poll (`LyngdorfApi._start_now_playing_poll`) that makes real HTTP calls
    in a thread-pool executor. If a test fails or returns before calling
    `async_disconnect()`, nothing ever tells that poll to stop.

    This tracks every `LyngdorfApi` a test connects (by wrapping
    `async_connect`, so no per-test opt-in is needed) and disconnects each
    one during teardown - on the failure path as well as the success path.

    This does not make the underlying limitation in KNOWN_ISSUES.md go
    away: `asyncio.wait_for` cancels the *await*, not the work, so a
    now-playing poll whose HTTP call is already running in its executor
    thread at the moment a test fails cannot be interrupted by anything
    here, or by anything else - that is the one case this fixture cannot
    rescue. What it does guarantee is that `async_disconnect()` is always
    *attempted*, on every path, immediately, rather than only on tests
    that remembered to call it themselves - which is what stops that
    poll from continuing to retry indefinitely once a test has already
    moved on, and keeps `LyngdorfApi`'s own state (`connected`, the poll
    task, the write queue) consistent after a failing test rather than
    silently left half torn-down.

    The disconnect itself is bounded by `_DISCONNECT_TEARDOWN_TIMEOUT`:
    if a receiver's `async_disconnect()` doesn't complete in time, this
    logs a warning and moves on rather than hanging the rest of the
    suite on it.
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
        except TimeoutError:
            _LOGGER.warning(
                "%s: async_disconnect() did not complete within %ss during test "
                "teardown - a now-playing poll's executor thread is likely still "
                "running a blocking call that cannot be interrupted mid-flight "
                "(see KNOWN_ISSUES.md); continuing rather than blocking the suite",
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
