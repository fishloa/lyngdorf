#!/usr/bin/env python3
"""
Lyngdorf Audio Control Library - API Module.

Handles TCP/IP communication with Lyngdorf receivers on port 84.
Implements asyncio protocol for command/response handling.

Supported models are defined by `LyngdorfModel` (see `lyngdorf/models/`);
the README carries the human-readable list.

:license: MIT, see LICENSE for more details.
"""

import asyncio
import contextlib
import dataclasses
import logging
import re
import time
import traceback
from asyncio import timeout as asyncio_timeout
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from .base import register_in_list
from .const import (
    ABSOLUTE_SETTER_MESSAGES,
    COMMAND_PACING_MS,
    DEFAULT_LYNGDORF_PORT,
    MONITOR_INTERVAL,
    NOW_PLAYING_POLL_TIMEOUT,
    NOW_PLAYING_POSITION_PATH,
    PLAY_MODE_PATH,
    POSITION_DRIFT_TOLERANCE_MS,
    RECONNECT_BACKOFF,
    RECONNECT_MAX_WAIT,
    RECONNECT_SCALE,
    SETUP_COMMAND_DELAY,
    STREAMMAGIC_PORT,
    LyngdorfModel,
    Msg,
)
from .exceptions import LyngdorfUnsupportedError
from .states import Control, PlaybackState, PlayMode, Repeat
from .streaming import (
    NowPlaying,
    StreamMagicSession,
    async_activate_control,
    async_fetch_now_playing,
    async_fetch_play_mode,
    async_fetch_play_modes,
    async_fetch_position,
    async_init_now_playing_queue,
    async_poll_now_playing_events,
    async_subscribe_now_playing,
    parse_play_mode_events,
    parse_play_modes,
    parse_position_events,
)
from .streaming import (
    async_seek as _seek,
)
from .streaming import (
    async_set_play_mode as _set_play_mode,
)

_LOGGER = logging.getLogger(__package__)

_COMMAND_PACING_SECONDS = COMMAND_PACING_MS / 1000

# Shape of an absolute-setter command: a bare uppercase token followed by a
# single parenthesised integer, e.g. "VOL(-300)" or "TRIMBASS(20)". Chosen
# deliberately narrow rather than a bare `TOKEN(.*)`: every write this
# library actually sends in that family (volume, zone B volume, the six
# trims, lipsync, balance) is a signed integer, so anything else matching
# `TOKEN(...)` but not this exact shape is left alone rather than guessed
# at - see `_coalesce_key`.
_ABSOLUTE_SETTER_SHAPE = re.compile(r"^([A-Z][A-Z0-9_]*)\(-?\d+\)$")


def _absolute_setter_tokens_for_model(model: LyngdorfModel) -> frozenset[str]:
    """The wire tokens this model uses for an absolute-setter message.

    Derived from `ABSOLUTE_SETTER_MESSAGES` (const.py) via
    `model.lookup_command` rather than hardcoded as literal strings,
    because the wire token for the same message differs by family - e.g.
    `Msg.TRIM_BASS` is `TRIMBASS` on MP/P but `BASS` on TDAI. A message a
    given model does not define (`KeyError`) simply contributes no token,
    same as any other unsupported message lookup elsewhere in this file.
    """
    tokens = set()
    for msg in ABSOLUTE_SETTER_MESSAGES:
        try:
            tokens.add(model.lookup_command(msg))
        except KeyError:
            continue
    return frozenset(tokens)


def _coalesce_key(command: str, absolute_setter_tokens: frozenset[str]) -> str | None:
    """The coalescing key for `command`, or None if it must never coalesce.

    Only a command shaped like an absolute setter (see
    `_ABSOLUTE_SETTER_SHAPE`) *and* whose token is one this model actually
    uses for a message in `ABSOLUTE_SETTER_MESSAGES` can coalesce - for
    those, the latest value fully replaces the meaning of an earlier
    queued one. Everything else keeps no key and is therefore never
    coalesced:

    - a relative/stepping command (`VOLUP`, `VOL+`, `RPVOI-`, ...) has no
      parenthesised value at all, so it never matches the shape;
    - a query (`VOL?`) likewise never matches the shape;
    - sequential input - the `NUM(0)`..`NUM(9)` digits, where `NUM` is not
      an absolute-setter token for any model - matches the shape but is
      filtered out by the token check, because order and count are the
      whole meaning there.
    """
    match = _ABSOLUTE_SETTER_SHAPE.match(command)
    if match is None:
        return None
    token = match.group(1)
    if token not in absolute_setter_tokens:
        return None
    return token


@dataclasses.dataclass(frozen=True, slots=True)
class _QueuedWrite:
    """One command waiting to be written, and its coalescing key (if any)."""

    command: str
    coalesce_key: str | None


