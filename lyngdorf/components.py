"""The gated components of a LyngdorfReceiver: ZoneB, Player and Remote.

Each is None on a model without the feature (2.0 design §5, tier 1) - the
receiver layer (WP4) calls the build_* factories once at construction and
the attribute is thereby structural: `if receiver.zone_b:` replaces 1.x's
ModelConfig.has_zone_b.

Components own their cached state behind internal _update_* methods; the
receiver's wire callbacks parse device replies (that is receiver-layer
work - design §4) and hand finished values in. Writes go through
constructor-injected internals: RioClient writer methods for ZoneB and
Remote, the streaming engine's transport methods for Player.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Protocol

from .base import CountingNumberDict
from .controls import SteppableControl
from .exceptions import LyngdorfInvalidValueError, LyngdorfUnsupportedError
from .models import LyngdorfModel
from .remote import RemoteKey, resolve_remote_key
from .rio import RioClient
from .states import Control, PlayMode, Repeat
from .streaming import NowPlaying


class ZoneB:
    """Zone B (Zone 2) of an MP- or P-series processor.

    Mirrors the main-zone shapes exactly - power/set_power,
    volume (SteppableControl), muted/set_muted, source/sources/set_source,
    plus the read-only audio_input and streaming_source - so a consumer's
    mental model transfers one-to-one (design §2.4). Zone B has exactly
    what the hardware has: no sound_mode, no trims, so nothing here can
    raise "unsupported".
    """

    def __init__(self, *, volume: SteppableControl, rio: RioClient) -> None:
        self._rio = rio
        self._volume = volume
        self._sources = CountingNumberDict()
        self._power_on: bool | None = None
        self._muted: bool | None = None
        self._source: str | None = None
        self._audio_input: str | None = None
        self._streaming_source: str | None = None

    @property
    def power_on(self) -> bool | None:
        """Zone B power state, or None until the device reports it."""
        return self._power_on

    async def set_power(self, on: bool) -> None:
        """Power Zone B on or off (queued for paced delivery)."""
        self._rio.zone_b_power_on(on)

    @property
    def volume(self) -> SteppableControl:
        """Zone B volume - SteppableControl statically: every model with
        a Zone B steps ZVOL (design §2.3)."""
        return self._volume

    @property
    def muted(self) -> bool | None:
        """Zone B mute state, or None until the device reports it."""
        return self._muted

    async def set_muted(self, muted: bool) -> None:
        """Mute or unmute Zone B (queued for paced delivery)."""
        self._rio.zone_b_mute_enabled(muted)

    @property
    def source(self) -> str | None:
        """The current Zone B source name, or None until reported."""
        return self._source

    @property
    def sources(self) -> list[str]:
        """Selectable Zone B sources, in the device's own index order."""
        return list(self._sources.values())

    async def set_source(self, name: str) -> None:
        """Select a Zone B source by name.

        Raises LyngdorfInvalidValueError for a name not in `sources`
        (unchanged 1.x semantics): the wire carries an index, so an
        unknown name has no index to send.
        """
        index = self._sources.lookupIndex(name)
        if index < 0:
            raise LyngdorfInvalidValueError(
                f"{name} is not a valid Zone B source name, and cannot be chosen"
            )
        self._rio.change_zone_b_source(index)

    @property
    def audio_input(self) -> str | None:
        """The physical audio input feeding Zone B, or None."""
        return self._audio_input

    @property
    def streaming_source(self) -> str | None:
        """The active Zone B streaming source type, or None."""
        return self._streaming_source

    # -- internal wiring surface (receiver-layer callbacks, WP4) ----------

    def _update_power(self, on: bool | None) -> None:
        self._power_on = on

    def _update_muted(self, muted: bool | None) -> None:
        self._muted = muted

    def _update_source(self, name: str | None) -> None:
        self._source = name

    def _update_audio_input(self, name: str | None) -> None:
        self._audio_input = name

    def _update_streaming_source(self, name: str | None) -> None:
        self._streaming_source = name


def build_zone_b(rio: RioClient) -> ZoneB | None:
    """The ZoneB component, or None on a model without Zone B (the whole
    TDAI family - design §2.4)."""
    config = rio._model.config
    if not config.has_zone_b:
        return None
    zvol_range = config.zone_b_volume_range
    assert zvol_range is not None, "has_zone_b models document a ZVOL range"
    volume = SteppableControl(
        initial_range=zvol_range,
        send_set=rio.zone_b_volume,
        send_up=rio.zone_b_volume_up,
        send_down=rio.zone_b_volume_down,
    )
    return ZoneB(volume=volume, rio=rio)


