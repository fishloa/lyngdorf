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

from .base import CountingNumberDict
from .controls import SteppableControl
from .exceptions import LyngdorfInvalidValueError
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
