"""The gated components of a LyngdorfReceiver: ZoneB, Player and Remote.

Each is None on a model without the feature (2.0 design §5, tier 1) - the
receiver layer (WP4) calls the build_* factories once at construction and
the attribute is thereby structural: `if receiver.zone_b:` replaces 1.x's
has_zone_b_feature().

Components own their cached state behind internal _update_* methods; the
receiver's wire callbacks parse device replies (that is receiver-layer
work - design §4) and hand finished values in. Writes go through
constructor-injected internals: RioClient writer methods for ZoneB and
Remote, the streaming engine's transport methods for Player.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .base import CountingNumberDict
from .controls import SteppableControl
from .exceptions import LyngdorfInvalidValueError, LyngdorfUnsupportedError
from .remote import RemoteKey, resolve_remote_key
from .rio import RioClient


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