class Remote:
    """The remote-key surface (design §2.6). None on the whole TDAI
    family - see build_remote.

    Behaviour relocated verbatim from 1.x's Receiver.press /
    send_remote_commands (the 1.10.0 remote-key work, issue #46): batch
    validation before any send, case-insensitive string resolution, block
    repeats, no delay_secs (the write queue owns pacing). Do not redesign
    any of it here.
    """

    def __init__(
        self,
        *,
        model_name: str,
        keys: frozenset[RemoteKey],
        send_key: Callable[[RemoteKey], None],
    ) -> None:
        self._model_name = model_name
        self._keys = keys
        self._send_key = send_key

    @property
    def keys(self) -> frozenset[RemoteKey]:
        """Every remote-control button this model's protocol documents
        at all.

        An explicit per-model set (see `ModelConfig.remote_keys`), never
        inferred from whether some unrelated wire command happens to
        succeed. Empty for the whole TDAI family, which has no
        navigation hardware at all; the MP and P families both populate
        the full button set their manual documents - see
        `lyngdorf/remote.py` for the per-model wire tables.

        Feeds both a consumer's advertised command list (e.g. Home
        Assistant's `remote` platform) and its own input validation, so
        it never has to guess what this model supports.
        """
        return self._keys

    async def press(self, key: RemoteKey) -> None:
        """Press a single remote key.

        Typed convenience for a caller that already has a `RemoteKey`
        and is not going through strings at all. `send` is the entry
        point shaped for Home Assistant's
        `RemoteEntity.async_send_command`; this delegates to it with a
        single-item batch so the two can never validate or dispatch
        differently.

        Raises:
            LyngdorfUnsupportedError: this model does not have `key`.
        """
        await self.send([key])

    async def send(
        self, commands: Iterable[str | RemoteKey], num_repeats: int = 1
    ) -> None:
        """Send a batch of remote-key presses, in order.

        Shaped to match Home Assistant's
        `RemoteEntity.async_send_command` exactly -
        `command: Iterable[str]` plus `num_repeats` - so the integration
        needs no translation layer:

            async def async_send_command(self, command, **kwargs):
                await self._remote.send(
                    command, num_repeats=kwargs.get(ATTR_NUM_REPEATS, 1)
                )

        Also accepts `RemoteKey` directly, for callers that are not going
        through strings at all.

        Every command is resolved to a `RemoteKey` - case-insensitively
        for strings, so `up`/`UP`/`Up` all resolve the same way, see
        `resolve_remote_key` - and checked against `keys` for *this
        whole batch* before anything is sent. A typo (or a key this
        model does not have) partway through a batch of six therefore
        raises before the first of the other five reaches the device,
        rather than leaving the device half navigated through a menu on
        the way to discovering the mistake.

        Raises:
            LyngdorfUnsupportedError: some `commands` entry does not
                resolve to a `RemoteKey` this model has, naming the bad
                value and what this model does support.

        `num_repeats` repeats the whole resolved sequence as a block -
        `["1", "2", "3"]` with `num_repeats=2` sends `1 2 3 1 2 3`, not
        `1 1 2 2 3 3` - matching how Home Assistant's own integrations
        interpret the same field (`broadlink`'s `remote.py` and
        `harmony`'s `data.py` both repeat the sequence, not each
        individual command; "the number of times you want to repeat the
        commands" reads the same way). Do not swap the loop nesting back
        to per-key repeats - a caller entering a channel number twice
        (`num_repeats=2` over `["1", "2", "3"]`) must see `123123`
        reach the device, not `112233`. The outbound write queue already
        paces every write and never coalesces a remote key (see
        `RioClient.send_remote_key`), so nothing further is needed here
        for the repeated sequence to reach the device as that many
        distinct, in-order wire commands.

        `delay_secs`, which `RemoteEntity.async_send_command` also
        accepts, is deliberately NOT supported here: the write queue
        already owns pacing (`COMMAND_PACING_MS`), and a second,
        caller-supplied delay on top of it would fight that rather than
        cooperate with it. An integration should drop that argument
        rather than have this library grow a second timing mechanism.
        """
        resolved: list[RemoteKey] = []
        for command in commands:
            key = resolve_remote_key(command)
            if key is None or key not in self._keys:
                raise LyngdorfUnsupportedError(
                    f"{command!r} is not a supported remote key for model "
                    f"{self._model_name} (available: "
                    f"{sorted(self._keys) or 'none'})"
                )
            resolved.append(key)

        for _ in range(num_repeats):
            for key in resolved:
                self._send_key(key)


