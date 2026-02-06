#!/usr/bin/env python3
"""
Lyngdorf Audio Control Library - API Module.

Handles TCP/IP communication with Lyngdorf receivers on port 84.
Implements asyncio protocol for command/response handling.

Supported Models:
- MP-40, MP-50, MP-60 (Processors)
- TDAI-1120, TDAI-2170, TDAI-3400 (Integrated Amplifiers)

:license: MIT, see LICENSE for more details.
"""

import asyncio
import contextlib
import logging
import time
import traceback
from asyncio import timeout as asyncio_timeout
from collections.abc import Callable
from typing import cast

from .const import (
    DEFAULT_LYNGDORF_PORT,
    MONITOR_INTERVAL,
    RECONNECT_BACKOFF,
    RECONNECT_MAX_WAIT,
    RECONNECT_SCALE,
    LyngdorfModel,
    Msg,
)

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

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost."""
        self.close()
        self._on_connection_lost()
        return super().connection_lost(exc)


class LyngdorfApi:
    """Handle responses from the Lyngdorf interface."""

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
        self._callbacks: dict[str, list[Callable]] = {}
        self._notification_callbacks: list[Callable[[], None]] = []

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
        self._protocol = cast(LyngdorfProtocol, transport_protocol[1])  # type: ignore
        self._connection_enabled = True
        self._last_message_time = time.monotonic()
        self._schedule_monitor()
        self._writeSetup()
        _LOGGER.debug("%s: connection complete", self.host)

    def _schedule_monitor(self) -> None:
        """Start the monitor task."""
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
            # Keep the connection alive
            self._writeCommand(f"{self._model.lookup_command(Msg.PING)}?")
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

    async def _async_reconnect(self) -> None:
        """Reconnect to the receiver asynchronously."""
        backoff = RECONNECT_BACKOFF
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
            backoff = min(RECONNECT_MAX_WAIT, backoff * RECONNECT_SCALE)

    def _writeSetup(self):
        for cmd in self._model.setup_commands:
            self._writeCommand(cmd)

    def _writeCommand(self, command):
        """Send a command to the receiver."""
        if self._protocol is not None:
            self._protocol.write(f"!{command}\r")
            _LOGGER.debug("%s send: '!%s'", self.host, command)

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
        self._writeCommand(f"{self._model.lookup_command(Msg.VOLUME)}+")

    def volume_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.VOLUME)}-")

    def zone_b_volume_up(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_VOLUME)}+")

    def zone_b_volume_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.ZONE_B_VOLUME)}-")

    def volume(self, volume: float):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.VOLUME)}({volume*10.0:.0f})"
        )

    def zone_b_volume(self, volume: float):
        self._writeCommand(
            f"{self._model.lookup_command(Msg.VOLUME)}({volume*10.0:.0f})"
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
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_BASS)}({trim*10.0:.0f})"
        )

    def change_trim_centre(self, trim: float):
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
        self._writeCommand(
            f"{self._model.lookup_command(Msg.TRIM_TREBLE_SET)}({trim*10.0:.0f})"
        )

    def trim_bass_up(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_BASS)}+")

    def trim_bass_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_BASS)}-")

    def trim_centre_up(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_CENTRE)}+")

    def trim_centre_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_CENTRE)}-")

    def trim_height_up(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_HEIGHT)}+")

    def trim_height_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_HEIGHT)}-")

    def trim_lfe_up(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_LFE)}+")

    def trim_lfe_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_LFE)}-")

    def trim_surround_up(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_SURROUND)}+")

    def trim_surround_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_SURROUND)}-")

    def trim_treble_up(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_TREBLE_SET)}+")

    def trim_treble_down(self):
        self._writeCommand(f"{self._model.lookup_command(Msg.TRIM_TREBLE_SET)}-")

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

            if cmd == self._model.lookup_command(Msg.PONG):
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
            except Exception:
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
