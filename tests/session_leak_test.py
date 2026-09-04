"""Regression tests: connecting and disconnecting must leave no open
aiohttp session.

A streaming-capable model allocates a `ClientSession` lazily, deep inside
the now-playing poll loop's first request (`StreamingClient._session`).
Nothing above that layer holds a reference to it, so a lifecycle bug
there is invisible: it never fails a test, never raises, and surfaces
only as aiohttp's "Unclosed client session" printed at interpreter exit
by the garbage collector — attributed to whichever test happened to be
running at the time rather than to the one that leaked.

That is exactly what happened. The message was in every run of the suite
and was read past as noise; instrumenting `ClientSession.__init__`
showed 83 sessions created across the suite and 15 never closed, behind
that one line. Two real bugs were underneath:

- `LyngdorfApi.async_disconnect` never closed the client `_ensure_poll`
  builds. `LyngdorfReceiver.disconnect` does, so only a direct
  `LyngdorfApi` user was affected — but that class is public and builds
  its poll lazily behind its own accessors, so nothing would ever have
  closed it.
- `NowPlayingPoll.stop()` only *requests* cancellation. The dying task's
  last in-flight request lazily recreated the session that had just been
  closed, so closing it was necessary and not sufficient.

These tests assert the property directly rather than watching for the
message, and they assert it INSIDE the test body — `conftest`'s
`_close_every_streaming_session` sweeps up at teardown, which would
otherwise hide precisely the defect under test.
"""

import asyncio

import aiohttp
import pytest

from lyngdorf import api as lyngdorf_api
from lyngdorf.api import LyngdorfApi
from lyngdorf.discovery import create_receiver
from lyngdorf.models import LyngdorfModel

#: A streaming model, so a poll starts and a session is actually created.
#: A non-streaming model would make every assertion here vacuous.
STREAMING_MODEL = LyngdorfModel.MP_60


@pytest.fixture
def sessions(monkeypatch):
    """Every `ClientSession` constructed during this test.

    Tracks construction rather than use: the leak is created lazily in
    the poll loop, where no test can reach it to check afterwards.
    """
    created: list[aiohttp.ClientSession] = []
    original_init = aiohttp.ClientSession.__init__

    def _tracking_init(self, *args: object, **kwargs: object) -> None:
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(aiohttp.ClientSession, "__init__", _tracking_init)
    return created