def _find_closing_paren(message: str, start: int) -> int:
    """Index of the first ``)`` at or after ``start`` that is not inside a
    quoted section, or -1 if there is none.

    A plain ``find(")")`` is wrong for any model that puts the name inside
    the parens. TDAI replies are shaped ``!SRCNAME(0,"Digital 1 (Coax)")``,
    so the first ``)`` is the one closing "(Coax)" and the name is cut short.
    Scanning past quoted sections keeps that intact while leaving the MP and
    P shape - ``!SRC(0)"HDMI"``, name outside the parens - parsed exactly as
    before. Note this is why ``rfind`` would not do instead: on the MP shape
    the last ``)`` is the one inside the name.
    """
    in_quotes = False
    for index in range(start, len(message)):
        character = message[index]
        if character == '"':
            in_quotes = not in_quotes
        elif character == ")" and not in_quotes:
            return index
    return -1


def _is_position_discontinuity(
    position_ms: int | None,
    previous_ms: int | None,
    previous_at: datetime | None,
    now: datetime,
    current_state: PlaybackState | None,
    previous_state: PlaybackState | None,
    current_title: str | None,
    previous_title: str | None,
) -> bool:
    """Whether a new position report is a discontinuity, not ordinary
    once-a-second progression.

    See `LyngdorfApi.register_position_jump_callback` for what this
    distinction is for and why it matters. A report counts as a
    discontinuity when any of the following hold:

    - there was no previous position, or the new one is None (the device
      just started reporting, or has gone idle/powered off)
    - playback is a *known* state other than `PlaybackState.PLAYING` (a
      pause, a stop, or a paused track being scrubbed) - every report in a
      known non-playing state counts, since position has no business moving
      on its own outside that state. An *unknown* state (`None` - a
      transient metadata-fetch failure leaves `_now_playing` unset) does
      NOT by itself count: treating "unknown" the same as "not playing"
      would classify every report as a discontinuity for as long as the
      fetch stays broken, which is precisely the 1Hz storm this callback
      exists to prevent. The remaining checks below still apply while the
      state is unknown, so a real seek during that window is still caught
      by drift.
    - the playback state changed since the previous report (this still
      fires once on the transition into/out of an unknown state, since
      `None` compares unequal to a known state - just not on every report
      thereafter, because the state then stops changing)
    - the track changed (compared by title - `NowPlaying` does not retain
      a distinct track identifier such as `playId`)
    - the observed position differs from where the clock says it should be
      - the previous position plus wall-clock time elapsed since it was
        recorded - by more than `POSITION_DRIFT_TOLERANCE_MS`

    A steady ~1Hz progression while playing satisfies none of these, which
    is the behaviour a consumer subscribing only to
    `register_position_callback` (not this) must keep seeing - including
    while the playback state happens to be unknown.

    `current_state`/`current_title` can be one report stale relative to
    the device: the poll loop calls `_update_position` with the position
    from the same queue event, then only *afterwards* re-fetches
    now-playing metadata to catch a state/track change (position arrives
    inline; metadata needs a round trip - see `_poll_now_playing`, and do
    not reorder that for this function's sake). So a pause or track change
    is compared here against the pre-change state on the report it
    happens, and detected as a discontinuity one report later, once the
    metadata refetch has landed and this function next runs. That is a
    one-report delay in detection, not a missed discontinuity - it still
    fires exactly once, just deferred - and is covered by
    `test_poll_loop_order_defers_pause_detection_by_one_report`.
    """
    if previous_ms is None or position_ms is None:
        return True
    if current_state is not None and current_state != PlaybackState.PLAYING:
        return True
    if current_state != previous_state:
        return True
    if current_title != previous_title:
        return True
    if previous_at is None:
        return True
    elapsed_ms = (now - previous_at).total_seconds() * 1000
    expected_ms = previous_ms + elapsed_ms
    return abs(position_ms - expected_ms) > POSITION_DRIFT_TOLERANCE_MS


