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
import dataclasses
import logging
import time
import traceback
from asyncio import timeout as asyncio_timeout
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from .base import register_in_list
from .const import (
    DEFAULT_LYNGDORF_PORT,
    NOW_PLAYING_POLL_TIMEOUT,
    NOW_PLAYING_POSITION_PATH,
    PLAY_MODE_PATH,
    POSITION_DRIFT_TOLERANCE_MS,
    STREAMMAGIC_PORT,
    LyngdorfModel,
)
from .exceptions import LyngdorfUnsupportedError
from .rio import LyngdorfProtocol, RioClient
from .rio import _coalesce_key as _coalesce_key  # re-export: tests import it from here
from .states import Control, PlaybackState, PlayMode, Repeat
from .streaming import (
    NowPlaying,
    StreamingClient,
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


class LyngdorfApi(RioClient):
    """Handle responses from the Lyngdorf interface.

    Adds now-playing/position/play-mode state and the streaming poll loop
    on top of `RioClient`'s wire-protocol connection. `async_connect` /
    `_async_establish_connection` / `async_disconnect` live here rather
    than on `RioClient` because they coordinate both: the poll loop starts
    only after the base connection is up, and stops before it closes. See
    `rio.client.RioClient`'s docstring for the other, harder reason
    `_async_establish_connection` can't move: it reads the module-global
    `DEFAULT_LYNGDORF_PORT`, which `tests/reconnect_leak_test.py`
    monkeypatches on this module directly.
    """

    streammagic_port: int = STREAMMAGIC_PORT

    def __init__(self, host: str, model: LyngdorfModel) -> None:
        """Initialize the client."""
        super().__init__(host, model)
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
        session = StreamingClient(self.host, port)

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
            # The task is cancelled on disconnect; without this the owned
            # ClientSession (and its kept-alive socket) would linger on
            # the device.
            await session.close()

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
