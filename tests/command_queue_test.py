"""Tests for LyngdorfApi's paced, coalescing outbound command queue.

Regression coverage for a hardware-confirmed defect: writing straight to
the transport with no pacing overflows a real MP-60 past a queue-depth
cliff of ~16 in-flight commands - see COMMAND_PACING_MS in const.py and
https://github.com/fishloa/lyngdorf/issues/35 for the measurement. A Home
Assistant volume-slider drag alone emits 10-30 `!VOL(x)` writes in a
second, comfortably past that cliff.

These tests drive `LyngdorfApi` directly with a mocked `_protocol`
(recording `.write()` calls) rather than a real socket, and either avoid
sleeping altogether or intercept `asyncio.sleep` to record the requested
duration without actually waiting - a real device is explicitly off
limits (192.168.16.16 must never be touched by tests).
"""

import asyncio
import contextlib
from unittest import mock
from unittest.mock import AsyncMock

import pytest
from conftest import flush_write_queue

from lyngdorf.api import LyngdorfApi, LyngdorfProtocol, _coalesce_key
from lyngdorf.const import COMMAND_PACING_MS
from lyngdorf.models import LyngdorfModel

FAKE_IP = "0.0.0.0"


def _sent(api: LyngdorfApi) -> list[str]:
    """Every command that actually reached the mocked transport, in order."""
    return [call.args[0] for call in api._protocol.write.call_args_list]


class TestCoalescingShapeRule:
    """Unit coverage for `_coalesce_key` itself - the shape/token rule that
    decides what may coalesce, independent of the queue/timing machinery.
    """

    def test_absolute_setters_get_a_key(self):
        tokens = frozenset({"VOL", "TRIMBASS"})
        assert _coalesce_key("VOL(-300)", tokens) == "VOL"
        assert _coalesce_key("TRIMBASS(20)", tokens) == "TRIMBASS"

    def test_unknown_token_in_setter_shape_gets_no_key(self):
        """NUM(5) matches the `TOKEN(params)` shape, but NUM is never an
        absolute-setter token for any model - order and count are the
        whole meaning of the digits, so it must never coalesce."""
        tokens = frozenset({"VOL"})
        assert _coalesce_key("NUM(5)", tokens) is None

    def test_stepping_commands_get_no_key(self):
        tokens = frozenset({"VOL"})
        assert _coalesce_key("VOLUP", tokens) is None
        assert _coalesce_key("VOL+", tokens) is None
        assert _coalesce_key("RPVOI-", tokens) is None

    def test_queries_get_no_key(self):
        tokens = frozenset({"VOL"})
        assert _coalesce_key("VOL?", tokens) is None

    def test_navigation_gets_no_key(self):
        tokens = frozenset({"VOL"})
        for command in ("DIRU", "DIRD", "DIRL", "DIRR", "ENTER", "MENU", "BACK"):
            assert _coalesce_key(command, tokens) is None


