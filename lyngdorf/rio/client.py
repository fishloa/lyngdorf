"""RioClient: the :84 wire-protocol connection - paced write queue,
connection monitor, reconnect loop, and callback dispatch.

Deliberately knows nothing about streaming state. `LyngdorfApi` (api.py)
subclasses this and adds exactly what coordinates the wire connection with
the now-playing poll loop - see that module's docstring for why those
three methods (`async_connect`, `_async_establish_connection`,
`async_disconnect`) live there instead of here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import traceback
from collections.abc import Callable

from ..base import register_in_list
from ..const import (
    COMMAND_PACING_MS,
    MONITOR_INTERVAL,
    RECONNECT_BACKOFF,
    RECONNECT_MAX_WAIT,
    RECONNECT_SCALE,
    SETUP_COMMAND_DELAY,
    Msg,
)
from ..models import LyngdorfModel
from ..remote import RemoteKey
from .protocol import LyngdorfProtocol, _find_closing_paren
from .queue import _absolute_setter_tokens_for_model, _coalesce_key, _QueuedWrite

_LOGGER = logging.getLogger(__package__)

_COMMAND_PACING_SECONDS = COMMAND_PACING_MS / 1000


class RioClient:
    """The :84 RIO protocol client: connection lifecycle below the level
    of "start a connection", the paced write queue, and callback dispatch.

    `_async_establish_connection` is declared here only as a signature for
    `_async_reconnect` to call through `self` - it has no implementation
    (raises `NotImplementedError`). `RioClient` is never instantiated
    directly; `LyngdorfApi` is its sole subclass and provides the real
    implementation, which also starts/stops the streaming poll around the
    base connection. This stub exists purely so mypy --strict has a
    declared attribute to check the call against; at runtime it is never
    reached, since `self` is always an `LyngdorfApi`.
    """

    setup_command_delay: float = SETUP_COMMAND_DELAY
    command_pacing_seconds: float = _COMMAND_PACING_SECONDS

    def __init__(self, host: str, model: LyngdorfModel) -> None:
        """Initialize the client."""
        self._connection_enabled = False
        self.host = host
        self._model: LyngdorfModel = model
        self._connect_lock = asyncio.Lock()
        self._healthy: bool | None = None
        self._last_message_time: float = -1.0
        self._reconnect_task: asyncio.Task[None] | None = None
        self._monitor_handle: asyncio.TimerHandle | None = None
        self._protocol: LyngdorfProtocol | None = None
        # Spelled out rather than a bare `Callable`: `register_in_list` is
        # generic over the element type, and a bare one leaves it with two
        # candidates to reconcile against the parameterised callback it is
        # handed, which mypy 1.x refuses to infer.
        self._callbacks: dict[str, list[Callable[[str, str], None]]] = {}
        self._notification_callbacks: list[Callable[[], None]] = []
        self._absolute_setter_tokens = _absolute_setter_tokens_for_model(model)
        self._write_queue: list[_QueuedWrite] = []
        self._write_queue_task: asyncio.Task[None] | None = None
        self._write_queue_ready = asyncio.Event()

    async def _async_establish_connection(self) -> None:
        """Establish a connection to the receiver.

        No implementation here - see the class docstring. `LyngdorfApi`
        provides the real body, which also owns the `DEFAULT_LYNGDORF_PORT`
        module global that `tests/reconnect_leak_test.py` monkeypatches on
        `lyngdorf.api` directly; that patch only works if the code reading
        the name is textually defined in `api.py`, which is the whole
        reason this method isn't implemented here.
        """
        raise NotImplementedError

    def _schedule_monitor(self) -> None:
        """Start the monitor task."""
        # Cancel any monitor already scheduled: every (re)connect calls this,
        # and without cancelling, monitors accumulate and each independently
        # fires its own keepalive-timeout disconnect/reconnect.
        self._stop_monitor()
        loop = asyncio.get_event_loop()
        self._monitor_handle = loop.call_later(MONITOR_INTERVAL, self._monitor)

    def _stop_monitor(self) -> None:
        """Stop the monitor task."""
        if self._monitor_handle is not None:
            self._monitor_handle.cancel()
            self._monitor_handle = None

    def _monitor(self) -> None:
        """Monitor the connection."""
        time_since_response = time.monotonic() - self._last_message_time
        if time_since_response > MONITOR_INTERVAL * 4:
            _LOGGER.info(
                "%s: Keep alive failed, disconnecting and reconnecting", self.host
            )
            if self._protocol is not None:
                self._protocol.close()
            self._handle_disconnected()
            return

        if time_since_response > MONITOR_INTERVAL and self._protocol:
            # Keep the connection alive. Which message to query is a
            # per-model choice (ModelConfig.keepalive_message) - the API
            # itself is generic and doesn't assume any particular command
            # is universally supported.
            if keepalive_message := self._model.keepalive_message:
                keepalive_command = self._model.lookup_command(keepalive_message)
                self._writeCommand(f"{keepalive_command}?")
        self._schedule_monitor()

    def _handle_disconnected(self) -> None:
        """Handle disconnected."""
        _LOGGER.debug("%s: disconnected", self.host)
        self._protocol = None
        self._stop_monitor()
        self._stop_write_queue()
        if not self._connection_enabled:
            return
        # Only ever run one reconnect loop. This handler can fire more than
        # once for a single drop (eof_received + connection_lost, and the
        # monitor's close() + explicit call); spawning a task each time opens
        # duplicate connections and orphans sockets on the device.
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._async_reconnect())

    async def _async_reconnect(self) -> None:
        """Reconnect to the receiver asynchronously."""
        backoff = RECONNECT_BACKOFF
        _LOGGER.debug("Trying to reconnect")
        while self._connection_enabled and not self.healthy:
            _LOGGER.debug("Trying to reconnect...")
            async with self._connect_lock:
                # Another attempt may have connected while we waited for the
                # lock; re-check under it so we don't establish (and leak) a
                # second connection.
                if self.healthy:
                    # mypy narrows `healthy` to False from the `while`
                    # condition and does not re-widen it across the await
                    # on the lock, so it calls this unreachable. It is
                    # not: re-checking UNDER the lock is the entire point,
                    # since another attempt may have connected while this
                    # one waited. Deleting it reinstates the duplicate-
                    # connection leak the comment above describes.
                    return  # type: ignore[unreachable]
                try:
                    await self._async_establish_connection()
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.error(
                        "%s: Unexpected exception on Lyngdorf reconnect",
                        self.host,
                        exc_info=True,
                    )
                else:
                    _LOGGER.info("%s: Lyngdorf reconnected", self.host)
                    return

            await asyncio.sleep(backoff)
            backoff = min(RECONNECT_MAX_WAIT, backoff * RECONNECT_SCALE)

    async def _writeSetup(self) -> None:
        for i, cmd in enumerate(self._model.setup_commands):
            if i > 0:
                await asyncio.sleep(self.setup_command_delay)
            self._writeCommand(cmd)

    def _writeCommand(self, command: str) -> None:
        """Enqueue a command for paced, coalescing delivery to the receiver.

        Writing straight to the transport with no pacing overflows a real
        device - see `COMMAND_PACING_MS` in const.py for the measured
        queue-depth cliff (https://github.com/fishloa/lyngdorf/issues/35).
        A Home Assistant volume-slider drag alone emits 10-30 commands in
        a second, comfortably past that cliff. Every runtime write -
        including this one - is therefore routed through a queue drained
        no faster than `COMMAND_PACING_MS` apart by `_drain_write_queue`,
        which keeps in-flight commands far under it.

        Repeated writes sharing an absolute-setter token (see
        `_coalesce_key`) collapse to the latest value rather than sending
        every intermediate one - turning a 30-command slider drag into
        one or two wire commands. Anything else (a relative/stepping
        command, sequential digits, navigation, a query) is never
        coalesced; see `_coalesce_key`'s docstring for why each case is
        safe or unsafe.

        Enqueueing itself is synchronous, since this is called from
        synchronous property setters (`receiver.volume = -30`). If
        nothing is currently draining the queue - no drain task has been
        started yet (still inside `_writeSetup`, before
        `_start_write_queue` runs), a test attached `_protocol` directly
        without going through `_async_establish_connection`, or there is
        no running event loop at all - flush the whole queue synchronously
        instead, the same fallback `_ensure_now_playing_task` takes when
        there is no loop to schedule onto.
        """
        key = _coalesce_key(command, self._absolute_setter_tokens)
        if key is not None:
            self._write_queue = [
                queued for queued in self._write_queue if queued.coalesce_key != key
            ]
        self._write_queue.append(_QueuedWrite(command=command, coalesce_key=key))

        if self._write_queue_task is not None and not self._write_queue_task.done():
            self._write_queue_ready.set()
            return

        while self._write_queue:
            queued = self._write_queue.pop(0)
            self._write_now(queued.command)

    def _write_now(self, command: str) -> None:
        """Write one command to the transport immediately, bypassing pacing.

        The drain task's per-item action, and `_writeCommand`'s fallback
        when nothing is draining the queue.
        """
        if self._protocol is not None:
            self._protocol.write(f"!{command}\r")
            _LOGGER.debug("%s send: '!%s'", self.host, command)

    def _start_write_queue(self) -> None:
        """Start the outbound-command drain task; safe to call repeatedly."""
        self._ensure_write_queue_task()

    def _ensure_write_queue_task(self) -> None:
        """Start the drain task unless one already exists.

        Mirrors `_ensure_now_playing_task`'s single-task guarantee, with
        one deliberate difference in how the reference is cleared. That
        poll's HTTP request keeps running in an executor thread for a
        while after `cancel()` returns, so its task reference is cleared
        only once the task genuinely finishes - restarting immediately
        would risk two polls owning a socket each on hardware with few
        slots. This task holds no such outlasting resource: once
        cancelled it drops out at its very next `await` with nothing left
        running, so `_stop_write_queue` clears the reference itself, and a
        reconnect is always free to start a fresh task right away.
        """
        if self._write_queue_task is not None:
            return
        try:
            task = asyncio.create_task(self._drain_write_queue())
        except RuntimeError:
            _LOGGER.debug(
                "%s: no running loop, not starting write-queue drain task",
                self.host,
            )
            return
        self._write_queue_task = task
        task.add_done_callback(self._on_write_queue_task_done)

    def _on_write_queue_task_done(self, task: asyncio.Task[None]) -> None:
        """Release the slot once the drain task genuinely finishes."""
        if self._write_queue_task is task:
            self._write_queue_task = None
        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            _LOGGER.error("%s: write-queue drain task failed", self.host, exc_info=exc)

    def _stop_write_queue(self) -> None:
        """Stop the drain task and drop anything still queued.

        Dropping rather than flushing: a queued write was paced for the
        connection that is going away, and by the time a later connection
        exists, whatever it represented (a volume set mid-drag, say) may
        no longer be what the caller or the device's own state wants -
        there is no reconnect-time signal that says otherwise. Nothing
        here depends on the write being retried to stay correct: the
        caller was a synchronous setter that already returned, same as
        any other write to a socket that drops mid-flight.
        """
        if self._write_queue_task is not None:
            self._write_queue_task.cancel()
            self._write_queue_task = None
        self._write_queue.clear()

    async def _drain_write_queue(self) -> None:
        """Background task: write queued commands to the transport, paced.

        Runs for the lifetime of one connection - see `_start_write_queue`/
        `_stop_write_queue`. Sleeps `COMMAND_PACING_MS` after *every*
        write, not only when another item is already queued: two
        commands enqueued individually, each arriving to find the queue
        momentarily empty, must still land `COMMAND_PACING_MS` apart, not
        back-to-back.
        """
        while True:
            if not self._write_queue:
                self._write_queue_ready.clear()
                await self._write_queue_ready.wait()
                continue
            queued = self._write_queue.pop(0)
            self._write_now(queued.command)
            await asyncio.sleep(self.command_pacing_seconds)

    def power_on(self, enabled: bool) -> None:
        if enabled:
            self._writeCommand(f"{self._model.lookup_command(Msg.POWER_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.POWER_OFF)}")

    def zone_b_power_on(self, enabled: bool) -> None:
        if enabled:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_POWER_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_POWER_OFF)}")

    def mute_enabled(self, mute: bool) -> None:
        if mute:
            self._writeCommand(f"{self._model.lookup_command(Msg.MUTE_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.MUTE_OFF)}")

    def zone_b_mute_enabled(self, mute: bool) -> None:
        if mute:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_MUTE_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_MUTE_OFF)}")

    def volume_up(self) -> None:
        self._writeCommand(self._model.volume_up_command())

    def volume_down(self) -> None:
        self._writeCommand(self._model.volume_down_command())

    def zone_b_volume_up(self) -> None:
        self._writeCommand(self._model.zone_b_volume_up_command())

    def zone_b_volume_down(self) -> None:
        self._writeCommand(self._model.zone_b_volume_down_command())

    def volume(self, volume: float) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.VOLUME)}({volume*10.0:.0f})"
        )

    def zone_b_volume(self, volume: float) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ZONE_B_VOLUME)}({volume*10.0:.0f})"
        )

    def change_source(self, source: int) -> None:
        self._writeCommand(f"{self._model.lookup_command(Msg.SOURCE)}({source})")

    def change_zone_b_source(self, zone_b_source: int) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ZONE_B_SOURCE)}({zone_b_source})"
        )

    def change_sound_mode(self, sound_mode: int) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.AUDIO_MODE)}({sound_mode})"
        )

    def change_hdmi_main_out(self, hdmi_index: int) -> None:
        self._writeCommand(f"HDMIMAINOUT({hdmi_index})")

    def change_room_perfect_position(self, room_perfect_position_index: int) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ROOM_PERFECT_POSITION)}({room_perfect_position_index})"
        )

    def change_lipsync(self, lipsync: int) -> None:
        self._writeCommand(f"{self._model.lookup_command(Msg.LIP_SYNC)}({lipsync})")

    def change_voicing(self, voicing: int) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ROOM_PERFECT_VOICING)}({voicing})"
        )

    def change_trim_bass(self, trim: float) -> None:
        # Scale is model-specific (10 = 1dB on MP/P, 1 = 1dB on TDAI) - see
        # ModelConfig.trim_bass_treble_scale.
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_BASS)}"
            f"({trim * self._model.trim_bass_treble_scale():.0f})"
        )

    def change_trim_centre(self, trim: float) -> None:
        # Channel trims are MP-only (see ModelConfig.has_surround) - the
        # TDAI family has no equivalent command at all, so unlike
        # bass/treble above there is no per-model scale to apply here.
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_CENTRE)}({trim*10.0:.0f})"
        )

    def change_trim_height(self, trim: float) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_HEIGHT)}({trim*10.0:.0f})"
        )

    def change_trim_lfe(self, trim: float) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_LFE)}({trim*10.0:.0f})"
        )

    def change_trim_surround(self, trim: float) -> None:
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_SURROUND)}({trim*10.0:.0f})"
        )

    def change_trim_treble(self, trim: float) -> None:
        # Scale is model-specific (10 = 1dB on MP/P, 1 = 1dB on TDAI) - see
        # ModelConfig.trim_bass_treble_scale.
        self._writeCommand(
            f"{self._model.trim_treble_set_command()}"
            f"({trim * self._model.trim_bass_treble_scale():.0f})"
        )

    def trim_bass_up(self) -> None:
        if command := self._model.trim_bass_up_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step bass trim; ignoring", self.host, self._model
            )

    def trim_bass_down(self) -> None:
        if command := self._model.trim_bass_down_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step bass trim; ignoring", self.host, self._model
            )

    def trim_centre_up(self) -> None:
        self._writeCommand(self._model.trim_centre_up_command())

    def trim_centre_down(self) -> None:
        self._writeCommand(self._model.trim_centre_down_command())

    def trim_height_up(self) -> None:
        self._writeCommand(self._model.trim_height_up_command())

    def trim_height_down(self) -> None:
        self._writeCommand(self._model.trim_height_down_command())

    def trim_lfe_up(self) -> None:
        self._writeCommand(self._model.trim_lfe_up_command())

    def trim_lfe_down(self) -> None:
        self._writeCommand(self._model.trim_lfe_down_command())

    def trim_surround_up(self) -> None:
        self._writeCommand(self._model.trim_surround_up_command())

    def trim_surround_down(self) -> None:
        self._writeCommand(self._model.trim_surround_down_command())

    def trim_treble_up(self) -> None:
        if command := self._model.trim_treble_up_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step treble trim; ignoring", self.host, self._model
            )

    def trim_treble_down(self) -> None:
        if command := self._model.trim_treble_down_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step treble trim; ignoring", self.host, self._model
            )

    def send_remote_key(self, key: RemoteKey) -> None:
        """Send one remote-key press to the device.

        Remote keys are write-only and sequential - the device never
        replies, and order/count is the whole meaning of a batch (see
        `Receiver.send_remote_commands`) - so a press must never
        coalesce with another queued one. `_writeCommand` already
        guarantees that with no extra logic here: coalescing only
        applies to a wire token that is both shaped like an absolute
        setter *and* a member of `_absolute_setter_tokens`, which is
        built from `ABSOLUTE_SETTER_MESSAGES` (`Msg` lookups) alone.
        Remote keys were pulled out of `Msg` entirely (see
        `lyngdorf/remote.py`), so a remote key's wire token can never be
        a member of that set for any model, on any family's protocol.
        """
        self._writeCommand(self._model.lookup_remote_key(key))

    def _process_event(self, message: str) -> None:
        """Process a realtime event."""

        _LOGGER.debug("%s recv: '%s'", self.host, message)
        # print("\r"+message+"\r")
        self._last_message_time = time.monotonic()
        if message.startswith("!"):
            cmd: str = ""
            first: str = ""
            second: str = ""
            message = message[1:]
            open_index = message.find("(")
            close_index = (
                _find_closing_paren(message, open_index + 1) if open_index > 1 else -1
            )
            if close_index > open_index:
                cmd = message[:open_index]
                first = message[open_index + 1 : close_index]
                second = message[close_index + 1 :]
            else:
                cmd = message

            try:
                pong_command = self._model.lookup_command(Msg.PONG)
            except KeyError:
                pong_command = None
            if cmd == pong_command:
                return

            if len(second) > 0 and second.startswith('"') and second.endswith('"'):
                second = second[1:-1]
            asyncio.create_task(self._async_run_callbacks(cmd, first, second))
            asyncio.create_task(self._notify_notification_callbacks())

    def register_notification_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback, returning a callable that unregisters it.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return register_in_list(self._notification_callbacks, callback)

    def un_register_notification_callback(self, callback: Callable[[], None]) -> None:
        with contextlib.suppress(ValueError):
            self._notification_callbacks.remove(callback)

    async def _notify_notification_callbacks(self) -> None:
        for callback in self._notification_callbacks:
            try:
                callback()
            except Exception:
                # We don't want a single bad callback to trip up the
                # whole system and prevent further execution
                # TIM. TODO. need to log the stack trace of the error found here, as at the moment v hard to find errors

                _LOGGER.error(
                    "%s: Event callback caused an unhandled exception '%s' (%s)",
                    self.host,
                    traceback.format_exc(),
                    callback,
                )

    def register_callback(
        self, command: str, callback: Callable[[str, str], None]
    ) -> Callable[[], None]:
        """Register a callback handler for an event type.

        Returns an idempotent unsubscribe that removes only this callback
        from this command's list, leaving other commands' callbacks (and
        other callbacks on the same command) untouched.
        """
        if command not in self._callbacks.keys():
            self._callbacks[command] = []
        return register_in_list(self._callbacks[command], callback)

    async def _async_run_callbacks(
        self, command: str, param1: str, param2: str
    ) -> None:
        """Handle triggering the registered callbacks for the event."""
        if command in self._callbacks.keys():
            for callback in self._callbacks[command]:
                try:
                    # _LOGGER.debug("Command %s callback (%s, %s) calling %s", command, param1, param2, callback)
                    callback(param1, param2)
                except Exception:  # pylint: disable=broad-except
                    # We don't want a single bad callback to trip up the
                    # whole system and prevent further execution
                    # TIM. TODO. need to log the stack trace of the error found here, as at the moment v hard to find errors

                    _LOGGER.error(
                        "%s: Event callback caused an unhandled exception '%s' for Command %s callback (%s, %s) calling %s",
                        self.host,
                        traceback.format_exc(),
                        command,
                        param1,
                        param2,
                        callback,
                    )

    @property
    def connected(self) -> bool:
        """Return True if telnet connection is enabled."""
        return self._connection_enabled

    @property
    def healthy(self) -> bool:
        """Return True if the connection is healthy."""
        return self._protocol is not None and self._protocol.connected
