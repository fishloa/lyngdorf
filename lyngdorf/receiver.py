"""LyngdorfReceiver: the entire 2.0 public receiver surface (design §2.2).

Pure assembly plus cached state (design §4): owns the internal
LyngdorfApi (wire client + streaming engine), builds the components from
ModelConfig, and defines the wire-callback methods - value conversion
only, no protocol framing, no socket code.

Write semantics, stated once and inherited by every setter's docstring by
reference: an `await` returns when the command has been QUEUED for paced
delivery, not when the device has acted. The authoritative new state
arrives through the device's own notification and is observable via the
properties / on_change. `async def` is the loop requirement made visible
(issue #51), not a promise of confirmation.
"""

from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Callable, Mapping, Sequence

import aiohttp

from .api import LyngdorfApi
from .base import CountingNumberDict, register_in_list
from .components import (
    Player,
    Remote,
    ZoneB,
    build_player,
    build_remote,
    build_zone_b,
)
from .const import Msg
from .controls import (
    NumericControl,
    SteppableControl,
    Trim,
    VolumeControl,
    build_lipsync,
    build_trims,
    build_volume,
)
from .exceptions import LyngdorfInvalidValueError
from .models import LyngdorfModel, NumericRange
from .rio import (
    MP_DIALECT,
    P_DIALECT,
    TDAI_2170_DIALECT,
    TDAI_DIALECT,
    Dialect,
    resolve_attr,
)
from .states import PlayMode
from .streaming import NowPlaying
from .values import (
    Reading,
    Selector,
    Switch,
    build_reading,
    build_selector,
    warn_deprecated,
)

_LOGGER = logging.getLogger(__package__)

_ALWAYS = object()


def convert_decibel(value: float | str, scale: float = 10.0) -> float:
    """Convert a wire-protocol numeric parameter to dB.

    `scale` is how many wire units make up 1 dB. Volume is always in
    tenths of a dB on both the MP and TDAI families, so the default of
    10.0 covers every volume call site unchanged. Bass/treble trim is
    NOT uniform across families - the MP series shares volume's tenths
    encoding but the TDAI series' `!BASS`/`!TREBLE` are whole dB only
    (see ModelConfig.trim_bass_treble_scale) - so callers on that path
    must pass the model's own scale explicitly rather than relying on
    this default. See issue #41.
    """
    return float(value) / scale


# Which family dialect each model registers with (was the receiver
# subclass hierarchy's _dialect class attributes - spec §2.9: the ten
# subclasses die; this mapping is what replaces their only real content).
_DIALECTS: dict[LyngdorfModel, Dialect] = {
    LyngdorfModel.MP_40: MP_DIALECT,
    LyngdorfModel.MP_50: MP_DIALECT,
    LyngdorfModel.MP_60: MP_DIALECT,
    LyngdorfModel.P_100: P_DIALECT,
    LyngdorfModel.P_200: P_DIALECT,
    LyngdorfModel.P_300: P_DIALECT,
    LyngdorfModel.TDAI_1120: TDAI_DIALECT,
    LyngdorfModel.TDAI_2210: TDAI_DIALECT,
    LyngdorfModel.TDAI_3400: TDAI_DIALECT,
    LyngdorfModel.TDAI_2170: TDAI_2170_DIALECT,
}


def _value(reading: Reading | None) -> str | None:
    return reading.value if reading is not None else None