def build_remote(rio: RioClient) -> Remote | None:
    """The Remote component, or None on a model with no remote keys at
    all (the whole TDAI family). The key set is the model's explicit
    per-family table (ModelConfig.remote_keys), never inferred - see
    issue #46."""
    model = rio._model
    keys = model.config.available_remote_keys()
    if not keys:
        return None
    return Remote(
        model_name=model.config.model_name,
        keys=keys,
        send_key=rio.send_remote_key,
    )


class NowPlayingEngine(Protocol):
    """What Player consumes from the streaming engine - structural,
    deliberately.

    In WP3/WP4 the engine is the 1.x LyngdorfApi, which already satisfies
    every member with no edits; when WP5 relocates the poll loop into
    streaming/poll.py (with the session plumbing that must edit the same
    code anyway), the relocated poller satisfies this same protocol and
    Player does not change. Player is this protocol's only consumer.
    """

    @property
    def now_playing(self) -> NowPlaying | None: ...
    @property
    def position_ms(self) -> int | None: ...
    @property
    def position_updated_at(self) -> datetime | None: ...
    @property
    def play_mode(self) -> PlayMode | None: ...
    @property
    def shuffle(self) -> bool | None: ...
    @property
    def repeat(self) -> Repeat | None: ...
    @property
    def available_controls(self) -> frozenset[Control]: ...
    @property
    def available_play_modes(self) -> frozenset[PlayMode]: ...
    @property
    def can_shuffle(self) -> bool: ...
    @property
    def available_repeat_modes(self) -> frozenset[Repeat]: ...

    def register_position_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]: ...
    def register_position_jump_callback(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]: ...

    async def async_pause(self) -> bool: ...
    async def async_next(self) -> bool: ...
    async def async_previous(self) -> bool: ...
    async def async_seek(self, position_ms: int) -> bool: ...
    async def async_set_play_mode(self, mode: PlayMode) -> bool: ...
    async def async_set_shuffle(self, shuffle: bool) -> bool: ...
    async def async_set_repeat(self, repeat: Repeat) -> bool: ...


