#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automation Library for Lyngdorf receivers.

:license: MIT, see LICENSE for more details.
"""

import asyncio
import contextlib
import time
import logging
import attr
import traceback

from asyncio import timeout as asyncio_timeout
from typing import Callable, Dict, Optional, cast, List

from lyngdorf.const import (
    DEFAULT_LYNGDORF_PORT,
    COMMANDS_SETUP,
    RESPONSES_KEYS_ALL,
    COMMAND_KEEP_ALIVE,
    RESPONSE_KEEP_ALIVE,
    MP60_AUDIO_INPUTS,
    MP60_VIDEO_INPUTS,
    MP60_VIDEO_OUTPUTS,
    MP60_STREAM_TYPES,
)

_MONITOR_INTERVAL = 5

_LOGGER = logging.getLogger(__package__)


class LyngdorfProtocol(asyncio.Protocol):
    """Protocol for the Lyngdorf interface."""

    def __init__(
        self,
        on_message: Callable[[str], None],
        on_connection_lost: Callable[[], None],
    ) -> None:
        """Initialize the protocol."""
        self._buffer = b""
        self.transport: Optional[asyncio.Transport] = None
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
        print("eof")
        return True

    def data_received(self, data: bytes) -> None:
        """Handle data received."""
        self._buffer += data
        while b"\r" in self._buffer:
            line, _, self._buffer = self._buffer.partition(b"\r")
            with contextlib.suppress(UnicodeDecodeError):
                self._on_message(line.decode("utf-8"))

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore
        """Handle connection made."""
        _LOGGER.debug("connection made")
        self.transport = transport  # type: ignore

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Handle connection lost."""
        self.transport = None
        self._on_connection_lost()
        return super().connection_lost(exc)


