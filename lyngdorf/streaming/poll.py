"""The streaming-module long-poll loop, extracted from api.py (spec §4).

NowPlayingPoll carries all the streaming state formerly owned by
LyngdorfApi — now_playing, position, play_mode, their callbacks,
the poll task lifecycle, and power-gated start/stop. It implements
NowPlayingEngine so Player can consume it unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Callable
from datetime import UTC, datetime

from ..base import register_in_list
from ..const import (
    NOW_PLAYING_POLL_TIMEOUT,
    NOW_PLAYING_POSITION_PATH,
    PLAY_MODE_PATH,
)
from ..states import Control, PlaybackState, PlayMode, Repeat
from .client import (
    StreamingClient,
    async_activate_control,
    async_fetch_now_playing,
    async_fetch_play_mode,
    async_fetch_play_modes,
    async_fetch_position,
    async_init_now_playing_queue,
    async_poll_now_playing_events,
    async_subscribe_now_playing,
)
from .client import (
    async_seek as _seek,
)
from .client import (
    async_set_play_mode as _set_play_mode,
)
from .parsers import parse_play_mode_events, parse_play_modes, parse_position_events
from .types import NowPlaying

_LOGGER = logging.getLogger(__package__)

_POSITION_DRIFT_TOLERANCE_MS = 2000


class NowPlayingPoll:
    """The streaming module's long-poll loop and its cached state.

    Implements NowPlayingEngine so Player consumes this unchanged from
    the api.py era. The poll loop runs as a background asyncio Task;
    transport writes bypass the poll lock via StreamingClient.one_shot_status.
    """

    def __init__(
        self,
        host: str,
        streaming: StreamingClient,
    ) -> None:
        self._host = host
        self._streaming = streaming
        self._now_playing: NowPlaying | None = None
        self._now_playing_callbacks: list[Callable[[NowPlaying | None], None]] = []
        self._now_playing_task: asyncio.Task[None] | None = None
        self._now_playing_wanted = False
        self._position_ms: int | None = None
        self._position_updated_at: datetime | None = None
        self._position_callbacks: list[Callable[[int | None], None]] = []
        self._position_jump_callbacks: list[Callable[[int | None], None]] = []
        self._position_prev_state: PlaybackState | None = None
        self._position_prev_title: str | None = None
        self._play_mode: PlayMode | None = None
        self._play_mode_callbacks: list[Callable[[PlayMode | None], None]] = []
        self._global_play_modes: frozenset[PlayMode] = frozenset()

    def start(self) -> None:
        """Ask for the poll to be running; safe to call repeatedly."""
        self._now_playing_wanted = True
        self._ensure_now_playing_task()

    def stop(self) -> None:
        self._now_playing_wanted = False
        if self._now_playing_task is not None:
            self._now_playing_task.cancel()

    def set_power_state(self, power_on: bool) -> None:
        """Follow device power with the now-playing poll.

        A powered-off device has nothing to play, so polling it is pure
        traffic against hardware that has few connection slots — and the
        poll runs about once a second whenever position is subscribed.
        Stopping on power-off also drops the kept-alive socket, leaving
        only the :84 control connection while the device is off.

        Called on every power notification, including repeats, so both
        start and stop must be idempotent — they are.
        """
        if power_on:
            self.start()
            return

        self.stop()
        self._update_now_playing(None)
        self._update_position(None)
        self._update_play_mode(None)

    def _ensure_now_playing_task(self) -> None:
        """Start the poll task unless one already exists."""
        if self._now_playing_task is not None:
            return

        coro = self._poll_now_playing()
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            coro.close()
            _LOGGER.debug(
                "%s: no running loop, not starting now-playing poll", self._host
            )
            return

        self._now_playing_task = task
        task.add_done_callback(self._on_now_playing_task_done)

    def _on_now_playing_task_done(self, task: asyncio.Task[None]) -> None:
        if self._now_playing_task is task:
            self._now_playing_task = None

        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            _LOGGER.debug("%s: now-playing poll task failed", self._host, exc_info=exc)
            return

        if self._now_playing_wanted:
            self._ensure_now_playing_task()

    async def _poll_now_playing(self) -> None:
        """Long-poll loop for now-playing changes on the :8080 API.

        Runs as a background task for streaming-capable models. Creates an
        event queue, subscribes to player data changes, then loops: long-
        poll for events -> on any change, fetch current state via getData
        -> diff against cached value -> fire callbacks. On any failure
        (network, expired queue), drops the queue and re-initializes with
        exponential backoff.
        """
        backoff = 1.0
        queue_id: str | None = None
        client = self._streaming

        try:
            while True:
                try:
                    if queue_id is None:
                        np = await async_fetch_now_playing(
                            self._host, self._streaming._port, session=client
                        )
                        self._update_now_playing(np)
                        self._update_position(
                            await async_fetch_position(
                                self._host, self._streaming._port, session=client
                            )
                        )
                        self._update_play_mode(
                            await async_fetch_play_mode(
                                self._host, self._streaming._port, session=client
                            )
                        )
                        raw_global_modes = await async_fetch_play_modes(
                            self._host, self._streaming._port, session=client
                        )
                        self._global_play_modes = parse_play_modes(raw_global_modes)

                        queue_id = await async_init_now_playing_queue(
                            self._host, self._streaming._port, session=client
                        )
                        if queue_id is None:
                            _LOGGER.debug(
                                "%s: failed to create now-playing queue, retrying",
                                self._host,
                            )
                            await asyncio.sleep(backoff)
                            backoff = min(30.0, backoff * 2)
                            continue

                        if not await async_subscribe_now_playing(
                            self._host,
                            queue_id,
                            self._streaming._port,
                            session=client,
                        ):
                            _LOGGER.debug(
                                "%s: failed to subscribe now-playing queue",
                                self._host,
                            )
                            queue_id = None
                            await asyncio.sleep(backoff)
                            backoff = min(30.0, backoff * 2)
                            continue

                        backoff = 1.0

                    events = await async_poll_now_playing_events(
                        self._host,
                        queue_id,
                        self._streaming._port,
                        NOW_PLAYING_POLL_TIMEOUT,
                        session=client,
                    )

                    if events is None:
                        _LOGGER.debug(
                            "%s: now-playing queue expired, re-initializing",
                            self._host,
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

                        if any(
                            not isinstance(event, dict)
                            or event.get("path")
                            not in (NOW_PLAYING_POSITION_PATH, PLAY_MODE_PATH)
                            for event in events
                        ):
                            np = await async_fetch_now_playing(
                                self._host, self._streaming._port, session=client
                            )
                            self._update_now_playing(np)

                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.debug(
                        "%s: now-playing poll error, retrying",
                        self._host,
                        exc_info=True,
                    )
                    queue_id = None
                    await asyncio.sleep(backoff)
                    backoff = min(30.0, backoff * 2)
        finally:
            # No close here: the client is receiver-owned now (it is shared with
            # Player's writes and reused across reconnects), so disconnect() owns
            # its lifetime. Idle keep-alive connections between a power-off poll
            # stop and the next start are reaped by aiohttp's connector, which
            # http.client never did — that is why 1.x closed here.
            pass

    def _update_now_playing(self, np: NowPlaying | None) -> None:
        if np != self._now_playing:
            self._now_playing = np
            for cb in self._now_playing_callbacks:
                try:
                    cb(np)
                except Exception:
                    _LOGGER.error(
                        "%s: now-playing callback error: %s",
                        self._host,
                        traceback.format_exc(),
                    )

    def _update_position(self, position_ms: int | None) -> None:
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
                        self._host,
                        traceback.format_exc(),
                    )

        if is_jump:
            for cb in self._position_jump_callbacks:
                try:
                    cb(position_ms)
                except Exception:
                    _LOGGER.error(
                        "%s: position jump callback error: %s",
                        self._host,
                        traceback.format_exc(),
                    )

    def _update_play_mode(self, mode: str | None) -> None:
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
                    self._host,
                    traceback.format_exc(),
                )

    # -- NowPlayingEngine protocol (consumed by Player) --------------------

    @property
    def now_playing(self) -> NowPlaying | None:
        return self._now_playing

    @property
    def position_ms(self) -> int | None:
        return self._position_ms

    @property
    def position_updated_at(self) -> datetime | None:
        return self._position_updated_at

    @property
    def play_mode(self) -> PlayMode | None:
        return self._play_mode

    @property
    def shuffle(self) -> bool | None:
        mode = self._play_mode
        return mode.shuffle if mode is not None else None

    @property
    def repeat(self) -> Repeat | None:
        mode = self._play_mode
        return mode.repeat if mode is not None else None

    def register_position_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        return register_in_list(self._position_callbacks, callback)

    def register_position_jump_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        return register_in_list(self._position_jump_callbacks, callback)

    @property
    def available_controls(self) -> frozenset[Control]:
        if self._now_playing is None:
            return frozenset()
        return self._now_playing.controls

    @property
    def available_play_modes(self) -> frozenset[PlayMode]:
        if self._now_playing is None:
            return frozenset()
        return self._now_playing.play_modes | self._global_play_modes

    @property
    def can_shuffle(self) -> bool:
        current = self._play_mode
        if current is None:
            return False
        return any(
            mode.repeat == current.repeat and mode.shuffle != current.shuffle
            for mode in self.available_play_modes
        )

    @property
    def available_repeat_modes(self) -> frozenset[Repeat]:
        current = self._play_mode
        if current is None:
            return frozenset()
        return frozenset(
            mode.repeat
            for mode in self.available_play_modes
            if mode.shuffle == current.shuffle
        )

    def register_now_playing_callback(
        self, callback: Callable[[NowPlaying | None], None]
    ) -> Callable[[], None]:
        return register_in_list(self._now_playing_callbacks, callback)

    def register_play_mode_callback(
        self, callback: Callable[[PlayMode | None], None]
    ) -> Callable[[], None]:
        return register_in_list(self._play_mode_callbacks, callback)

    # -- writes (spec §8: bypass the poll lock) ----------------------------

    async def async_pause(self) -> bool:
        if Control.PAUSE not in self.available_controls:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: device does not currently offer {Control.PAUSE!r} "
                f"(available: {sorted(self.available_controls) or 'none'})"
            )
        return await async_activate_control(
            self._host,
            Control.PAUSE,
            self._streaming._port,
            session=self._streaming,
        )

    async def async_next(self) -> bool:
        if Control.NEXT_TRACK not in self.available_controls:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: device does not currently offer {Control.NEXT_TRACK!r} "
                f"(available: {sorted(self.available_controls) or 'none'})"
            )
        return await async_activate_control(
            self._host,
            Control.NEXT_TRACK,
            self._streaming._port,
            session=self._streaming,
        )

    async def async_previous(self) -> bool:
        if Control.PREVIOUS_TRACK not in self.available_controls:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: device does not currently offer "
                f"{Control.PREVIOUS_TRACK!r} "
                f"(available: {sorted(self.available_controls) or 'none'})"
            )
        return await async_activate_control(
            self._host,
            Control.PREVIOUS_TRACK,
            self._streaming._port,
            session=self._streaming,
        )

    async def async_seek(self, position_ms: int) -> bool:
        if Control.SEEK not in self.available_controls:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: device does not currently offer {Control.SEEK!r} "
                f"(available: {sorted(self.available_controls) or 'none'})"
            )
        return await _seek(
            self._host,
            position_ms,
            self._streaming._port,
            session=self._streaming,
        )

    async def async_set_play_mode(self, mode: PlayMode) -> bool:
        if mode not in self.available_play_modes:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: device does not currently offer play mode {mode!r} "
                f"(available: "
                f"{sorted(self.available_play_modes, key=lambda m: m.wire) or 'none'})"
            )
        return await _set_play_mode(
            self._host,
            mode.wire,
            self._streaming._port,
            session=self._streaming,
        )

    async def async_set_shuffle(self, shuffle: bool) -> bool:
        import dataclasses

        current = self._play_mode
        if current is None:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: no current play mode to modify"
            )
        candidate = dataclasses.replace(current, shuffle=shuffle)
        if candidate not in self.available_play_modes:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: device does not currently offer shuffle={shuffle} "
                f"with repeat={current.repeat} (available: "
                f"{sorted(self.available_play_modes, key=lambda m: m.wire) or 'none'})"
            )
        return await self.async_set_play_mode(candidate)

    async def async_set_repeat(self, repeat: Repeat) -> bool:
        import dataclasses

        current = self._play_mode
        if current is None:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: no current play mode to modify"
            )
        candidate = dataclasses.replace(current, repeat=repeat)
        if candidate not in self.available_play_modes:
            from ..exceptions import LyngdorfUnsupportedError

            raise LyngdorfUnsupportedError(
                f"{self._host}: device does not currently offer repeat={repeat} "
                f"with shuffle={current.shuffle} (available: "
                f"{sorted(self.available_play_modes, key=lambda m: m.wire) or 'none'})"
            )
        return await self.async_set_play_mode(candidate)


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
    once-a-second progression."""
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
    return abs(position_ms - expected_ms) > _POSITION_DRIFT_TOLERANCE_MS