class Player:
    """The embedded streaming module's surface (:8080) - design §2.5.

    None on models without the module (build_player). Model capability
    ends there: everything on this class is RUNTIME capability, varying
    with the current source, and stays a live predicate (design §5
    tier 2) - a Player that exists still legitimately offers nothing
    while stopped. Transport methods keep their 1.x bool return
    ("HTTP accepted vs network failure", decision D7) and keep raising
    LyngdorfUnsupportedError when the current source does not offer the
    control, because the device answers HTTP 200 to anything and a
    return value alone can never mean "honoured".

    Transport writes deliberately do NOT ride the poll loop's
    StreamingClient (design §8): each takes a fresh connection with an
    explicit Connection: close, so a pause never waits behind an
    in-flight ~25 s long poll. That property lives in the engine's
    transport methods and the session-less write helpers they call -
    preserved by delegation here, and pinned by
    tests/player_test.py::TestTransportWritesBypassThePollLock.
    """

    def __init__(self, engine: NowPlayingEngine) -> None:
        self._engine = engine

    # -- now playing -------------------------------------------------------

    @property
    def now_playing(self) -> NowPlaying | None:
        """Current now-playing metadata, or None if idle/unavailable."""
        return self._engine.now_playing

    # -- position ----------------------------------------------------------

    @property
    def position_ms(self) -> int | None:
        """Elapsed playback position in milliseconds, or None if unknown.

        Pair with `NowPlaying.duration_ms` for a progress percentage.
        Tracked separately from `now_playing` because it updates about
        once a second, which would otherwise churn that object and every
        metadata consumer along with it.
        """
        return self._engine.position_ms

    @property
    def position_updated_at(self) -> datetime | None:
        """When `position_ms` was last refreshed from the device.

        Lets a consumer extrapolate the current position between updates
        instead of displaying a value that visibly lags.
        """
        return self._engine.position_updated_at

    @property
    def position_percent(self) -> float | None:
        """Fraction of the current track played, 0.0-1.0.

        None when either position or duration is unknown, or when the
        duration is zero - live streams report a duration of 0, and a
        progress fraction is meaningless for them.
        """
        now_playing = self._engine.now_playing
        duration = now_playing.duration_ms if now_playing else None
        position_ms = self._engine.position_ms
        if position_ms is None or not duration:
            return None
        return min(1.0, position_ms / duration)

    def on_position(self, callback: Callable[[int | None], None]) -> Callable[[], None]:
        """Register a callback, returning a callable that unregisters it.

        Fires on every raw position change, including the ordinary
        once-a-second progression while playing - for a consumer that
        genuinely wants a live counter. For a consumer where each call
        costs something (a Home Assistant entity state write, say), use
        `on_position_jump` instead.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return self._engine.register_position_callback(callback)

    def on_position_jump(
        self, callback: Callable[[int | None], None]
    ) -> Callable[[], None]:
        """Register a callback for position *discontinuities* only.

        Fires when the position does something other than advance with the
        clock: a seek, a track change, a play or pause, or the stream
        drifting from where it should be. It does not fire for the ordinary
        once-a-second progression, so a consumer that writes state on every
        call stays cheap.

        Use this rather than `on_position` when each call costs something -
        a Home Assistant entity state write, say, which fans out over
        websockets and re-evaluates every automation bound to that entity.

        The returned unsubscribe is idempotent - calling it twice, or after
        the callback has already been removed, is a no-op rather than an
        error, because teardown paths run more than once in practice.
        """
        return self._engine.register_position_jump_callback(callback)

    # -- per-source, runtime-varying transport capability ------------------

    @property
    def can_pause(self) -> bool:
        """Whether the current source offers pause. Narrows and widens as
        the source changes; False whenever nothing is playing."""
        return Control.PAUSE in self._engine.available_controls

    @property
    def can_next(self) -> bool:
        """Whether the current source offers skip-forward."""
        return Control.NEXT_TRACK in self._engine.available_controls

    @property
    def can_previous(self) -> bool:
        """Whether the current source offers skip-back."""
        return Control.PREVIOUS_TRACK in self._engine.available_controls

    @property
    def can_seek(self) -> bool:
        """Whether the current source offers seek.

        AirPlay does not; Spotify Connect does. Note the payload's `live`
        and `audioType` fields say nothing useful about this - both
        sources report `live: true`.
        """
        return Control.SEEK in self._engine.available_controls

    @property
    def can_shuffle(self) -> bool:
        """Whether shuffle can be toggled independently of repeat."""
        return self._engine.can_shuffle

    # -- transport ---------------------------------------------------------

    async def pause(self) -> bool:
        """Toggle pause on the current source.

        The device has no separate resume: on a source it streams itself
        this pauses a playing track and resumes a paused one. On AirPlay
        and other controller-driven sources it instead ends the session,
        which cannot be undone from the device.
        """
        return await self._engine.async_pause()

    async def next_track(self) -> bool:
        """Skip to the next track."""
        return await self._engine.async_next()

    async def previous_track(self) -> bool:
        """Skip to the previous track."""
        return await self._engine.async_previous()

    async def seek(self, position_ms: int) -> bool:
        """Seek to an absolute position, in milliseconds."""
        return await self._engine.async_seek(position_ms)

    # -- play mode ---------------------------------------------------------

    @property
    def play_mode(self) -> PlayMode | None:
        """Current shuffle/repeat mode, or None if unknown/unavailable."""
        return self._engine.play_mode

    @property
    def play_modes(self) -> frozenset[PlayMode]:
        """Shuffle/repeat modes the current source offers, or empty.

        The union of the per-source and global lists - each is a partial
        view of the same 2x3 grid, and taking either alone made `normal`
        unreachable (measured on a real MP-60; the full evidence comment
        lives on the engine's available_play_modes and travels with it
        when WP5 relocates the poll state)."""
        return self._engine.available_play_modes

    @property
    def shuffle(self) -> bool | None:
        """Current shuffle setting, or None if unknown/unavailable."""
        return self._engine.shuffle

    @property
    def repeat(self) -> Repeat | None:
        """Current repeat setting, or None if unknown/unavailable."""
        return self._engine.repeat

    @property
    def repeat_modes(self) -> frozenset[Repeat]:
        """Repeat values reachable from the current shuffle setting."""
        return self._engine.available_repeat_modes

    async def set_play_mode(self, mode: PlayMode) -> bool:
        """Set the combined shuffle/repeat mode."""
        return await self._engine.async_set_play_mode(mode)

    async def set_shuffle(self, shuffle: bool) -> bool:
        """Set shuffle, carrying the current repeat setting over
        unchanged (see the engine's async_set_shuffle for the full
        validation contract)."""
        return await self._engine.async_set_shuffle(shuffle)

    async def set_repeat(self, repeat: Repeat) -> bool:
        """Set repeat, carrying the current shuffle setting over
        unchanged."""
        return await self._engine.async_set_repeat(repeat)


def build_player(model: LyngdorfModel, engine: NowPlayingEngine) -> Player | None:
    """The Player component, or None on a model without the embedded
    streaming module (TDAI-2170, the whole P series - design §2.5)."""
    if not model.config.has_streaming:
        return None
    return Player(engine)