class LyngdorfReceiver:
    """A Lyngdorf A/V processor or integrated amplifier.

    Write semantics, stated once and inherited by every setter's docstring by
    reference: an `await` returns when the command has been QUEUED for paced
    delivery, not when the device has acted. The authoritative new state
    arrives through the device's own notification and is observable via the
    properties / on_change. `async def` is the loop requirement made visible
    (issue #51), not a promise of confirmation.
    """

    def __init__(
        self,
        host: str,
        model: LyngdorfModel,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = host
        self._model = model
        self._dialect = _DIALECTS[model]

        # Ownership is decided here and nowhere else (spec §8). The owned
        # ClientSession itself is created lazily inside StreamingClient on
        # first :8080 use — constructing one needs a running loop, and a
        # non-streaming model must never allocate one at all.
        self._owns_session = session is None
        self._session = session
        from .const import STREAMMAGIC_PORT
        from .streaming.client import StreamingClient

        self._streaming: StreamingClient | None = (
            StreamingClient(host, STREAMMAGIC_PORT, session=session)
            if model.config.has_streaming
            else None
        )
        # The streaming poll loop — only created for streaming models.
        # Implements NowPlayingEngine, so Player consumes it unchanged.
        self._poll: NowPlayingPoll | None = None
        if self._streaming is not None:
            from .streaming.poll import NowPlayingPoll

            self._poll = NowPlayingPoll(host, self._streaming)

        self._api = LyngdorfApi(host, model, poll=self._poll)

        # Components and controls - structural capability (design §5):
        # built once, from ModelConfig, via the WP3 factories.
        self._volume = build_volume(self._api)
        self._trims = build_trims(self._api)
        self._lipsync = build_lipsync(self._api)
        self._zone_b = build_zone_b(self._api)
        # Player takes the poll (or LyngdorfApi for non-streaming / compat)
        self._player = build_player(model, self._poll if self._poll else self._api)
        self._remote = build_remote(self._api)

        config = model.config
        self._audio_inputs = config.audio_inputs
        # Indices already complained about - see _name_audio_input.
        self._unknown_audio_inputs: set[int] = set()
        self._video_inputs = config.video_inputs
        self._stream_types = config.stream_types
        self._sources = CountingNumberDict()
        self._sound_modes = CountingNumberDict()
        self._room_perfect_positions = CountingNumberDict()
        self._voicings = CountingNumberDict()
        self._name: str | None = None
        self._max_volume: float | None = None
        self._fixed_source: str | None = None

        self._power = Switch(self._api.power_on)
        self._mute = Switch(self._api.mute_enabled)
        self._source_selector = build_selector(
            self._api, Msg.SOURCES_COUNT, self._api.change_source, self._sources
        )
        self._sound_mode_selector = build_selector(
            self._api, Msg.AUDIO_MODE, self._api.change_sound_mode, self._sound_modes
        )
        self._room_perfect_position_selector = build_selector(
            self._api,
            Msg.ROOM_PERFECT_POSITION,
            self._api.change_room_perfect_position,
            self._room_perfect_positions,
        )
        self._voicing_selector = build_selector(
            self._api,
            Msg.ROOM_PERFECT_VOICING,
            self._api.change_voicing,
            self._voicings,
        )
        self._audio_information_reading = build_reading(self._api, Msg.AUDIO_TYPE)
        self._video_information_reading = build_reading(self._api, Msg.VIDEO_TYPE)
        self._audio_input_reading = build_reading(
            self._api, Msg.AUDIO_IN, self._audio_inputs
        )
        self._video_input_reading = build_reading(
            self._api, Msg.VIDEO_IN, self._video_inputs
        )
        self._streaming_source_reading = build_reading(
            self._api, Msg.STREAM_TYPE, self._stream_types
        )
        self._notification_callbacks: list[Callable[[], None]] = []

        # Dialect tables address zone_b internals by dotted path; alias
        # them so resolve_attr's "self._zone_b_sources" resolves.
        if self._zone_b is not None:
            self._zone_b_sources = self._zone_b._sources

        # Wired here rather than in connect: it is pure Python
        # object plumbing (turning an api-level now-playing update into
        # the Receiver's notification callback) with no dependency on an
        # actual socket connection, so capability properties like
        # `can_pause` stay live even before `connect` is called.
        if self._player is not None and self._poll is not None:
            self._poll.register_now_playing_callback(self._now_playing_changed)
            self._poll.register_play_mode_callback(self._play_mode_changed)

    # -- identity / lifecycle ---------------------------------------------

    @property
    def host(self) -> str:
        """The device's host/IP - required at construction, so typed
        honestly (was str | None in 1.x)."""
        return self._host

    @property
    def model(self) -> LyngdorfModel:
        return self._model

    @property
    def name(self) -> str | None:
        """The device-reported name, or None before the first reply."""
        return self._name

    @property
    def connected(self) -> bool:
        return self._api.connected

    async def connect(self) -> None:
        """Register wire callbacks and open the :84 connection.

        Keeps the 1.x sequence exactly (design §8): register -> connect
        (paced setup burst, monitor, poll start for streaming models all
        inside the api's connect)."""
        self._register_callbacks()
        await self._api.async_connect()
        if self._poll is not None:
            self._poll.start()

    async def disconnect(self) -> None:
        if self._poll is not None:
            self._poll.stop()
        await self._api.async_disconnect()
        if self._streaming is not None:
            # Closes only a session this library created; an injected one
            # belongs to the caller (spec §8). This is also where the
            # kept-alive :8080 socket goes away — 1.x closed it in the
            # poll coroutine's `finally`, which cannot survive the client
            # being hoisted out of that coroutine (it now outlives the
            # poll task, is shared with Player's writes, and is reused
            # across reconnects). Between a power-off poll stop and the
            # next poll start the connection is now reaped by aiohttp's
            # connector keepalive_timeout instead — something http.client
            # never did, which is why 1.x needed the manual close.
            await self._streaming.close()

    def on_change(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Fires on any state change. Returns an idempotent unsubscribe;
        duplicate registration collapses to one entry. (Was
        register_notification_callback - unchanged semantics.)"""
        return register_in_list(self._notification_callbacks, callback)

    # -- power ---------------------------------------------------------------

    @property
    def power(self) -> Switch:
        """Main-zone power."""
        return self._power

    @property
    def power_on(self) -> bool | None:
        """DEPRECATED, removed in 3.0. Use `power.value`."""
        warn_deprecated("power_on", "power.value")
        return self._power.value

    async def set_power(self, on: bool) -> None:
        """DEPRECATED, removed in 3.0. Use `power.set()`."""
        warn_deprecated("set_power()", "power.set()")
        await self._power.set(on)

    # -- volume & mute --------------------------------------------------------

    @property
    def volume(self) -> SteppableControl:
        """Main-zone volume - see NumericControl.range for the advisory
        contract, and max_volume for the live user ceiling."""
        return self._volume

    @property
    def max_volume(self) -> float | None:
        """DEPRECATED, removed in 3.0. Use `volume.maximum_volume`, and
        `isinstance(volume, VolumeControl)` for the capability.

        Kept one release with a warning rather than removed outright,
        because that is the window a consumer needs to change a pin and
        change code in separate commits.

        The reason it moved is issue #54: None here means two different
        things - the model has no MAXVOL command (the whole TDAI family)
        or it has one and has not answered yet - and nothing in the type
        tells them apart, so `max_volume is None` reads as a capability
        check and is wrong on an MP that has simply not replied. It was
        the last property on the receiver whose None varied at runtime.

        On the control that ambiguity is gone: a model without the
        feature has no VolumeControl, so `maximum_volume` is left meaning
        only "not reported yet".
        """
        warnings.warn(
            "max_volume is deprecated and will be removed in lyngdorf 3.0; "
            "use volume.maximum_volume (and isinstance(volume, "
            "VolumeControl) for the capability)",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._max_volume

    @property
    def mute(self) -> Switch:
        """Main-zone mute."""
        return self._mute

    @property
    def muted(self) -> bool | None:
        """DEPRECATED, removed in 3.0. Use `mute.value`."""
        warn_deprecated("muted", "mute.value")
        return self._mute.value

    async def set_muted(self, muted: bool) -> None:
        """DEPRECATED, removed in 3.0. Use `mute.set()`."""
        warn_deprecated("set_muted()", "mute.set()")
        await self._mute.set(muted)

    # -- selections and readings (None where the model's protocol lacks them) --

    @property
    def source_selector(self) -> Selector | None:
        """None on TDAI-2170, which reports a fixed source only."""
        return self._source_selector

    @property
    def sound_mode_selector(self) -> Selector | None:
        return self._sound_mode_selector

    @property
    def room_perfect_position_selector(self) -> Selector | None:
        return self._room_perfect_position_selector

    @property
    def voicing_selector(self) -> Selector | None:
        return self._voicing_selector

    @property
    def audio_information_reading(self) -> Reading | None:
        return self._audio_information_reading

    @property
    def video_information_reading(self) -> Reading | None:
        return self._video_information_reading

    @property
    def audio_input_reading(self) -> Reading | None:
        return self._audio_input_reading

    @property
    def video_input_reading(self) -> Reading | None:
        return self._video_input_reading

    @property
    def streaming_source_reading(self) -> Reading | None:
        return self._streaming_source_reading

    @property
    def source(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `source_selector.value`."""
        warn_deprecated("source", "source_selector.value")
        if self._source_selector is not None:
            return self._source_selector.value
        return self._fixed_source

    @property
    def sources(self) -> list[str]:
        """DEPRECATED, removed in 3.0. Use `source_selector.options`."""
        warn_deprecated("sources", "source_selector.options")
        return list(self._sources.values())

    async def set_source(self, name: str) -> None:
        """DEPRECATED, removed in 3.0. Use `source_selector.select()`.

        Raises LyngdorfInvalidValueError for a name not in sources
        (unchanged 1.x semantics - the wire carries an index)."""
        warn_deprecated("set_source()", "source_selector.select()")
        index = self._sources.lookupIndex(name)
        if index < 0:
            raise LyngdorfInvalidValueError(
                f"{name} is not a valid source name, and cannot be chosen"
            )
        self._api.change_source(index)

    @property
    def sound_mode(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `sound_mode_selector.value`."""
        warn_deprecated("sound_mode", "sound_mode_selector.value")
        return _value(self._sound_mode_selector)

    @property
    def sound_modes(self) -> list[str]:
        """DEPRECATED, removed in 3.0. Use `sound_mode_selector.options`."""
        warn_deprecated("sound_modes", "sound_mode_selector.options")
        return list(self._sound_modes.values())

    async def set_sound_mode(self, name: str) -> None:
        """DEPRECATED, removed in 3.0. Use `sound_mode_selector.select()`."""
        warn_deprecated("set_sound_mode()", "sound_mode_selector.select()")
        index = self._sound_modes.lookupIndex(name)
        if index < 0:
            raise LyngdorfInvalidValueError(
                f"{name} is not a valid sound mode name, and cannot be chosen"
            )
        self._api.change_sound_mode(index)

    @property
    def room_perfect_position(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use
        `room_perfect_position_selector.value`."""
        warn_deprecated("room_perfect_position", "room_perfect_position_selector.value")
        return _value(self._room_perfect_position_selector)

    @property
    def room_perfect_positions(self) -> list[str]:
        """DEPRECATED, removed in 3.0. Use
        `room_perfect_position_selector.options`."""
        warn_deprecated(
            "room_perfect_positions", "room_perfect_position_selector.options"
        )
        return list(self._room_perfect_positions.values())

    async def set_room_perfect_position(self, name: str) -> None:
        """DEPRECATED, removed in 3.0. Use
        `room_perfect_position_selector.select()`."""
        warn_deprecated(
            "set_room_perfect_position()", "room_perfect_position_selector.select()"
        )
        index = self._room_perfect_positions.lookupIndex(name)
        if index < 0:
            raise LyngdorfInvalidValueError(
                f"{name} is not a valid RoomPerfect position, and cannot be chosen"
            )
        self._api.change_room_perfect_position(index)

    @property
    def voicing(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `voicing_selector.value`."""
        warn_deprecated("voicing", "voicing_selector.value")
        return _value(self._voicing_selector)

    @property
    def voicings(self) -> list[str]:
        """DEPRECATED, removed in 3.0. Use `voicing_selector.options`."""
        warn_deprecated("voicings", "voicing_selector.options")
        return list(self._voicings.values())

    async def set_voicing(self, name: str) -> None:
        """DEPRECATED, removed in 3.0. Use `voicing_selector.select()`."""
        warn_deprecated("set_voicing()", "voicing_selector.select()")
        index = self._voicings.lookupIndex(name)
        if index < 0:
            raise LyngdorfInvalidValueError(
                f"{name} is not a valid voicing, and cannot be chosen"
            )
        self._api.change_voicing(index)

    @property
    def audio_input(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `audio_input_reading.value`."""
        warn_deprecated("audio_input", "audio_input_reading.value")
        return _value(self._audio_input_reading)

    @property
    def audio_inputs(self) -> list[str]:
        """DEPRECATED, removed in 3.0. Use `audio_input_reading.options`."""
        warn_deprecated("audio_inputs", "audio_input_reading.options")
        return list(self._audio_inputs.values())

    @property
    def audio_information(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `audio_information_reading.value`."""
        warn_deprecated("audio_information", "audio_information_reading.value")
        return _value(self._audio_information_reading)

    @property
    def video_input(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `video_input_reading.value`."""
        warn_deprecated("video_input", "video_input_reading.value")
        return _value(self._video_input_reading)

    @property
    def video_inputs(self) -> list[str]:
        """DEPRECATED, removed in 3.0. Use `video_input_reading.options`."""
        warn_deprecated("video_inputs", "video_input_reading.options")
        return list(self._video_inputs.values())

    @property
    def video_information(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `video_information_reading.value`."""
        warn_deprecated("video_information", "video_information_reading.value")
        return _value(self._video_information_reading)

    @property
    def streaming_source(self) -> str | None:
        """DEPRECATED, removed in 3.0. Use `streaming_source_reading.value`."""
        warn_deprecated("streaming_source", "streaming_source_reading.value")
        return _value(self._streaming_source_reading)

    @property
    def stream_types(self) -> list[str]:
        """DEPRECATED, removed in 3.0. Use `streaming_source_reading.options`."""
        warn_deprecated("stream_types", "streaming_source_reading.options")
        return list(self._stream_types.values())

    # -- numeric controls ------------------------------------------------------

    @property
    def trims(self) -> Mapping[Trim, NumericControl]:
        """Only the bands this model has appear as keys (design §5);
        narrow steppability with isinstance(ctl, SteppableControl)."""
        return self._trims

    @property
    def lipsync(self) -> NumericControl | None:
        """None on the whole TDAI family. .range is the LIVE LIPSYNCRANGE
        value, seeded from the documented default.

        `.value` is an `int`, restoring 1.10's behaviour (issue #56).
        2.0.0 and 2.0.1 returned a float, which changed the state string
        a consumer renders; 2.0.2 put it back.

        A consumer sees `50.0` where 1.x gave `50`. In Home Assistant
        that is the entity's state string, so it changes recorded history
        and breaks templates comparing against "50". It has already
        reached users: adopting the control-based read changed the format
        at that moment, unannounced because unknown.

        It followed from folding lipsync into NumericControl, whose
        `value` is `float | None` because volume and the trims are
        genuinely fractional. An earlier version of this docstring
        defended it, on the grounds that a per-control value type would
        push a union onto every consumer to spare one control a trailing
        zero. That misdescribed the case, and is corrected here rather
        than deleted so the argument is not made a third time: lipsync's
        integer-ness is STRUCTURAL. All six models with lipsync have step
        1.0, `_lipsync_range_callback` hardcodes that step instead of
        reading it from the device, and `build_lipsync` states that no
        model steps lipsync. A control advertising `step=1.0` while
        holding `50.0` contradicts itself.

        No union is needed to fix it - an `int` satisfies a `float`
        annotation under the numeric tower - and note for whoever does:
        snapping to the step is NOT enough, `round(50.0 / 1.0) * 1.0` is
        `50.0` and still renders "50.0". It must be coerced."""
        return self._lipsync

    # -- components -------------------------------------------------------------

    @property
    def zone_b(self) -> ZoneB | None:
        return self._zone_b

    @property
    def player(self) -> Player | None:
        return self._player

    @property
    def remote(self) -> Remote | None:
        return self._remote

    # -- wire-callback registration ---------------------------------------

    def _register_callback(
        self, msg: Msg, callback: Callable[[str, str], None]
    ) -> None:
        """Register a callback for a message, skipping cleanly if the
        connected model's protocol doesn't define that message.

        Model-specific registration (which messages apply to a given
        family, and under what shape) is handled by the per-family
        dialect groups in _register_callbacks. This catch is a safety net
        for anything not covered by those groups - so an unexpected
        protocol gap degrades a single feature instead of breaking
        connection setup entirely.
        """
        try:
            command = self._model.config.lookup_command(msg)
        except KeyError:
            _LOGGER.warning(
                "Model %s does not support message %s; skipping callback registration",
                self._model,
                msg,
            )
            return
        self._api.register_callback(command, callback)

    def _gating_object(self, msg: Msg) -> object | None:
        """The object a message feeds, for messages whose callback only
        exists to fill a Reading or Selector; messages with no entry
        always register."""
        return {
            Msg.AUDIO_IN: self._audio_input_reading,
            Msg.VIDEO_IN: self._video_input_reading,
            Msg.VIDEO_TYPE: self._video_information_reading,
            Msg.AUDIO_TYPE: self._audio_information_reading,
            Msg.STREAM_TYPE: self._streaming_source_reading,
            Msg.AUDIO_MODE: self._sound_mode_selector,
            Msg.AUDIO_MODES_COUNT: self._sound_mode_selector,
        }.get(msg, _ALWAYS)

    def _register_dialect_group(self, group: Sequence[tuple[Msg, str]]) -> None:
        for msg, attr in group:
            if self._gating_object(msg) is None:
                continue
            self._register_callback(msg, resolve_attr(self, attr))

    def _register_callbacks(self) -> None:
        """Register every wire callback for this model. Sync and
        idempotent-by-construction on the api's dispatch registry; called
        by connect(), and directly by tests that drive _process_event
        without a socket."""
        self._register_callback(Msg.DEVICE, self._name_callback)
        self._register_callback(Msg.VOLUME, self._volume_callback)
        if isinstance(self._volume, VolumeControl):
            self._register_callback(Msg.MAX_VOLUME, self._max_volume_callback)
        self._register_callback(Msg.POWER, self._power_callback)
        for group in (
            self._dialect.mute,
            self._dialect.source,
            self._dialect.room_perfect_position,
            self._dialect.voicing,
            self._dialect.video,
            self._dialect.zone_b,
            self._dialect.surround_trim,
        ):
            self._register_dialect_group(group)
        if Trim.BASS in self._trims:
            self._register_callback(Msg.TRIM_BASS, self._trim_bass_callback)
        if Trim.TREBLE in self._trims:
            self._register_callback(Msg.TRIM_TREBLE, self._trim_treble_callback)
        if self._audio_information_reading is not None:
            self._register_callback(Msg.AUDIO_TYPE, self._audio_info_callback)
        if self._sound_mode_selector is not None:
            self._register_callback(
                Msg.AUDIO_MODES_COUNT, self._sound_modes.count_callback
            )
            self._register_callback(Msg.AUDIO_MODE, self._sound_mode_callback)
        if self._lipsync is not None:
            self._register_callback(Msg.LIP_SYNC, self._lipsync_callback)
            self._register_callback(Msg.LIP_SYNC_MIN_MAX, self._lipsync_range_callback)

    # -- wire callbacks --------------------------------------------------------

    def _name_callback(self, param1: str, param2: str) -> None:
        if param1 != self._name:
            self._name = param1

    def _volume_callback(self, param1: str, ignored: str) -> None:
        self._volume._update_value(convert_decibel(param1))
        self._notify_notification_callbacks()

    def _max_volume_callback(self, param1: str, ignored: str) -> None:
        self._max_volume = convert_decibel(param1)
        if isinstance(self._volume, VolumeControl):
            self._volume._update_maximum_volume(self._max_volume)
        self._notify_notification_callbacks()

    def _zone_b_volume_callback(self, param1: str, ignored: str) -> None:
        if (zb := self._zone_b) is not None:
            zb.volume._update_value(convert_decibel(param1))
        self._notify_notification_callbacks()

    def _mute_callback(self, param1: str, param2: str) -> None:
        self._mute._update(param1 == "ON")
        self._notify_notification_callbacks()

    def _mute_on_callback(self, param1: str, param2: str) -> None:
        self._mute._update(True)
        self._notify_notification_callbacks()

    def _mute_off_callback(self, param1: str, param2: str) -> None:
        self._mute._update(False)
        self._notify_notification_callbacks()

    def _zone_b_mute_on_callback(self, param1: str, param2: str) -> None:
        if (zb := self._zone_b) is not None:
            zb._mute._update(True)
        self._notify_notification_callbacks()

    def _zone_b_mute_off_callback(self, param1: str, param2: str) -> None:
        if (zb := self._zone_b) is not None:
            zb._mute._update(False)
        self._notify_notification_callbacks()

    @staticmethod
    def _set_selector(selector: Selector | None, name: str | None) -> None:
        if selector is not None:
            selector._update(name)

    def _set_source(self, name: str | None) -> None:
        if self._source_selector is not None:
            self._source_selector._update(name)
        else:
            self._fixed_source = name

    def _source_callback(self, param1: str, param2: str) -> None:
        if self._sources.is_full():
            self._set_source(param2)
            self._notify_notification_callbacks()
        else:
            self._sources.add(int(param1), param2)

    def _source_name_callback(self, param1: str, param2: str) -> None:
        index_str, _, name = param1.partition(",")
        name = name.strip('"')
        if self._sources.is_full():
            self._set_source(name)
            self._notify_notification_callbacks()
        else:
            self._sources.add(int(index_str), name)

    def _sources_enabled_callback(self, param1: str, param2: str) -> None:
        from .rio import populate_fixed_list

        populate_fixed_list(
            self._sources, self._model.config.fixed_sources or {}, param1
        )

    def _fixed_source_callback(self, param1: str, param2: str) -> None:
        self._set_source(self._sources.get(int(param1)))
        self._notify_notification_callbacks()

    def _zone_b_source_callback(self, param1: str, param2: str) -> None:
        if (zb := self._zone_b) is not None:
            if zb._sources.is_full():
                zb._source_selector._update(param2)
            else:
                zb._sources.add(int(param1), param2)
        self._notify_notification_callbacks()

    def _name_audio_input(self, param1: str) -> str:
        """Map a reported audio-input index to its name, complaining once
        if we have no entry for it.

        The protocol offers no way to enumerate audio inputs. There is
        `!SRCS` for sources, but nothing equivalent here - the device
        answers `!AUDIN(X)` with a bare integer and the vendor manual
        says "See table of audio inputs for the translation of the number
        to actual audio input". So the table in ModelConfig is not a
        convenience, it is the only mapping that exists, and it is
        maintained by hand from manuals and measurement.

        Which means an index we do not have is a defect in this library's
        data, not a device fault - and the user sees "audio-13" where a
        real name belongs. The fallback keeps things working; the warning
        is how the gap ever gets fixed. Latched per index so a device
        pushing !AUDIN on every source change produces one line, not one
        per change.
        """
        index = int(param1)
        known = self._audio_inputs.get(index)
        if known is not None:
            return known
        if index not in self._unknown_audio_inputs:
            self._unknown_audio_inputs.add(index)
            _LOGGER.warning(
                "%s: %s reported audio input %d, which this library has no "
                "name for - showing 'audio-%d' instead. This is a gap in "
                "the library's input table for this model, not a device "
                "fault; please report it with the model and firmware.",
                self.host,
                self._model.config.model_name,
                index,
                index,
            )
        return f"audio-{param1}"

    def _audio_input_callback(self, param1: str, param2: str) -> None:
        if (reading := self._audio_input_reading) is not None:
            reading._update(self._name_audio_input(param1))
        self._notify_notification_callbacks()

    def _zone_b_audio_input_callback(self, param1: str, param2: str) -> None:
        if (zb := self._zone_b) is not None:
            if (reading := zb._audio_input_reading) is not None:
                reading._update(self._name_audio_input(param1))
        self._notify_notification_callbacks()

    def _video_input_callback(self, param1: str, param2: str) -> None:
        if (reading := self._video_input_reading) is not None:
            reading._update(self._video_inputs.get(int(param1), f"video-{param1}"))
        self._notify_notification_callbacks()

    def _stream_type_callback(self, param1: str, param2: str) -> None:
        if (reading := self._streaming_source_reading) is not None:
            reading._update(self._stream_types.get(int(param1), f"video-{param1}"))
        self._notify_notification_callbacks()

    def _zone_b_stream_type_callback(self, param1: str, param2: str) -> None:
        if (zb := self._zone_b) is not None:
            if (reading := zb._streaming_source_reading) is not None:
                reading._update(self._stream_types.get(int(param1), f"video-{param1}"))
        self._notify_notification_callbacks()

    def _audio_info_callback(self, param1: str, param2: str) -> None:
        if (reading := self._audio_information_reading) is not None:
            reading._update(param1)
        self._notify_notification_callbacks()

    def _video_info_callback(self, param1: str, param2: str) -> None:
        if (reading := self._video_information_reading) is not None:
            reading._update(param1)
        self._notify_notification_callbacks()

    def _sound_mode_callback(self, param1: str, param2: str) -> None:
        if self._sound_modes.is_full():
            self._set_selector(self._sound_mode_selector, param2)
            self._notify_notification_callbacks()
        else:
            self._sound_modes.add(int(param1), param2)

    def _power_callback(self, param1: str, param2: str) -> None:
        is_on = self._model.config.power_state_on == param1
        self._power._update(is_on)
        if is_on:
            self._requery_mute()
        if self._poll is not None:
            self._poll.set_power_state(is_on)
        self._notify_notification_callbacks()

    def _requery_mute(self) -> None:
        mute_cmd = self._model.config.lookup_command(Msg.MUTE)
        self._api._writeCommand(f"{mute_cmd}?")

    def _zone_b_power_callback(self, param1: str, param2: str) -> None:
        if (zb := self._zone_b) is not None:
            zb._power._update(self._model.config.power_state_on == param1)
            if self._model.config.power_state_on == param1:
                self._requery_zone_b_mute()
        self._notify_notification_callbacks()

    def _requery_zone_b_mute(self) -> None:
        if self._zone_b is None:
            return
        try:
            mute_cmd = self._model.config.lookup_command(Msg.ZONE_B_MUTE)
            self._api._writeCommand(f"{mute_cmd}?")
        except KeyError:
            pass

    def _room_perfect_position_callback(self, param1: str, param2: str) -> None:
        if self._room_perfect_positions.is_full():
            self._set_selector(self._room_perfect_position_selector, param2)
            self._notify_notification_callbacks()
        else:
            self._room_perfect_positions.add(int(param1), param2)

    def _room_perfect_position_name_callback(self, param1: str, param2: str) -> None:
        index_str, _, name = param1.partition(",")
        name = name.strip('"')
        if self._room_perfect_positions.is_full():
            self._set_selector(self._room_perfect_position_selector, name)
            self._notify_notification_callbacks()
        else:
            self._room_perfect_positions.add(int(index_str), name)

    def _room_perfect_positions_present_callback(
        self, param1: str, param2: str
    ) -> None:
        from .rio import populate_fixed_list

        populate_fixed_list(
            self._room_perfect_positions,
            self._model.config.room_perfect_positions or {},
            param1,
        )

    def _fixed_room_perfect_position_callback(self, param1: str, param2: str) -> None:
        self._set_selector(
            self._room_perfect_position_selector,
            self._room_perfect_positions.get(int(param1)),
        )
        self._notify_notification_callbacks()

    def _voicing_callback(self, param1: str, param2: str) -> None:
        if self._voicings.is_full():
            self._set_selector(self._voicing_selector, param2)
            self._notify_notification_callbacks()
        else:
            self._voicings.add(int(param1), param2)

    def _voicing_name_callback(self, param1: str, param2: str) -> None:
        index_str, _, name = param1.partition(",")
        name = name.strip('"')
        if self._voicings.is_full():
            self._set_selector(self._voicing_selector, name)
            self._notify_notification_callbacks()
        else:
            self._voicings.add(int(index_str), name)

    def _voicings_enabled_callback(self, param1: str, param2: str) -> None:
        from .rio import populate_fixed_list

        populate_fixed_list(
            self._voicings, self._model.config.fixed_voicings or {}, param1
        )

    def _fixed_voicing_callback(self, param1: str, param2: str) -> None:
        self._set_selector(self._voicing_selector, self._voicings.get(int(param1)))
        self._notify_notification_callbacks()

    def _lipsync_callback(self, param1: str, param2: str) -> None:
        """Store lipsync as an INT, as 1.x did (issue #56).

        1.10 did `self._lipsync = int(param1)` and typed the property
        `int | None`. 2.0 folded lipsync into NumericControl, whose value
        is `float | None` for volume and the trims, and every value
        became a float - so a consumer saw `50.0` where 1.x gave `50`.
        That is the entity's state STRING in Home Assistant, so it
        changes recorded history and breaks templates comparing against
        "50". Nobody decided it; it fell out of the refactor.

        The coercion lives here rather than in NumericControl, and that
        is the narrower of two options that were both implemented. The
        general form keyed off `range.step`, so any control the device
        treats as integral agreed with its own step - correct, and it
        also caught bass/treble on the TDAI family, whose step is 1.0
        where the MP family's is 0.1.

        Scoped back to lipsync because correctness was not the deciding
        axis - both versions are correct. Cost was. Restoring lipsync is
        a net-zero change across the upgrade: `int` in 1.10, float in
        1.11/2.0.1, `int` again here. Coercing the TDAI trims would have
        been a NEW user-visible change for owners who never had a
        defect, since `convert_decibel` has returned a float on every
        path in every version - spending a broken template on tidiness a
        step nobody reads.

        The general form remains the right end state and is recorded in
        #56 as consciously scoped out, to be done in a release where it
        is the announced change rather than a side effect of this one.

        `round(float(...))` rather than 1.x's `int(param1)`: it yields an
        int just the same, and survives a device that answers "50.0"
        where 1.x would have raised ValueError.
        """
        if (ls := self._lipsync) is not None:
            ls._update_value(round(float(param1)))
        self._notify_notification_callbacks()

    def _lipsync_range_callback(self, param1: str, ignored: str) -> None:
        min_str, _, max_str = param1.partition(",")
        if (ls := self._lipsync) is not None:
            ls._update_range(
                NumericRange(min=float(min_str), max=float(max_str), step=1.0)
            )
        self._notify_notification_callbacks()

    def _trim_bass_callback(self, param1: str, ignored: str) -> None:
        if (ctl := self._trims.get(Trim.BASS)) is not None:
            ctl._update_value(
                convert_decibel(param1, self._model.config.trim_bass_treble_scale)
            )
        self._notify_notification_callbacks()

    def _trim_treble_callback(self, param1: str, ignored: str) -> None:
        if (ctl := self._trims.get(Trim.TREBLE)) is not None:
            ctl._update_value(
                convert_decibel(param1, self._model.config.trim_bass_treble_scale)
            )
        self._notify_notification_callbacks()

    def _trim_centre_callback(self, param1: str, ignored: str) -> None:
        if (ctl := self._trims.get(Trim.CENTER)) is not None:
            ctl._update_value(convert_decibel(param1))
        self._notify_notification_callbacks()

    def _trim_height_callback(self, param1: str, ignored: str) -> None:
        if (ctl := self._trims.get(Trim.HEIGHT)) is not None:
            ctl._update_value(convert_decibel(param1))
        self._notify_notification_callbacks()

    def _trim_lfe_callback(self, param1: str, ignored: str) -> None:
        if (ctl := self._trims.get(Trim.LFE)) is not None:
            ctl._update_value(convert_decibel(param1))
        self._notify_notification_callbacks()

    def _trim_surround_callback(self, param1: str, ignored: str) -> None:
        if (ctl := self._trims.get(Trim.SURROUND)) is not None:
            ctl._update_value(convert_decibel(param1))
        self._notify_notification_callbacks()

    def _now_playing_changed(self, np: NowPlaying | None) -> None:
        self._notify_notification_callbacks()

    def _play_mode_changed(self, mode: PlayMode | None) -> None:
        self._notify_notification_callbacks()

    def _notify_notification_callbacks(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            for callback in self._notification_callbacks:
                try:
                    callback()
                except Exception:
                    _LOGGER.exception("Event callback caused an unhandled exception")
            return
        asyncio.create_task(self._async_notify_notification_callbacks())

    async def _async_notify_notification_callbacks(self) -> None:
        for callback in self._notification_callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.exception("Event callback caused an unhandled exception")