class LyngdorfProtocol(asyncio.Protocol):
    """Protocol for the Lyngdorf interface."""

    def __init__(
        self,
        on_message: Callable[[str], None],
        on_connection_lost: Callable[[], None],
    ) -> None:
        """Initialize the protocol."""
        self._buffer = b""
        self.transport: asyncio.Transport | None = None
        self._on_message = on_message
        self._on_connection_lost = on_connection_lost

    @property
    def connected(self) -> bool:
        """Return True if transport is connected."""
        if self.transport is None:
            return False
        return not self.transport.is_closing()

    def write(self, data: str) -> None:
        """Write data to the transport."""
        if self.transport is None or self.transport.is_closing():
            return
        self.transport.write(data.encode("utf-8"))

    def close(self) -> None:
        """Close the connection."""
        if self.transport is not None:
            self.transport.close()

    def eof_received(self):
        _LOGGER.info("Pipe closed")
        self.close()
        self._on_connection_lost()
        return True

    def data_received(self, data: bytes) -> None:
        """Handle data received.

        Messages are terminated with CR, but the TDAI family follows that
        CR with an LF. Splitting on CR alone would leave the LF at the head
        of the next message, where it defeats the leading-"!" check in
        LyngdorfApi._process_event and the message is dropped in silence -
        so every reply after the first goes missing. Strip the framing off
        each line rather than assuming which terminator a model uses.
        """
        self._buffer += data
        while b"\r" in self._buffer:
            line, _, self._buffer = self._buffer.partition(b"\r")
            with contextlib.suppress(UnicodeDecodeError):
                message = line.decode("utf-8").strip("\r\n")
                if message:
                    self._on_message(message)

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore
        """Handle connection made."""
        _LOGGER.debug("connection made")
        self.transport = transport  # type: ignore

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost."""
        self.close()
        self._on_connection_lost()
        return super().connection_lost(exc)


class LyngdorfApi:
    """Handle responses from the Lyngdorf interface."""

    # Class attribute (not a plain module constant) so tests can override it
    # per-instance/class without affecting real connections' pacing.
    setup_command_delay: float = SETUP_COMMAND_DELAY

    # Same reasoning as `setup_command_delay` above, for the runtime
    # outbound command queue's own pacing (see `_drain_write_queue`).
    command_pacing_seconds: float = _COMMAND_PACING_SECONDS

    streammagic_port: int = STREAMMAGIC_PORT

    def __init__(self, host: str, model: LyngdorfModel):
        """Initialize the client."""
        self._connection_enabled = False
        self.host = host
        self._model: LyngdorfModel = model
        self._connect_lock = asyncio.Lock()
        self._healthy: bool | None = None
        self._last_message_time: float = -1.0
        self._reconnect_task: asyncio.Task | None = None
        self._monitor_handle: asyncio.TimerHandle | None = None
        self._protocol: LyngdorfProtocol | None = None
        # Spelled out rather than a bare `Callable`: `register_in_list` is
        # generic over the element type, and a bare one leaves it with two
        # candidates to reconcile against the parameterised callback it is
        # handed, which mypy 1.x refuses to infer.
        self._callbacks: dict[str, list[Callable[[str, str], None]]] = {}
        self._notification_callbacks: list[Callable[[], None]] = []
        self._now_playing: NowPlaying | None = None
        self._now_playing_callbacks: list[Callable[[NowPlaying | None], None]] = []
        self._now_playing_task: asyncio.Task | None = None
        self._now_playing_wanted = False
        self._position_ms: int | None = None
        self._position_updated_at: datetime | None = None
        self._position_callbacks: list[Callable[[int | None], None]] = []
        self._position_jump_callbacks: list[Callable[[int | None], None]] = []
        # Snapshot of what was true *at the previous position report*, used
        # only to detect discontinuities - see `_update_position`. Distinct
        # from `_now_playing`/`_play_mode`, which reflect the current state
        # and may have already moved on by the time the next position
        # report arrives.
        self._position_prev_state: PlaybackState | None = None
        self._position_prev_title: str | None = None
        self._play_mode: PlayMode | None = None
        self._play_mode_callbacks: list[Callable[[PlayMode | None], None]] = []
        self._global_play_modes: frozenset[PlayMode] = frozenset()
        # Outbound command queue - see `_writeCommand`/`_drain_write_queue`.
        # Computed once: which wire tokens count as absolute setters is
        # fixed for the lifetime of a model.
        self._absolute_setter_tokens = _absolute_setter_tokens_for_model(model)
        self._write_queue: list[_QueuedWrite] = []
        self._write_queue_task: asyncio.Task | None = None
        # asyncio.Event does not bind to a loop at construction time (3.10+),
        # so this is safe to create here even though __init__ itself may run
        # with no loop running.
        self._write_queue_ready = asyncio.Event()

    async def async_connect(self) -> None:
        """Connect to the receiver asynchronously."""
        _LOGGER.debug("%s: connecting", self.host)
        if self._connection_enabled:
            return
        await self._async_establish_connection()

    async def _async_establish_connection(self) -> None:
        """Establish a connection to the receiver."""
        _LOGGER.info("%s: establishing connection", self.host)
        loop = asyncio.get_event_loop()
        try:
            async with asyncio_timeout(2.0):
                transport_protocol = await loop.create_connection(
                    lambda: LyngdorfProtocol(
                        on_connection_lost=self._handle_disconnected,
                        on_message=self._process_event,
                    ),
                    self.host,
                    DEFAULT_LYNGDORF_PORT,
                )
        except TimeoutError as err:
            _LOGGER.debug("%s: Timeout exception on connect", self.host)
            raise TimeoutError(f"TimeoutException: {err}", "connect") from err
        except ConnectionRefusedError as err:
            _LOGGER.debug("%s: Connection refused on connect", self.host, exc_info=True)
            raise ConnectionRefusedError(
                f"ConnectionRefusedError: {err}", "connect"
            ) from err
        # Never overwrite a live protocol without closing it first: a stale
        # transport left dangling stays ESTABLISHED on the device and leaks a
        # control-port slot (the TDAI family allows only a few connections).
        if self._protocol is not None:
            self._protocol.close()
        self._protocol = cast(LyngdorfProtocol, transport_protocol[1])  # type: ignore
        self._connection_enabled = True
        self._last_message_time = time.monotonic()
        self._schedule_monitor()
        await self._writeSetup()
        # Started only after the setup burst, not before: `_writeSetup`
        # already paces itself with `setup_command_delay` and writes
        # straight to the transport (see `_writeCommand`'s immediate-flush
        # fallback, which applies here since no drain task exists yet).
        # Starting the queue earlier would pace the same burst twice over.
        self._start_write_queue()
        if self._model.has_streaming_feature():
            self._start_now_playing_poll()
        _LOGGER.debug("%s: connection complete", self.host)

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

    def _start_now_playing_poll(self) -> None:
        """Ask for the poll to be running; safe to call repeatedly."""
        self._now_playing_wanted = True
        self._ensure_now_playing_task()

    def _ensure_now_playing_task(self) -> None:
        """Start the poll task unless one already exists.

        `_now_playing_task` is the single guard against running two polls
        at once - which would double the request rate and hold a second
        connection to a device with few slots. It is cleared only when a
        task has genuinely finished (see `_on_now_playing_task_done`),
        never at cancellation time: a cancelled task keeps running until
        the loop next gets to it, and its HTTP request keeps running in
        its executor thread until the response arrives, so it still owns
        its socket for a while after `cancel()` returns.
        """
        if self._now_playing_task is not None:
            return

        coro = self._poll_now_playing()
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            # Reached from the synchronous power notification callback,
            # which normally runs on the event loop but need not - and
            # with no loop there is nothing to schedule the poll onto.
            # Connecting starts it again, so this cannot strand the poll.
            coro.close()
            _LOGGER.debug(
                "%s: no running loop, not starting now-playing poll", self.host
            )
            return

        self._now_playing_task = task
        task.add_done_callback(self._on_now_playing_task_done)

    def _on_now_playing_task_done(self, task: asyncio.Task) -> None:
        """Release the slot, and restart if the poll is still wanted.

        A task that ends while still wanted (its loop saw the connection
        drop, say) would otherwise leave the poll silently stopped until
        the next reconnect or power notification.
        """
        if self._now_playing_task is task:
            self._now_playing_task = None

        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            # Deliberately not restarted: an immediately-failing task
            # would otherwise spin, hammering the device.
            _LOGGER.debug("%s: now-playing poll task failed", self.host, exc_info=exc)
            return

        if self._now_playing_wanted and self._connection_enabled:
            self._ensure_now_playing_task()

    def _stop_now_playing_poll(self) -> None:
        self._now_playing_wanted = False
        if self._now_playing_task is not None:
            self._now_playing_task.cancel()

    def set_power_state(self, power_on: bool) -> None:
        """Follow device power with the now-playing poll.

        A powered-off device has nothing to play, so polling it is pure
        traffic against hardware that has few connection slots - and the
        poll runs about once a second whenever position is subscribed.
        Stopping on power-off also drops the kept-alive socket, leaving
        only the :84 control connection while the device is off.

        Called on every power notification, including repeats, so both
        start and stop must be idempotent - they are.
        """
        if not self._model.has_streaming_feature():
            return

        if power_on:
            self._start_now_playing_poll()
            return

        self._stop_now_playing_poll()
        # Nothing is playing on a device that is off; leaving the last
        # track cached would have consumers show stale now-playing state
        # for as long as it stayed off.
        self._update_now_playing(None)
        self._update_position(None)
        self._update_play_mode(None)

    async def async_disconnect(self) -> None:
        """Close the connection to the receiver asynchronously."""
        async with self._connect_lock:
            self._connection_enabled = False
            self._stop_monitor()
            self._stop_now_playing_poll()
            self._stop_write_queue()
            if self._reconnect_task is not None:
                self._reconnect_task.cancel()
                self._reconnect_task = None
            if self._protocol is not None:
                self._protocol.close()
                self._protocol = None

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
                    return
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

    async def _writeSetup(self):
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

    def _on_write_queue_task_done(self, task: asyncio.Task) -> None:
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

    def power_on(self, enabled: bool):
        if enabled:
            self._writeCommand(f"{self._model.lookup_command(Msg.POWER_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.POWER_OFF)}")

    def zone_b_power_on(self, enabled: bool):
        if enabled:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_POWER_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_POWER_OFF)}")

    def mute_enabled(self, mute: bool):
        if mute:
            self._writeCommand(f"{self._model.lookup_command(Msg.MUTE_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.MUTE_OFF)}")

    def zone_b_mute_enabled(self, mute: bool):
        if mute:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_MUTE_ON)}")
        else:
            self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_MUTE_OFF)}")

    def volume_up(self):
        self._writeCommand(self._model.volume_up_command())

    def volume_down(self):
        self._writeCommand(self._model.volume_down_command())

    def zone_b_volume_up(self):
        self._writeCommand(self._model.zone_b_volume_up_command())

    def zone_b_volume_down(self):
        self._writeCommand(self._model.zone_b_volume_down_command())

    def volume(self, volume: float):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.VOLUME)}({volume*10.0:.0f})"
        )

    def zone_b_volume(self, volume: float):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ZONE_B_VOLUME)}({volume*10.0:.0f})"
        )

    def change_source(self, source: int):
        self._writeCommand(f"{self._model.lookup_command(Msg.SOURCE)}({source})")

    def change_zone_b_source(self, zone_b_source: int):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ZONE_B_SOURCE)}({zone_b_source})"
        )

    def change_sound_mode(self, sound_mode: int):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.AUDIO_MODE)}({sound_mode})"
        )

    def change_hdmi_main_out(self, hdmi_index: int):
        self._writeCommand(f"HDMIMAINOUT({hdmi_index})")

    def change_room_perfect_position(self, room_perfect_position_index: int):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ROOM_PERFECT_POSITION)}({room_perfect_position_index})"
        )

    def change_lipsync(self, lipsync: int):
        self._writeCommand(f"{self._model.lookup_command(Msg.LIP_SYNC)}({lipsync})")

    def change_voicing(self, voicing: int):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.ROOM_PERFECT_VOICING)}({voicing})"
        )

    def change_trim_bass(self, trim: float):
        # Scale is model-specific (10 = 1dB on MP/P, 1 = 1dB on TDAI) - see
        # ModelConfig.trim_bass_treble_scale.
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_BASS)}"
            f"({trim * self._model.trim_bass_treble_scale():.0f})"
        )

    def change_trim_centre(self, trim: float):
        # Channel trims are MP-only (see ModelConfig.has_surround) - the
        # TDAI family has no equivalent command at all, so unlike
        # bass/treble above there is no per-model scale to apply here.
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_CENTRE)}({trim*10.0:.0f})"
        )

    def change_trim_height(self, trim: float):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_HEIGHT)}({trim*10.0:.0f})"
        )

    def change_trim_lfe(self, trim: float):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_LFE)}({trim*10.0:.0f})"
        )

    def change_trim_surround(self, trim: float):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_SURROUND)}({trim*10.0:.0f})"
        )

    def change_trim_treble(self, trim: float):
        # Scale is model-specific (10 = 1dB on MP/P, 1 = 1dB on TDAI) - see
        # ModelConfig.trim_bass_treble_scale.
        self._writeCommand(
            f"{self._model.trim_treble_set_command()}"
            f"({trim * self._model.trim_bass_treble_scale():.0f})"
        )

    def trim_bass_up(self):
        if command := self._model.trim_bass_up_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step bass trim; ignoring", self.host, self._model
            )

    def trim_bass_down(self):
        if command := self._model.trim_bass_down_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step bass trim; ignoring", self.host, self._model
            )

    def trim_centre_up(self):
        self._writeCommand(self._model.trim_centre_up_command())

    def trim_centre_down(self):
        self._writeCommand(self._model.trim_centre_down_command())

    def trim_height_up(self):
        self._writeCommand(self._model.trim_height_up_command())

    def trim_height_down(self):
        self._writeCommand(self._model.trim_height_down_command())

    def trim_lfe_up(self):
        self._writeCommand(self._model.trim_lfe_up_command())

    def trim_lfe_down(self):
        self._writeCommand(self._model.trim_lfe_down_command())

    def trim_surround_up(self):
        self._writeCommand(self._model.trim_surround_up_command())

    def trim_surround_down(self):
        self._writeCommand(self._model.trim_surround_down_command())

    def trim_treble_up(self):
        if command := self._model.trim_treble_up_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step treble trim; ignoring", self.host, self._model
            )

    def trim_treble_down(self):
        if command := self._model.trim_treble_down_command():
            self._writeCommand(command)
        else:
            _LOGGER.warning(
                "%s: model %s cannot step treble trim; ignoring", self.host, self._model
            )

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
    def now_playing(self) -> NowPlaying | None:
        """Current now-playing metadata, or None if idle/unavailable."""
        return self._now_playing

    def register_now_playing_callback(
        self, callback: Callable[[NowPlaying | None], None]
    ) -> Callable[[], None]:
        """Register a callback, returning a callable that unregisters it.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return register_in_list(self._now_playing_callbacks, callback)

    @property
    def position_ms(self) -> int | None:
        """Elapsed playback position in milliseconds, or None if unknown.

        Pair with `NowPlaying.duration_ms` for a progress percentage.
        Tracked separately from `now_playing` because it updates about
        once a second, which would otherwise churn that object and every
        metadata consumer along with it.
        """
        return self._position_ms

    @property
    def position_updated_at(self) -> datetime | None:
        """When `position_ms` was last refreshed from the device.

        Lets a consumer extrapolate the current position between updates
        instead of displaying a value that visibly lags.
        """
        return self._position_updated_at

    def register_position_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        """Register a callback, returning a callable that unregisters it.

        Fires on every raw position change, including the ordinary
        once-a-second progression while playing - for a consumer that
        genuinely wants a live counter. For a consumer where each call
        costs something (a Home Assistant entity state write, say), use
        `register_position_jump_callback` instead.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return register_in_list(self._position_callbacks, callback)

    def register_position_jump_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        """Register a callback for position *discontinuities* only.

        Fires when the position does something other than advance with the
        clock: a seek, a track change, a play or pause, or the stream
        drifting from where it should be. It does not fire for the ordinary
        once-a-second progression, so a consumer that writes state on every
        call stays cheap.

        Use this rather than `register_position_callback` when each call
        costs something - a Home Assistant entity state write, say, which
        fans out over websockets and re-evaluates every automation bound to
        that entity.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return register_in_list(self._position_jump_callbacks, callback)

    @property
    def play_mode(self) -> PlayMode | None:
        """Current shuffle/repeat mode, or None if unknown/unavailable.

        None on a model without a streaming module, same as `now_playing`
        and `position_ms`. Also None when the device's current wire value
        is not one `PlayMode.from_wire` recognises - forwards compatible
        with a device that has grown a mode this library does not model,
        by degrading to "unknown" rather than raising.
        """
        if not self._model.has_streaming_feature():
            return None
        return self._play_mode

    @property
    def shuffle(self) -> bool | None:
        """Current shuffle setting, or None if unknown/unavailable."""
        mode = self.play_mode
        return mode.shuffle if mode is not None else None

    @property
    def repeat(self) -> Repeat | None:
        """Current repeat setting, or None if unknown/unavailable."""
        mode = self.play_mode
        return mode.repeat if mode is not None else None

    def register_play_mode_callback(
        self, callback: Callable[[PlayMode | None], None]
    ) -> Callable[[], None]:
        """Register a callback, returning a callable that unregisters it.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return register_in_list(self._play_mode_callbacks, callback)

    @property
    def available_controls(self) -> frozenset[Control]:
        """Transport actions the current source offers, or empty."""
        if not self._model.has_streaming_feature() or self._now_playing is None:
            return frozenset()
        return self._now_playing.controls

    @property
    def available_play_modes(self) -> frozenset[PlayMode]:
        """Shuffle/repeat modes the current source offers, or empty.

        The union of the current source's own advertised set
        (`NowPlaying.play_modes`) and the device's global play-mode enum
        (`_global_play_modes`) - not a preference between one and the
        other. Measured against a real MP-60 (firmware 5.4.2): both of the
        device's own lists are partial views of the same six-value 2x3
        grid. The per-source `controls.playMode` in the now-playing
        payload omits `normal` entirely - it lists only `shuffle`,
        `repeatOne`, `repeatAll`, `shuffleRepeatOne`, `shuffleRepeatAll` -
        while the global `settings:/mediaPlayer/playModes` enum includes
        `normal` but omits the `repeatAll` variants. This method used to
        prefer the per-source list whenever it was non-empty, falling back
        to the global enum only when the per-source list was empty
        outright; that made `normal` (shuffle=False, repeat=Repeat.OFF -
        the device's own default/null state) permanently unreachable on
        any source that advertises per-source modes at all, which broke
        turning shuffle or repeat back off (`async_set_shuffle(False)` /
        `async_set_repeat(Repeat.OFF)` from a non-normal mode). Taking the
        union instead is not a guess: every member of it comes from
        something the device itself declared.
        """
        if not self._model.has_streaming_feature() or self._now_playing is None:
            return frozenset()
        return self._now_playing.play_modes | self._global_play_modes

    @property
    def can_shuffle(self) -> bool:
        """Whether shuffle can be toggled independently of the current mode.

        True when some advertised mode differs from the current one only
        in its `shuffle` field - i.e. there is a mode to switch to that
        keeps the current repeat setting.
        """
        current = self.play_mode
        if current is None:
            return False
        return any(
            mode.repeat == current.repeat and mode.shuffle != current.shuffle
            for mode in self.available_play_modes
        )

    @property
    def available_repeat_modes(self) -> frozenset[Repeat]:
        """Repeat values reachable from the current shuffle setting."""
        current = self.play_mode
        if current is None:
            return frozenset()
        return frozenset(
            mode.repeat
            for mode in self.available_play_modes
            if mode.shuffle == current.shuffle
        )

    def _require_control(self, control: Control) -> None:
        if control not in self.available_controls:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer {control!r} "
                f"(available: {sorted(self.available_controls) or 'none'})"
            )

    async def async_pause(self) -> bool:
        """Toggle pause on the current source.

        The device has no separate resume: on a source it streams itself
        this pauses a playing track and resumes a paused one. On AirPlay
        and other controller-driven sources it instead ends the session,
        which cannot be undone from the device.
        """
        self._require_control(Control.PAUSE)
        return await async_activate_control(
            self.host, Control.PAUSE, self.streammagic_port
        )

    async def async_next(self) -> bool:
        """Skip to the next track."""
        self._require_control(Control.NEXT_TRACK)
        return await async_activate_control(
            self.host, Control.NEXT_TRACK, self.streammagic_port
        )

    async def async_previous(self) -> bool:
        """Skip to the previous track."""
        self._require_control(Control.PREVIOUS_TRACK)
        return await async_activate_control(
            self.host, Control.PREVIOUS_TRACK, self.streammagic_port
        )

    async def async_seek(self, position_ms: int) -> bool:
        """Seek to an absolute position, in milliseconds."""
        self._require_control(Control.SEEK)
        return await _seek(self.host, position_ms, self.streammagic_port)

    async def async_set_play_mode(self, mode: PlayMode) -> bool:
        """Set the combined shuffle/repeat mode."""
        if mode not in self.available_play_modes:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer play mode {mode!r} "
                f"(available: {sorted(self.available_play_modes, key=lambda m: m.wire) or 'none'})"
            )
        return await _set_play_mode(self.host, mode.wire, self.streammagic_port)

    async def async_set_shuffle(self, shuffle: bool) -> bool:
        """Set shuffle, carrying the current repeat setting over unchanged.

        Takes the current `play_mode`, replaces only its `shuffle` field,
        and sets the resulting combination - so toggling shuffle can never
        clobber whatever repeat mode was already in effect. Raises
        `LyngdorfUnsupportedError` if there is no current play mode to
        modify, or if the resulting combination is not one the current
        source advertises.
        """
        current = self.play_mode
        if current is None:
            raise LyngdorfUnsupportedError(
                f"{self.host}: no current play mode to modify"
            )
        candidate = dataclasses.replace(current, shuffle=shuffle)
        if candidate not in self.available_play_modes:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer shuffle={shuffle} "
                f"with repeat={current.repeat} (available: "
                f"{sorted(self.available_play_modes, key=lambda m: m.wire) or 'none'})"
            )
        return await self.async_set_play_mode(candidate)

    async def async_set_repeat(self, repeat: Repeat) -> bool:
        """Set repeat, carrying the current shuffle setting over unchanged.

        Mirrors `async_set_shuffle`: takes the current `play_mode`,
        replaces only its `repeat` field, and validates the resulting
        combination before sending it.
        """
        current = self.play_mode
        if current is None:
            raise LyngdorfUnsupportedError(
                f"{self.host}: no current play mode to modify"
            )
        candidate = dataclasses.replace(current, repeat=repeat)
        if candidate not in self.available_play_modes:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer repeat={repeat} "
                f"with shuffle={current.shuffle} (available: "
                f"{sorted(self.available_play_modes, key=lambda m: m.wire) or 'none'})"
            )
        return await self.async_set_play_mode(candidate)

    async def _poll_now_playing(self) -> None:
        """Long-poll loop for now-playing changes on the :8080 API.

        Runs as a background task for streaming-capable models. Creates an
        event queue, subscribes to player data changes, then loops: long-
        poll for events -> on any change, fetch current state via getData
        -> diff against cached value -> fire callbacks. On any failure
        (network, expired queue), drops the queue and re-initializes with
        exponential backoff.
        """
        port = self.streammagic_port
        backoff = 1.0
        queue_id: str | None = None
        # One connection reused for every request below. Subscribing to
        # position makes this loop iterate about once a second, so a
        # connection per request would burn ~86,400 sockets a day on
        # hardware that has few to spare.
        session = StreamMagicSession(self.host, port)

        try:
            while self._connection_enabled:
                try:
                    if queue_id is None:
                        np = await async_fetch_now_playing(
                            self.host, port, session=session
                        )
                        self._update_now_playing(np)
                        self._update_position(
                            await async_fetch_position(self.host, port, session=session)
                        )
                        self._update_play_mode(
                            await async_fetch_play_mode(
                                self.host, port, session=session
                            )
                        )
                        raw_global_modes = await async_fetch_play_modes(
                            self.host, port, session=session
                        )
                        self._global_play_modes = parse_play_modes(raw_global_modes)

                        queue_id = await async_init_now_playing_queue(
                            self.host, port, session=session
                        )
                        if queue_id is None:
                            _LOGGER.debug(
                                "%s: failed to create now-playing queue, retrying",
                                self.host,
                            )
                            await asyncio.sleep(backoff)
                            backoff = min(30.0, backoff * 2)
                            continue

                        if not await async_subscribe_now_playing(
                            self.host, queue_id, port, session=session
                        ):
                            _LOGGER.debug(
                                "%s: failed to subscribe now-playing queue", self.host
                            )
                            queue_id = None
                            await asyncio.sleep(backoff)
                            backoff = min(30.0, backoff * 2)
                            continue

                        backoff = 1.0

                    events = await async_poll_now_playing_events(
                        self.host,
                        queue_id,
                        port,
                        NOW_PLAYING_POLL_TIMEOUT,
                        session=session,
                    )

                    if events is None:
                        _LOGGER.debug(
                            "%s: now-playing queue expired, re-initializing", self.host
                        )
                        queue_id = None
                        continue

                    if events:
                        position = parse_position_events(events)
                        if position is not None:
                            self._update_position(position)

                        play_mode = parse_play_mode_events(events)
                        if play_mode is not None:
                            self._update_play_mode(play_mode)

                        # Position ticks about once a second and play mode
                        # arrives inline too; refetching the full payload
                        # for either would mean an HTTP request per change
                        # for a value we already have inline.
                        if any(
                            not isinstance(event, dict)
                            or event.get("path")
                            not in (NOW_PLAYING_POSITION_PATH, PLAY_MODE_PATH)
                            for event in events
                        ):
                            np = await async_fetch_now_playing(
                                self.host, port, session=session
                            )
                            self._update_now_playing(np)

                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.debug(
                        "%s: now-playing poll error, retrying",
                        self.host,
                        exc_info=True,
                    )
                    queue_id = None
                    await asyncio.sleep(backoff)
                    backoff = min(30.0, backoff * 2)
        finally:
            # The task is cancelled on disconnect; without this the
            # kept-alive socket would linger on the device.
            session.close()

    def _update_now_playing(self, np: NowPlaying | None) -> None:
        if np != self._now_playing:
            self._now_playing = np
            for cb in self._now_playing_callbacks:
                try:
                    cb(np)
                except Exception:
                    _LOGGER.error(
                        "%s: now-playing callback error: %s",
                        self.host,
                        traceback.format_exc(),
                    )

    def _update_position(self, position_ms: int | None) -> None:
        """Record a new playback position.

        The timestamp is refreshed on every device report, including when
        the value repeats (a paused track reports the same millisecond
        indefinitely) - otherwise a consumer extrapolating from it would
        drift further from reality the longer the pause lasted. The raw
        callback still only fires on an actual change; the jump callback
        fires independently of that, based on whether this report is a
        discontinuity rather than ordinary once-a-second progression - see
        `_is_position_discontinuity` and `register_position_jump_callback`.
        Raw callbacks fire before jump callbacks, so a consumer subscribed
        to both sees them in a sensible order.
        """
        now = datetime.now(UTC)
        previous_ms = self._position_ms
        previous_at = self._position_updated_at
        previous_state = self._position_prev_state
        previous_title = self._position_prev_title

        current_state = self._now_playing.state if self._now_playing else None
        current_title = self._now_playing.title if self._now_playing else None

        is_jump = _is_position_discontinuity(
            position_ms,
            previous_ms,
            previous_at,
            now,
            current_state,
            previous_state,
            current_title,
            previous_title,
        )

        self._position_updated_at = now
        self._position_prev_state = current_state
        self._position_prev_title = current_title

        if position_ms != previous_ms:
            self._position_ms = position_ms
            for cb in self._position_callbacks:
                try:
                    cb(position_ms)
                except Exception:
                    _LOGGER.error(
                        "%s: position callback error: %s",
                        self.host,
                        traceback.format_exc(),
                    )

        if is_jump:
            for cb in self._position_jump_callbacks:
                try:
                    cb(position_ms)
                except Exception:
                    _LOGGER.error(
                        "%s: position jump callback error: %s",
                        self.host,
                        traceback.format_exc(),
                    )

    def _update_play_mode(self, mode: str | None) -> None:
        """Record a new play mode from its wire string.

        Converted to `PlayMode` here, rather than by each caller, so the
        poll loop's seed fetch, its per-event update, and
        `set_power_state`'s clear-on-power-off all share one conversion
        path. A wire value `PlayMode.from_wire` does not recognise becomes
        None, same as "unavailable" - callbacks only fire on an actual
        change to the parsed value.
        """
        parsed = PlayMode.from_wire(mode) if mode is not None else None
        if parsed == self._play_mode:
            return

        self._play_mode = parsed
        for cb in self._play_mode_callbacks:
            try:
                cb(parsed)
            except Exception:
                _LOGGER.error(
                    "%s: play mode callback error: %s",
                    self.host,
                    traceback.format_exc(),
                )

    @property
    def connected(self) -> bool:
        """Return True if telnet connection is enabled."""
        return self._connection_enabled

    @property
    def healthy(self) -> bool:
        """Return True if the connection is healthy."""
        return self._protocol is not None and self._protocol.connected
