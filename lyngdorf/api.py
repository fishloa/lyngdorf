"""Lyngdorf Audio Control Library - API Module.

Handles TCP/IP communication with Lyngdorf receivers on port 84.
Implements asyncio protocol for command/response handling.

Streaming (:8080) state and poll loop live in streaming/poll.py; this
module delegates streaming calls to an internal NowPlayingPoll instance
so the existing test surface stays intact while the class is extracted.

:license: MIT, see LICENSE for more details.
"""

import asyncio
import logging
import time
from asyncio import timeout as asyncio_timeout
from collections.abc import Callable
from datetime import datetime

from .const import DEFAULT_LYNGDORF_PORT, STREAMMAGIC_PORT
from .exceptions import LyngdorfUnsupportedError
from .models import LyngdorfModel
from .rio import LyngdorfProtocol, RioClient
from .rio import _coalesce_key as _coalesce_key  # re-export: tests import it from here
from .states import Control, PlayMode, Repeat
from .streaming import NowPlaying
from .streaming.poll import NowPlayingPoll

_LOGGER = logging.getLogger(__package__)


class LyngdorfApi(RioClient):
    """The :84 RIO protocol client with connection lifecycle and streaming
    state delegation.

    The streaming-module poll loop was extracted to
    `lyngdorf.streaming.poll.NowPlayingPoll` in WP5. This class holds a
    `NowPlayingPoll` internally and delegates all NowPlayingEngine
    methods to it so the existing test surface stays intact.

    `async_connect` / `_async_establish_connection` / `async_disconnect`
    live here rather than on `RioClient` because they coordinate both:
    the poll loop starts only after the base connection is up, and stops
    before it closes. See `rio.client.RioClient`'s docstring for the
    harder reason `_async_establish_connection` can't move: it reads the
    module-global `DEFAULT_LYNGDORF_PORT`, which
    `tests/reconnect_leak_test.py` monkeypatches on this module directly.
    """

    streammagic_port: int = STREAMMAGIC_PORT

    def __init__(
        self,
        host: str,
        model: LyngdorfModel,
        poll: NowPlayingPoll | None = None,
    ) -> None:
        super().__init__(host, model)
        self._poll = poll

    def _ensure_poll(self) -> NowPlayingPoll:
        if self._poll is None:
            from .streaming.client import StreamingClient

            client = StreamingClient(self.host, self.streammagic_port)
            self._poll = NowPlayingPoll(self.host, client)
        return self._poll

    # -- Poll lifecycle delegation (used by tests) --------------------------

    @property
    def _now_playing_task(self) -> asyncio.Task[None] | None:
        return self._poll._now_playing_task if self._poll else None

    @_now_playing_task.setter
    def _now_playing_task(self, value: asyncio.Task[None] | None) -> None:
        self._ensure_poll()._now_playing_task = value

    @property
    def _now_playing_wanted(self) -> bool:
        return self._poll._now_playing_wanted if self._poll else False

    @_now_playing_wanted.setter
    def _now_playing_wanted(self, value: bool) -> None:
        if value:
            self._ensure_poll()._now_playing_wanted = value
        elif self._poll is not None:
            self._poll._now_playing_wanted = value

    def _on_now_playing_task_done(self, task: asyncio.Task[None]) -> None:
        self._ensure_poll()._on_now_playing_task_done(task)

    def _ensure_now_playing_task(self) -> None:
        self._ensure_poll()._ensure_now_playing_task()

    async def _poll_now_playing(self) -> None:
        await self._ensure_poll()._poll_now_playing()

    @property
    def _global_play_modes(self) -> frozenset[PlayMode]:
        return self._poll._global_play_modes if self._poll else frozenset()

    @_global_play_modes.setter
    def _global_play_modes(self, value: frozenset[PlayMode]) -> None:
        self._ensure_poll()._global_play_modes = value

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
        if self._protocol is not None:
            self._protocol.close()
        self._protocol = transport_protocol[1]
        self._connection_enabled = True
        self._last_message_time = time.monotonic()
        self._schedule_monitor()
        await self._writeSetup()
        self._start_write_queue()
        if self._model.config.has_streaming:
            self._start_now_playing_poll()
        _LOGGER.debug("%s: connection complete", self.host)

    def _start_now_playing_poll(self) -> None:
        self._ensure_poll().start()

    def _stop_now_playing_poll(self) -> None:
        if self._poll is not None:
            self._poll.stop()

    def set_power_state(self, power_on: bool) -> None:
        if not self._model.config.has_streaming:
            return
        if power_on:
            self._start_now_playing_poll()
            return
        self._stop_now_playing_poll()
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

    # -- NowPlayingEngine delegation (consumed by Player) --------------------

    @property
    def now_playing(self) -> NowPlaying | None:
        return self._poll.now_playing if self._poll else None

    def register_now_playing_callback(
        self, callback: Callable[[NowPlaying | None], None]
    ) -> Callable[[], None]:
        return self._ensure_poll().register_now_playing_callback(callback)

    @property
    def position_ms(self) -> int | None:
        return self._poll.position_ms if self._poll else None

    @property
    def position_updated_at(self) -> datetime | None:
        return self._poll.position_updated_at if self._poll else None

    def register_position_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        return self._ensure_poll().register_position_callback(callback)

    def register_position_jump_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        return self._ensure_poll().register_position_jump_callback(callback)

    @property
    def play_mode(self) -> PlayMode | None:
        if not self._model.config.has_streaming:
            return None
        return self._poll.play_mode if self._poll else None

    @property
    def shuffle(self) -> bool | None:
        if not self._model.config.has_streaming:
            return None
        return self._poll.shuffle if self._poll else None

    @property
    def repeat(self) -> Repeat | None:
        if not self._model.config.has_streaming:
            return None
        return self._poll.repeat if self._poll else None

    def register_play_mode_callback(
        self, callback: Callable[[PlayMode | None], None]
    ) -> Callable[[], None]:
        return self._ensure_poll().register_play_mode_callback(callback)

    @property
    def available_controls(self) -> frozenset[Control]:
        if not self._model.config.has_streaming:
            return frozenset()
        return self._poll.available_controls if self._poll else frozenset()

    @property
    def available_play_modes(self) -> frozenset[PlayMode]:
        if not self._model.config.has_streaming:
            return frozenset()
        return self._poll.available_play_modes if self._poll else frozenset()

    @property
    def can_shuffle(self) -> bool:
        if not self._model.config.has_streaming:
            return False
        return self._poll.can_shuffle if self._poll else False

    @property
    def available_repeat_modes(self) -> frozenset[Repeat]:
        if not self._model.config.has_streaming:
            return frozenset()
        return self._poll.available_repeat_modes if self._poll else frozenset()

    def _require_control(self, control: Control) -> None:
        if control not in self.available_controls:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer {control!r} "
                f"(available: {sorted(self.available_controls) or 'none'})"
            )

    async def async_pause(self) -> bool:
        self._require_control(Control.PAUSE)
        return await self._ensure_poll().async_pause()

    async def async_next(self) -> bool:
        self._require_control(Control.NEXT_TRACK)
        return await self._ensure_poll().async_next()

    async def async_previous(self) -> bool:
        self._require_control(Control.PREVIOUS_TRACK)
        return await self._ensure_poll().async_previous()

    async def async_seek(self, position_ms: int) -> bool:
        self._require_control(Control.SEEK)
        return await self._ensure_poll().async_seek(position_ms)

    async def async_set_play_mode(self, mode: PlayMode) -> bool:
        if mode not in self.available_play_modes:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer play mode {mode!r} "
                f"(available: "
                f"{sorted(self.available_play_modes, key=lambda m: m.wire) or 'none'})"
            )
        return await self._ensure_poll().async_set_play_mode(mode)

    async def async_set_shuffle(self, shuffle: bool) -> bool:
        return await self._ensure_poll().async_set_shuffle(shuffle)

    async def async_set_repeat(self, repeat: Repeat) -> bool:
        return await self._ensure_poll().async_set_repeat(repeat)

    # -- Internal state mutation (used by tests directly) --------------------

    def _update_now_playing(self, np: NowPlaying | None) -> None:
        self._ensure_poll()._update_now_playing(np)

    @property
    def _now_playing(self) -> NowPlaying | None:
        return self._poll._now_playing if self._poll else None

    def _update_position(self, position_ms: int | None) -> None:
        self._ensure_poll()._update_position(position_ms)

    def _update_play_mode(self, mode: str | None) -> None:
        self._ensure_poll()._update_play_mode(mode)
