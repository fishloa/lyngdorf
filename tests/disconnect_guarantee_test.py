"""Regression tests for issue #45 (see KNOWN_ISSUES.md).

Connecting a streaming-capable model (every model except TDAI-2170 and the
P series) starts a background now-playing poll that makes real HTTP calls
in a thread-pool executor. If a test calls `async_connect()` against a
fake host and then fails or returns before calling `async_disconnect()`,
nothing ever tells that poll to stop - `asyncio.wait_for` cancels the
*await*, not the work, so a call already running in its executor thread
cannot be interrupted, and Python will not tear down a thread-pool worker
mid-block.

`tests/conftest.py`'s `_guarantee_disconnect` autouse fixture tracks every
`LyngdorfApi` a test connects and disconnects each one during teardown, so
disconnect runs on the failure path as well as the success path. These
tests prove that guarantee, and prove the fixture's own bound: it must not
itself hang if a receiver refuses to disconnect promptly.

Several tests here rely on pytest running tests within a module top to
bottom (the default, and true for every supported pytest version this
project targets): a "victim" test connects, deliberately fails or leaves
something stuck, and records a timestamp or a reference in module-level
state; the following test inspects what the autouse fixture's teardown
did in between - proof the fixture ran, and ran within its own bound,
without requiring a nested pytest invocation to observe it.
"""

import asyncio
import time
from unittest import mock

import pytest

from lyngdorf import create_receiver as async_create_receiver
from lyngdorf.api import LyngdorfApi
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver

FAKE_IP = "0.0.0.0"

# Shared state for the "victim test, then inspect" pairs below.
_shared: dict[str, object] = {}


async def _connect_with_mocked_control_port(client: LyngdorfReceiver) -> None:
    """Connect `client`'s control-port (:84) transport without touching a
    real socket - the same pattern `basic_wiring_test.py` uses throughout.
    Streaming HTTP (:8080), if the model has that feature, is left real,
    exactly as it is for every other test that connects a streaming model
    to `FAKE_IP` - `_guarantee_disconnect` doesn't require anything special
    of a test, that's the point.
    """
    transport = mock.Mock()

    def create_conn(proto_factory, host, port):
        return (transport, proto_factory())

    with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
        debug_mock.return_value.create_connection = mock.AsyncMock(
            side_effect=create_conn
        )
        await client.connect()


class TestDisconnectGuaranteedAfterFailure:
    """Proves the core "Done when" guarantee: every receiver connected
    during a test is disconnected at teardown, including when the test
    fails - not just when it reaches its own `async_disconnect()` call.
    """

    @pytest.mark.xfail(
        reason=(
            "deliberately fails before calling async_disconnect() - exercises "
            "condition 3 from KNOWN_ISSUES.md/issue #45. The next test proves "
            "the autouse fixture disconnected this receiver anyway."
        ),
        strict=True,
    )
    @pytest.mark.asyncio
    async def test_connect_then_fail_without_disconnecting(self):
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        await _connect_with_mocked_control_port(client)
        assert client.connected  # sanity - the bug requires a live connection
        _shared["disconnect_guarantee_client"] = client
        raise AssertionError("deliberate failure - never reaches async_disconnect()")

    @pytest.mark.asyncio
    async def test_previous_failure_was_disconnected_by_the_fixture(self):
        client = _shared["disconnect_guarantee_client"]
        assert isinstance(client, LyngdorfReceiver)
        # Without _guarantee_disconnect, nothing would ever have called
        # async_disconnect() on this receiver: connected would still be
        # True, and its now-playing poll task would still exist, wanting
        # to keep running.
        assert client.connected is False
        assert client._api._now_playing_task is None
        assert client._api._now_playing_wanted is False


class TestFixtureTeardownDoesNotItselfHang:
    """Proves the other "Done when" requirement: the fixture's own
    teardown must not hang if a receiver refuses to disconnect promptly -
    it disconnects under a short timeout and reports rather than blocking.
    """

    @pytest.mark.asyncio
    async def test_connect_with_stuck_disconnect(self, monkeypatch):
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        await _connect_with_mocked_control_port(client)

        async def _stuck_disconnect(*_args, **_kwargs):
            # Stands in for a now-playing poll's executor thread already
            # running a blocking call it cannot be interrupted mid-flight
            # (see KNOWN_ISSUES.md) - deliberately far longer than
            # _guarantee_disconnect's own bound (2s), so this proves the
            # fixture bails out rather than waiting the full duration.
            await asyncio.sleep(30)

        monkeypatch.setattr(LyngdorfApi, "async_disconnect", _stuck_disconnect)
        # No explicit disconnect call - the autouse fixture's teardown,
        # which runs immediately after this test function returns, is
        # what has to survive this receiver refusing to disconnect.
        _shared["stuck_disconnect_test_finished_at"] = time.monotonic()

    @pytest.mark.asyncio
    async def test_stuck_disconnect_teardown_was_bounded(self):
        finished_at = _shared["stuck_disconnect_test_finished_at"]
        assert isinstance(finished_at, float)
        elapsed = time.monotonic() - finished_at
        assert elapsed < 10.0, (
            f"the fixture's teardown for the stuck-disconnect test took "
            f"{elapsed:.2f}s - it should have bailed out at its own "
            "_DISCONNECT_TEARDOWN_TIMEOUT bound (2s) and logged a warning, "
            "rather than waiting anywhere near the full 30s stuck disconnect"
        )


@pytest.mark.xfail(
    reason=(
        "deliberately fails before calling async_disconnect() - the literal "
        "regression scenario from issue #45. The next test asserts that this "
        "test's own teardown (including the autouse fixture) was prompt."
    ),
    strict=True,
)
@pytest.mark.asyncio
async def test_connect_streaming_model_to_fake_host_then_fail_completes_promptly():
    """The literal regression scenario from issue #45: a streaming-capable
    model connected to a fake host, in a test that fails before reaching
    `async_disconnect()`. Uses real (unmocked) streaming-port networking -
    exactly like every other test that connects a streaming model to
    FAKE_IP - since the point of the fixture is that a test doesn't need
    to do anything special to be protected.

    Records its own finish time; the following test asserts on the gap,
    which captures this test's *entire* teardown (including the autouse
    fixture disconnecting it), not just this function's own body.
    """
    client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
    await _connect_with_mocked_control_port(client)
    assert client.connected
    _shared["fake_host_test_finished_at"] = time.monotonic()
    raise AssertionError("deliberate failure - never reaches async_disconnect()")


def test_fake_host_test_and_its_teardown_completed_promptly():
    """Two orders of magnitude below the ~120s hang KNOWN_ISSUES.md
    describes, so this fails loudly if the previous test's now-playing
    poll ever blocked its own teardown rather than just running slowly.
    """
    finished_at = _shared["fake_host_test_finished_at"]
    assert isinstance(finished_at, float)
    elapsed = time.monotonic() - finished_at
    assert (
        elapsed < 10.0
    ), f"the fake-host streaming-connect test's teardown took {elapsed:.2f}s"