async def _fake_control_port(monkeypatch) -> asyncio.AbstractServer:
    """Stand a real TCP server in for the device's control port (:84).

    A real socket rather than a mock, because the leak lives in the
    connect/disconnect lifecycle and a mocked transport lets a test pass
    without that lifecycle ever running properly.
    """

    class _Amp(asyncio.Protocol):
        def data_received(self, data: bytes) -> None:
            """Swallow the setup burst; no reply is needed here."""

    loop = asyncio.get_running_loop()
    server = await loop.create_server(_Amp, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(lyngdorf_api, "DEFAULT_LYNGDORF_PORT", port)
    return server


async def _wait_for_a_session(
    sessions: list[aiohttp.ClientSession], timeout: float = 2.0
) -> None:
    """Wait until the poll loop has actually allocated one.

    Without this the tests below would pass vacuously the moment
    something stopped the poll from starting — green, and proving
    nothing. The assertion that at least one session exists is as
    load-bearing as the assertion that they are all closed.
    """
    elapsed = 0.0
    while not sessions and elapsed < timeout:
        await asyncio.sleep(0.02)
        elapsed += 0.02
    assert sessions, (
        "no ClientSession was ever created, so this test proves nothing. "
        "Either the model stopped being streaming-capable or the poll no "
        "longer starts on connect - fix the test, do not delete it."
    )


def _assert_all_closed(sessions: list[aiohttp.ClientSession]) -> None:
    leaked = [s for s in sessions if not s.closed]
    assert not leaked, (
        f"{len(leaked)} of {len(sessions)} aiohttp sessions were still open "
        f"after disconnect. This does not fail anything at runtime - it "
        f"prints 'Unclosed client session' at interpreter exit, blamed on "
        f"whatever the GC was near. Close what you allocate."
    )


class TestReceiverLifecycleLeaksNothing:
    """The documented lifecycle: `create_receiver` -> connect -> disconnect."""

    @pytest.mark.asyncio
    async def test_connect_then_disconnect_closes_every_session(
        self, sessions, monkeypatch
    ):
        server = await _fake_control_port(monkeypatch)
        try:
            receiver = await create_receiver("127.0.0.1", STREAMING_MODEL)
            await receiver.connect()
            await _wait_for_a_session(sessions)
            await receiver.disconnect()
            _assert_all_closed(sessions)
        finally:
            server.close()

    @pytest.mark.asyncio
    async def test_repeated_cycles_do_not_accumulate_open_sessions(
        self, sessions, monkeypatch
    ):
        """Three full cycles. A session recreated after close - which is
        legitimate, `_session()` does it deliberately so reconnect needs
        no special handling - must still end closed each time.

        This is the shape that made the first fix look wrong: closing the
        client without awaiting the poll task let the task allocate a
        replacement on its way out, so the leak count went UP.
        """
        server = await _fake_control_port(monkeypatch)
        try:
            for _ in range(3):
                receiver = await create_receiver("127.0.0.1", STREAMING_MODEL)
                await receiver.connect()
                await _wait_for_a_session(sessions)
                await receiver.disconnect()
                _assert_all_closed(sessions)
        finally:
            server.close()


class TestAcloseAwaitsTheTask:
    """The second half of the fix, pinned by its mechanism rather than by
    the race it prevents.

    Closing the streaming client was necessary and not sufficient:
    `stop()` only *requests* cancellation, so the poll task was still
    running when the session closed and its last in-flight request
    lazily allocated a replacement. Reproducing that race in a test is
    timing-dependent and would be flaky; the property underneath is not.

    `aclose()` must leave no running task behind. If that holds, the
    window cannot open.
    """

    @pytest.mark.asyncio
    async def test_the_task_is_finished_when_aclose_returns(self):
        from lyngdorf.streaming.client import StreamingClient
        from lyngdorf.streaming.poll import NowPlayingPoll

        client = StreamingClient("127.0.0.1", 8080)
        poll = NowPlayingPoll("127.0.0.1", client)
        try:
            poll.start()
            task = poll._now_playing_task
            assert task is not None, "start() did not create a poll task"
            assert not task.done(), "the task finished before it was tested"

            await poll.aclose()

            assert task.done(), (
                "aclose() returned while the poll task was still running. "
                "Its next request will lazily recreate the session about "
                "to be closed - use cancel-and-await, not stop()."
            )
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_stop_alone_does_not_wait(self):
        """The distinction the fix rests on, asserted so nobody
        'simplifies' aclose() back into stop().

        stop() is correct for a power-off, where the poll is expected to
        start again and nothing is being torn down underneath it. It is
        wrong before closing a session, and the difference is exactly
        this: it returns with the task still alive.
        """
        from lyngdorf.streaming.client import StreamingClient
        from lyngdorf.streaming.poll import NowPlayingPoll

        client = StreamingClient("127.0.0.1", 8080)
        poll = NowPlayingPoll("127.0.0.1", client)
        try:
            poll.start()
            task = poll._now_playing_task
            assert task is not None

            poll.stop()

            assert not task.done(), (
                "stop() now waits for the task. If that is deliberate, "
                "aclose() may be redundant - but check the session-close "
                "ordering before removing it."
            )
        finally:
            await poll.aclose()
            await client.close()


class TestApiLifecycleLeaksNothing:
    """`LyngdorfApi` driven directly - where the bug actually was.

    `LyngdorfReceiver.disconnect` always closed its streaming client;
    `LyngdorfApi.async_disconnect` did not close the one `_ensure_poll`
    builds for itself. The class is public, so this path needs its own
    guard rather than relying on the receiver's.
    """

    @pytest.mark.asyncio
    async def test_connect_then_disconnect_closes_every_session(
        self, sessions, monkeypatch
    ):
        server = await _fake_control_port(monkeypatch)
        api = LyngdorfApi("127.0.0.1", STREAMING_MODEL)
        try:
            await api.async_connect()
            await _wait_for_a_session(sessions)
            await api.async_disconnect()
            _assert_all_closed(sessions)
        finally:
            server.close()

    @pytest.mark.asyncio
    async def test_an_injected_poll_is_left_alone(self, sessions, monkeypatch):
        """Ownership, asserted in the other direction.

        `LyngdorfApi` must close only a poll it built itself. When one is
        injected - which is exactly what `LyngdorfReceiver` does - the
        caller owns the lifecycle, and closing it here would shut a
        session out from under whoever handed it over.
        """
        from lyngdorf.streaming.client import StreamingClient
        from lyngdorf.streaming.poll import NowPlayingPoll

        server = await _fake_control_port(monkeypatch)
        client = StreamingClient("127.0.0.1", 8080)
        poll = NowPlayingPoll("127.0.0.1", client)
        api = LyngdorfApi("127.0.0.1", STREAMING_MODEL, poll=poll)
        try:
            await api.async_connect()
            await _wait_for_a_session(sessions)
            await api.async_disconnect()
            assert any(not s.closed for s in sessions), (
                "an injected poll's session was closed by LyngdorfApi. It "
                "belongs to whoever injected it - see the _owns_poll rule."
            )
        finally:
            await client.close()
            server.close()