class LyngdorfApi:
    """Handle responses from the Lyngdorf interface."""

    def __init__(self, host):
        """Initialize the client."""
        self._connection_enabled = False
        self.host = host
        self._connect_lock = asyncio.Lock()
        self.host: str
        self.timeout: float
        self._connection_enabled: bool
        self._healthy: Optional[bool] = attr.ib(
            converter=attr.converters.optional(bool), default=None
        )
        self._last_message_time: float = -1.0
        self._connect_lock: asyncio.Lock  # = attr.ib(default=attr.Factory(asyncio.Lock))
        self._reconnect_task: asyncio.Task = None
        self._monitor_handle: asyncio.TimerHandle
        self._protocol: LyngdorfProtocol
        self._callbacks: Dict[str, Callable] = {}
        self._notification_callbacks: List = list()

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
        except asyncio.TimeoutError as err:
            _LOGGER.debug("%s: Timeout exception on connect", self.host)
            raise asyncio.TimeoutError(f"TimeoutException: {err}", "connect") from err
        except ConnectionRefusedError as err:
            _LOGGER.debug("%s: Connection refused on connect", self.host, exc_info=True)
            raise ConnectionRefusedError(
                f"ConnectionRefusedError: {err}", "connect"
            ) from err
        self._protocol = cast(LyngdorfProtocol, transport_protocol[1])  # type: ignore
        self._connection_enabled = True
        self._last_message_time = time.monotonic()
        self._schedule_monitor()
        self._writeSetup()
        _LOGGER.debug("%s: connection complete", self.host)

    def _schedule_monitor(self) -> None:
        """Start the monitor task."""
        loop = asyncio.get_event_loop()
        self._monitor_handle = loop.call_later(_MONITOR_INTERVAL, self._monitor)

    def _stop_monitor(self) -> None:
        """Stop the monitor task."""
        if self._monitor_handle is not None:
            self._monitor_handle.cancel()
            self._monitor_handle = None

    def _monitor(self) -> None:
        """Monitor the connection."""
        time_since_response = time.monotonic() - self._last_message_time
        if time_since_response > _MONITOR_INTERVAL * 4:
            _LOGGER.info(
                "%s: Keep alive failed, disconnecting and reconnecting", self.host
            )
            if self._protocol is not None:
                self._protocol.close()
            self._handle_disconnected()
            return

        if time_since_response > _MONITOR_INTERVAL and self._protocol:
            # Keep the connection alive
            self._writeCommand(COMMAND_KEEP_ALIVE)
        self._schedule_monitor()

    def _handle_disconnected(self) -> None:
        """Handle disconnected."""
        _LOGGER.debug("%s: disconnected", self.host)
        self._protocol = None
        self._stop_monitor()
        if not self._connection_enabled:
            return
        self._reconnect_task = asyncio.create_task(self._async_reconnect())

    async def async_disconnect(self) -> None:
        """Close the connection to the receiver asynchronously."""
        async with self._connect_lock:
            self._connection_enabled = False
            self._stop_monitor()
            if self._reconnect_task is not None:
                self._reconnect_task.cancel()
                self._reconnect_task = None
            if self._protocol is not None:
                self._protocol.close()
                self._protocol = None

            # if self._reconnect_task is not None:
            #     try:
            #         await self._reconnect_task
            #     except asyncio.CancelledError:
            #         pass

    async def _async_reconnect(self) -> None:
        """Reconnect to the receiver asynchronously."""
        backoff = 0.5
        _LOGGER.debug("Trying to reconnect")
        while self._connection_enabled and not self.healthy:
            _LOGGER.debug("Trying to reconnect...")
            async with self._connect_lock:
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
            backoff = min(30.0, backoff * 2)

    def _writeSetup(self):
        for cmd in COMMANDS_SETUP:
            self._writeCommand(cmd)

    def _writeCommand(self, command):
        """Send a command to the receiver."""
        self._protocol.write(f"!{command}\r")
        _LOGGER.debug("%s send: '!%s'", self.host, command)

    def power_on(self, enabled: bool):
        if enabled:
            self._writeCommand("POWERONMAIN")
        else:
            self._writeCommand("POWEROFFMAIN")

    def zone_b_power_on(self, enabled: bool):
        if enabled:
            self._writeCommand("POWERONZONE2")
        else:
            self._writeCommand("POWEROFFZONE2")

    def mute_enabled(self, mute: bool):
        if mute:
            self._writeCommand("MUTEON")
        else:
            self._writeCommand("MUTEOFF")

    def zone_b_mute_enabled(self, mute: bool):
        if mute:
            self._writeCommand("ZMUTEON")
        else:
            self._writeCommand("ZMUTEOFF")

    def volume_up(self):
        self._writeCommand("VOL+")

    def volume_down(self):
        self._writeCommand("VOL-")

    def zone_b_volume_up(self):
        self._writeCommand("ZVOL+")

    def zone_b_volume_down(self):
        self._writeCommand("ZVOL-")

    def volume(self, volume: float):
        self._writeCommand(f"VOL({volume*10.0:.0f})")

    def zone_b_volume(self, volume: float):
        self._writeCommand(f"VOL({volume*10.0:.0f})")

    def change_source(self, source: int):
        self._writeCommand(f"SRC({source})")

    def change_zone_b_source(self, zone_b_source: int):
        self._writeCommand(f"ZSRC({zone_b_source})")

    def change_sound_mode(self, sound_mode: int):
        self._writeCommand(f"AUDMODE({sound_mode})")

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
            if 1 < message.find("(") < message.find(")"):
                cmd = message[: message.find("(")]
                first = message[1 + message.find("(") : message.find(")")]
                second = message[1 + message.find(")") :]
            else:
                cmd = message

            if cmd == RESPONSE_KEEP_ALIVE:
                return

            if len(second) > 0 and second.startswith('"') and second.endswith('"'):
                second = second[1:-1]
            asyncio.create_task(self._async_run_callbacks(cmd, first, second))
            asyncio.create_task(self._notify_notification_callbacks())

    def register_notification_callback(self, callback: Callable[[], None]) -> None:
        self._notification_callbacks.append(callback)

    def un_register_notification_callback(self, callback: Callable[[], None]) -> None:
        self._notification_callbacks.remove(callback)

    async def _notify_notification_callbacks(self) -> None:
        for callback in self._notification_callbacks:
            try:
                callback()
            except Exception as err:
                # We don't want a single bad callback to trip up the
                # whole system and prevent further execution
                # TIM. TODO. need to log the stack trace of the error found here, as at the moment v hard to find errors

                _LOGGER.error(
                    "%s: Event callback caused an unhandled exception '%s' (%s)",
                    self.host,
                    traceback.format_exc(),
                )

    def register_callback(
        self, command: str, callback: Callable[[str, str], None]
    ) -> None:
        """Register a callback handler for an event type."""
        # Validate the passed in type
        if command not in RESPONSES_KEYS_ALL:
            raise ValueError(f"{command} is not a valid callback type.")

        if command not in self._callbacks.keys():
            self._callbacks[command] = []
        self._callbacks[command].append(callback)

    async def _async_run_callbacks(
        self, command: str, param1: str, param2: str
    ) -> None:
        """Handle triggering the registered callbacks for the event."""
        if command in self._callbacks.keys():
            for callback in self._callbacks[command]:
                try:
                    # _LOGGER.debug("Command %s callback (%s, %s) calling %s", command, param1, param2, callback)
                    callback(param1, param2)
                except Exception as err:  # pylint: disable=broad-except
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