class TestCoalescingThroughTheRealQueue:
    """End-to-end: what actually reaches the transport, not just the key
    computation - the queue must apply `_coalesce_key`'s verdict.
    """

    @pytest.mark.asyncio
    async def test_rapid_identical_token_absolute_setters_coalesce_to_latest(self):
        """A rapid-fire volume-slider drag - many `VOL(x)` writes with no
        pacing gaps - must collapse to a single write of the final value,
        not one write per intermediate value."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            for volume in range(-400, -100, 10):  # 30 rapid writes
                api._writeCommand(f"VOL({volume})")
            await flush_write_queue(api)
            assert _sent(api) == ["!VOL(-110)\r"]
        finally:
            api._stop_write_queue()

    @pytest.mark.asyncio
    async def test_coalescing_is_per_token_not_global(self):
        """Two different absolute-setter tokens interleaved must each
        collapse to their own latest value, not to a single last-write-
        wins across the whole queue."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            api._writeCommand("VOL(-300)")
            api._writeCommand("TRIMBASS(10)")
            api._writeCommand("VOL(-250)")
            api._writeCommand("TRIMBASS(20)")
            api._writeCommand("VOL(-200)")
            await flush_write_queue(api)
            assert set(_sent(api)) == {"!VOL(-200)\r", "!TRIMBASS(20)\r"}
            assert len(_sent(api)) == 2
        finally:
            api._stop_write_queue()

    @pytest.mark.asyncio
    async def test_relative_stepping_commands_do_not_coalesce(self):
        """Each VOLUP means "one more step" - ten of them must produce ten
        writes, never collapse to one."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            for _ in range(10):
                api._writeCommand("VOLUP")
            await flush_write_queue(api)
            assert _sent(api) == ["!VOLUP\r"] * 10
        finally:
            api._stop_write_queue()

    @pytest.mark.asyncio
    async def test_digits_do_not_coalesce_and_preserve_order(self):
        """Sequential digit entry: order and count are the whole meaning,
        so NUM(1) NUM(2) NUM(3) must arrive intact and in sequence."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            api._writeCommand("NUM(1)")
            api._writeCommand("NUM(2)")
            api._writeCommand("NUM(3)")
            await flush_write_queue(api)
            assert _sent(api) == ["!NUM(1)\r", "!NUM(2)\r", "!NUM(3)\r"]
        finally:
            api._stop_write_queue()

    @pytest.mark.asyncio
    async def test_cursor_and_navigation_commands_do_not_coalesce(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            for command in ("DIRU", "DIRU", "MENU", "DIRD", "ENTER"):
                api._writeCommand(command)
            await flush_write_queue(api)
            assert _sent(api) == [
                "!DIRU\r",
                "!DIRU\r",
                "!MENU\r",
                "!DIRD\r",
                "!ENTER\r",
            ]
        finally:
            api._stop_write_queue()

    @pytest.mark.asyncio
    async def test_queries_are_never_coalesced_away(self):
        """A caller re-querying deliberately (e.g. mute on power-on, see
        device.py) must see every query reach the transport, not just the
        latest."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            api._writeCommand("MUTE?")
            api._writeCommand("MUTE?")
            await flush_write_queue(api)
            assert _sent(api) == ["!MUTE?\r", "!MUTE?\r"]
        finally:
            api._stop_write_queue()


class TestBurstPacingAndCap:
    """A burst mixing all three command shapes must never put more than
    one write in flight at a time - the drain loop always paces after
    every write - keeping it far under the measured 16-command cliff.
    """

    @pytest.mark.asyncio
    async def test_burst_of_30_mixed_commands_is_paced_and_never_exceeds_cap(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api.command_pacing_seconds = COMMAND_PACING_MS / 1000
        api._protocol = mock.Mock()

        # A "controlled clock": record every requested sleep duration but
        # actually wait 0 seconds, so the test runs instantly instead of
        # spending 30 * 50ms on real sleeps.
        real_sleep = asyncio.sleep
        sleep_durations: list[float] = []

        async def fake_sleep(duration: float) -> None:
            sleep_durations.append(duration)
            await real_sleep(0)

        with mock.patch("asyncio.sleep", side_effect=fake_sleep):
            api._start_write_queue()
            try:
                for i in range(30):
                    if i % 3 == 0:
                        api._writeCommand(f"VOL({i})")  # absolute setter
                    elif i % 3 == 1:
                        api._writeCommand("VOLUP")  # stepping
                    else:
                        api._writeCommand(f"NUM({i % 10})")  # sequential

                for _ in range(500):
                    if not api._write_queue:
                        break
                    await real_sleep(0)
                else:
                    raise AssertionError("queue did not drain")
            finally:
                api._stop_write_queue()

        sent = _sent(api)

        # Coalesced down from 10 VOL(...) writes to the single latest one.
        vol_writes = [c for c in sent if c.startswith("!VOL(")]
        assert vol_writes == ["!VOL(27)\r"]

        # Every VOLUP survives - stepping never coalesces.
        assert sent.count("!VOLUP\r") == 10

        # Every NUM survives, in original order - sequential input never
        # coalesces and order is the whole meaning.
        num_writes = [c for c in sent if c.startswith("!NUM(")]
        expected_nums = [f"!NUM({i % 10})\r" for i in range(30) if i % 3 == 2]
        assert num_writes == expected_nums

        assert len(sent) == 1 + 10 + 10

        # Pacing: every write drained from the queue was followed by a
        # sleep requesting at least COMMAND_PACING_MS - never two writes
        # back-to-back with no pacing gap between them.
        pacing_sleeps = [d for d in sleep_durations if d > 0]
        assert len(pacing_sleeps) == len(sent)
        assert all(d >= COMMAND_PACING_MS / 1000 for d in pacing_sleeps)


class TestSyncFallbackWithNoDrainTask:
    """`_writeCommand` must still work when nothing is draining the queue
    - no running event loop at all, or (as many existing tests do) a
    protocol attached directly without going through
    `_async_establish_connection`. It falls back to writing immediately,
    mirroring `_ensure_now_playing_task`'s no-running-loop fallback.
    """

    def test_write_works_with_no_running_event_loop(self):
        """A genuinely synchronous call site - no asyncio anywhere."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._writeCommand("VOL(-200)")
        assert _sent(api) == ["!VOL(-200)\r"]

    @pytest.mark.asyncio
    async def test_write_flushes_immediately_when_no_drain_task_started(self):
        """A running loop exists, but no drain task was ever started -
        writes must still land immediately, one per call, same as before
        this queue existed."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        assert api._write_queue_task is None

        api._writeCommand("VOL(-200)")
        api._writeCommand("VOL(-100)")  # would coalesce with a task running
        assert _sent(api) == ["!VOL(-200)\r", "!VOL(-100)\r"]


class TestDrainTaskLifecycle:
    """The drain task starts on connect, stops on disconnect, and only
    ever one exists - mirrors `TestSinglePollTask` in streaming_test.py
    for `_now_playing_task`.
    """

    async def _connect(
        self, api: LyngdorfApi, transport: mock.Mock
    ) -> LyngdorfProtocol:
        holder: dict[str, LyngdorfProtocol] = {}

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            holder["protocol"] = proto
            return [transport, proto]

        with mock.patch("asyncio.get_event_loop") as loop_mock:
            loop_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await api.async_connect()
        return holder["protocol"]

    @pytest.mark.asyncio
    async def test_task_starts_on_connect(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        await self._connect(api, mock.Mock())
        try:
            assert api._write_queue_task is not None
            assert not api._write_queue_task.done()
        finally:
            await api.async_disconnect()

    @pytest.mark.asyncio
    async def test_repeated_start_creates_one_task(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        await self._connect(api, mock.Mock())
        try:
            first = api._write_queue_task
            for _ in range(5):
                api._start_write_queue()
            assert api._write_queue_task is first
        finally:
            await api.async_disconnect()

    @pytest.mark.asyncio
    async def test_task_stops_on_disconnect(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        await self._connect(api, mock.Mock())
        task = api._write_queue_task
        assert task is not None

        await api.async_disconnect()

        assert api._write_queue_task is None
        # `_stop_write_queue` requests cancellation and clears the
        # reference immediately (see its docstring); give the loop one
        # tick to actually process that cancellation.
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_reconnect_starts_a_fresh_task(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        await self._connect(api, mock.Mock())
        first = api._write_queue_task
        await api.async_disconnect()

        await self._connect(api, mock.Mock())
        try:
            second = api._write_queue_task
            assert second is not None
            assert second is not first
            assert not second.done()
        finally:
            await api.async_disconnect()


class TestQueuedWritesDoNotLeakAcrossReconnect:
    """A write queued for a connection that then drops must never land on
    a later connection - see `_stop_write_queue`'s docstring for why
    dropping (not flushing) is the right choice here."""

    @pytest.mark.asyncio
    async def test_pending_write_is_dropped_not_carried_to_new_connection(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        first_transport = mock.Mock()
        second_transport = mock.Mock()

        def make_create_conn(transport):
            def create_conn(proto_lambda, host, port):
                proto = proto_lambda()
                return [transport, proto]

            return create_conn

        with mock.patch("asyncio.get_event_loop") as loop_mock:
            loop_mock.return_value.create_connection = AsyncMock(
                side_effect=make_create_conn(first_transport)
            )
            await api.async_connect()

        # Enqueue without letting the drain task run - the write is still
        # sitting in the queue when the connection drops.
        api._writeCommand("VOL(-100)")
        assert api._write_queue, "expected the write to still be queued"

        await api.async_disconnect()
        assert api._write_queue == [], "a dropped connection must drop its queue"

        with mock.patch("asyncio.get_event_loop") as loop_mock:
            loop_mock.return_value.create_connection = AsyncMock(
                side_effect=make_create_conn(second_transport)
            )
            await api.async_connect()
        await flush_write_queue(api)
        await api.async_disconnect()

        assert not any(
            call.args[0] == "!VOL(-100)\r"
            for call in second_transport.write.call_args_list
        ), "a write queued before disconnect must never reach a later connection"
