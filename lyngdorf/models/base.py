"""Base model classes and protocols for Lyngdorf devices.

This module defines the core data structures and protocols that all
Lyngdorf device models must implement.

:license: MIT, see LICENSE for more details.
"""

from dataclasses import dataclass, field
from typing import Protocol

from ..const import POWER_ON, Msg
from ..remote import RemoteKey, RemoteKeyTable


@dataclass(frozen=True)
class NumericRange:
    """The valid range for an adjustable numeric setting (a trim, or
    lipsync), as `(min, max, step)`.

    A value object rather than a bare tuple so a consumer (in particular
    the Home Assistant `number` platform, which needs exactly these three
    fields to build a `NumberEntity`) gets named, self-documenting fields
    instead of having to remember index 0/1/2.

    Both `min`/`max` and `step` are advisory: this library does not
    enforce any of the three on a write. `Receiver.trim_bass`'s setter
    (see device.py) and every other numeric setter send whatever value
    they are given straight to the device, unchecked against this range -
    see `Receiver.volume_range`'s docstring for why (in short: the device
    itself already bounds these values sensibly, so a library check in
    front of it adds nothing but a second place for a legitimate write to
    fail). This exists purely so a consumer can build a correctly-bounded,
    correctly-grained slider without having to know, for example, that the
    MP series' trims are addressable to 0.1 dB (`api.py` encodes
    `int(trim * 10)` on the wire) while the TDAI series' are whole-dB only.

    Frozen (and so hashable/comparable by value) rather than a plain
    class, matching `PlayMode` and `NowPlaying` elsewhere in this
    codebase - there is no mutable state here to protect, just three
    numbers that are meaningless individually.
    """

    min: float
    max: float
    step: float


class ModelCapability(Protocol):
    """Protocol defining what a model configuration must provide.

    This protocol ensures all model configurations have consistent
    interfaces for accessing device capabilities and command mappings.
    """

    @property
    def model_name(self) -> str:
        """Return the model identifier (e.g., 'mp-60', 'tdai-1120')."""
        ...

    @property
    def manufacturer(self) -> str:
        """Return the manufacturer name."""
        ...

    @property
    def messages(self) -> dict[Msg, str]:
        """Return the command protocol mapping for this model."""
        ...

    @property
    def setup_commands(self) -> list[str]:
        """Return the initialization command sequence."""
        ...


@dataclass(frozen=True)
class ModelConfig:
    """Immutable configuration for a specific Lyngdorf device model.

    This dataclass encapsulates all model-specific information including
    protocol commands, hardware capabilities, and supported features.

    Attributes:
        model_name: Model identifier (e.g., 'mp-60', 'tdai-1120')
        manufacturer: Manufacturer name (typically 'Lyngdorf')
        messages: Protocol command mapping (Msg enum -> command string)
        setup_commands: Initialization command sequence
        video_inputs: Video input mapping (index -> name)
        audio_inputs: Audio input mapping (index -> name)
        stream_types: Stream type mapping (index -> name)
        video_outputs: Optional video output mapping
        room_perfect_positions: Fixed Room Perfect position mapping (index
            -> name), used for models whose set of positions is hardware-
            fixed rather than dynamically enumerated over the wire - see
            `fixed_sources`.
        fixed_sources: Fixed source mapping (index -> name), used for
            models whose sources are fixed hardware inputs rather than a
            dynamic, user-configurable list. TDAI-2170 is the only current
            example: it has no count+enumeration burst for sources (no
            SRCLIST), only a bitmask (SRCENABLED) of which of these fixed
            entries are enabled. None for every model with a dynamic list.
        fixed_voicings: Fixed voicing mapping (index -> name), same
            rationale as `fixed_sources` but for voicings (gated by
            VOIENABLED on TDAI-2170 rather than a VOILIST/RPVOIS burst).
        has_zone_b: Whether this model supports Zone B (Zone 2) functionality
        has_video: Whether this model supports video inputs/outputs
        has_surround: Whether this model has discrete per-channel
            multichannel trims (center/height/LFE/surround speaker trims).
            Audio mode selection, audio type, and lip sync are handled
            separately per-model since they don't vary along the same axis
            (e.g. the P-series has audio modes and lip sync but no channel
            trims at all).
        power_state_on: The parameter value in a power-state reply that
            means "powered on". The MP and P families answer `!POWER(1)`,
            so this defaults to "1"; the TDAI family answers `!PWR(ON)`
            and overrides it with "ON".
        mute_state_in_parameter: Whether mute state arrives as a parameter
            on the MUTE message (`!MUTE(ON)` / `!MUTE(OFF)`, the TDAI
            family) rather than as distinct `!MUTEON` / `!MUTEOFF`
            messages (the MP and P families).
        keepalive_message: Message type queried to keep an idle connection
            alive and to detect a dead one (`LyngdorfApi._monitor`). Must be
            a message every model in `messages` actually defines - DEVICE
            is the one truly universal query across every model, including
            TDAI-2170's more limited protocol subset, which doesn't even
            have VERBOSE. None disables the keep-alive query entirely (the
            connection is still torn down and reconnected on prolonged
            silence, just without an active probe first).
        has_streaming: Whether this model has the embedded streaming
            module's separate now-playing HTTP API (see
            lyngdorf/streaming.py, ``:8080``, unrelated to the ``:84`` RIO
            protocol `messages` describes). True for MP-40/50/60 and
            TDAI-1120/3400; False for TDAI-2170 (unconfirmed - only present
            if an optional streaming board is fitted) and the P-series
            (no streaming source at all).
        trim_bass_range, trim_treble_range: The device-documented dB range
            (and UI step granularity) for bass/treble trim, or None on a
            model with no bass/treble trim at all (TDAI-2170). Taken from
            the per-model vendor manuals in docs/ - NOT assumed equal
            across families: the MP series encodes 0.1 dB steps
            (`!TRIMBASS`, "10 = 1dB" per docs/mp-40.md et al) while the
            TDAI series' `!BASS`/`!TREBLE` are documented as whole dB only
            (docs/tdai-1120.md, docs/tdai-3400.md), even though both
            families happen to share the same -12..+12 dB bound.
        trim_bass_treble_scale: How many wire units make up 1 dB on the
            bass/treble trim commands specifically - the write side
            (`LyngdorfApi.change_trim_bass`/`change_trim_treble`) multiplies
            a dB value by this before formatting it onto the wire, and the
            read side (`Receiver._trim_bass_callback`/
            `_trim_treble_callback`) divides by it. Defaults to 10.0 (the
            MP/P family's "10 = 1dB" encoding per docs/mp-40.md et al);
            the TDAI family overrides it to 1.0 since `!BASS`/`!TREBLE`
            are documented as whole dB with no sub-decibel encoding at all
            (docs/tdai-1120.md, docs/tdai-3400.md; TDAI-2210 shares that
            protocol - see models/tdai_series.py). Not used for the
            per-channel trims (centre/height/LFE/surround), which are
            MP-only and always in tenths of a dB - see
            `LyngdorfApi.change_trim_centre` et al, which hardcode ``*10``
            rather than reading this field. See issue #41, where this was
            confirmed on a real TDAI-3400: an amp showing +3 dB on its
            front panel answers `!BASS(3)`, which the old blanket ``*10``
            surfaced as 0.3 dB and would have written back as `!BASS(30)`.

            That mismatch is why a TDAI-3400, under the old blanket ``*10``
            assumption, could be sent a wire value that read back as 4
            rather than the intended dB figure - not because the device
            failed to bound the value, but because the library itself
            multiplied by the wrong scale before the write ever reached
            the wire, producing a wire value that did not correspond to
            the caller's requested dB at all. It was fixed by giving each
            family its own `trim_bass_treble_scale` so a value in the
            documented range always encodes correctly, not by rejecting
            out-of-range values at the setter - the setters do not
            validate against `trim_bass_range`/`trim_treble_range` (or any
            other numeric range) at all; see `Receiver.volume_range`'s
            docstring for why. An MP-60, by contrast, bounds a genuinely
            out-of-range value cleanly and predictably by itself (150
            stores as 120), which is precisely the kind of case where a
            library check in front of the device adds nothing.
        trim_centre_range, trim_height_range, trim_lfe_range,
            trim_surround_range: The device-documented dB range for the
            discrete multichannel speaker trims - MP series only (see
            has_surround); None everywhere else, including the TDAI family
            (which has bass/treble trim but no per-channel trims at all).
        lipsync_default_range: The range to report for `Receiver.lipsync_range`
            before the device has answered a `LIPSYNCRANGE?` query (or on a
            model where it never will, if this is None). The MP and P
            families both map Msg.LIP_SYNC_MIN_MAX and query it at
            startup, so this is a fallback, not the final word - see
            `Receiver._lipsync_range_callback`. None for the TDAI family,
            which has no lip sync control at all.
        volume_range: The device-documented dB range (and 0.1 dB step,
            the same tenths-of-a-dB wire encoding as the MP trims - see
            `LyngdorfApi.volume`) for the main-zone `!VOL` command. NOT
            uniform across every family sharing the same protocol: the MP
            and P families document -99.9..+24.0 dB (docs/mp-40.md,
            docs/mp-60.md, docs/p-series.md all agree), but the entire
            TDAI family - TDAI-1120, TDAI-2170 and TDAI-3400 - documents a
            lower ceiling of -99.9..+12.0 dB (docs/tdai-1120.md,
            docs/tdai-2170.md, docs/tdai-3400.md), and TDAI-2210 shares
            that bound since it shares TDAI-1120/3400's protocol.

            This is the model's fixed hardware capability and stays that
            way for the connection's whole lifetime - it is set per model
            here (not computed) deliberately so a single model's bound can
            be changed later without restructuring anything. It is
            deliberately NOT narrowed to the device's live `MAXVOL`
            setting (`Receiver.max_volume`, #40): `max_volume` is a
            user-settable speaker-protection ceiling the device already
            enforces in hardware and can change from the front panel
            mid-session, so folding it into `volume_range` would make a
            capability a consumer might cache (e.g. Home Assistant's
            `number`/`media_player` slider bounds, read once) silently
            change meaning later - a stored scene or automation built
            against the old bound would start meaning something different
            with no code change on either side. A consumer that wants the
            live ceiling reads `max_volume` itself and decides what to do
            with it; the two concepts (what the hardware can do, versus
            what the user currently allows) are kept distinct rather than
            blended into one number. See `Receiver.volume_range`.
        zone_b_volume_range: The device-documented dB range for the `!ZVOL`
            command, on the models that have Zone B at all (see
            `has_zone_b`) - None everywhere else, including the whole TDAI
            family, none of which maps Zone B at all. Where present, it is
            documented identical to `volume_range` on the same model
            (docs/mp-60.md's `!ZVOL` matches its `!VOL` exactly, and
            likewise for docs/mp-40.md/docs/p-series.md) - not assumed
            equal, each was checked. Like `volume_range`, this is a fixed
            capability, never narrowed to any live setting - no manual
            documents a Zone B counterpart to `!MAXVOL` (no `!ZMAXVOL`)
            regardless.
        remote_keys: The write-only `RemoteKey` -> wire-command table for
            this model (see `lyngdorf/remote.py`) - empty by default,
            which is exactly right for the whole TDAI family (no
            navigation hardware at all). The MP and P families each set
            this explicitly to the full button set their manual
            documents; this is never inferred from any other capability
            flag, and never from whether some unrelated `Msg` lookup
            happens to succeed - see issue #46, which found that kind of
            inference is exactly how the P series ended up silently
            supporting no remote keys at all despite its manual
            documenting a full set.
    """

    model_name: str
    manufacturer: str
    messages: dict[Msg, str]
    setup_commands: list[str]
    video_inputs: dict[int, str]
    audio_inputs: dict[int, str]
    stream_types: dict[int, str]
    video_outputs: dict[int, str] | None = None
    room_perfect_positions: dict[int, str] | None = None
    fixed_sources: dict[int, str] | None = None
    fixed_voicings: dict[int, str] | None = None
    has_zone_b: bool = False
    has_video: bool = False
    has_surround: bool = False
    has_streaming: bool = False
    trim_bass_range: NumericRange | None = None
    trim_treble_range: NumericRange | None = None
    trim_centre_range: NumericRange | None = None
    trim_height_range: NumericRange | None = None
    trim_lfe_range: NumericRange | None = None
    trim_surround_range: NumericRange | None = None
    trim_bass_treble_scale: float = 10.0
    lipsync_default_range: NumericRange | None = None
    volume_range: NumericRange | None = None
    zone_b_volume_range: NumericRange | None = None
    power_state_on: str = POWER_ON
    mute_state_in_parameter: bool = False
    keepalive_message: Msg | None = Msg.DEVICE
    remote_keys: RemoteKeyTable = field(default_factory=RemoteKeyTable)

    def lookup_command(self, key: Msg) -> str:
        """Lookup protocol command for a given message type.

        Args:
            key: Message type to lookup

        Returns:
            Protocol command string for this model

        Raises:
            KeyError: If message type not supported by this model
        """
        return self.messages[key]

    def available_remote_keys(self) -> frozenset[RemoteKey]:
        """Every remote key this model's protocol documents at all.

        Empty for the whole TDAI family (see `remote_keys` above).
        """
        return self.remote_keys.available_keys()

    def lookup_remote_key(self, key: RemoteKey) -> str:
        """Lookup the wire command for a given remote key.

        Args:
            key: Remote key to lookup

        Returns:
            Wire command string for this model

        Raises:
            KeyError: If this model does not support the given key
        """
        return self.remote_keys.command_for(key)

    # Command-shape defaults below are the MP/P family's: a bare `<cmd>+`/
    # `<cmd>-` suffix steps a value up/down, and query/set share one name
    # except treble (TRIM_TREBLE is the reply key, TRIM_TREBLE_SET the
    # query/set/step one - see docs/mp-60.md, TRIMTREBLE vs TRIMTREB,
    # verified against real hardware). TDAIModelConfig overrides these:
    # TDAI has no `+`/`-` suffix convention at all, using distinct literal
    # tokens (VOLUP/VOLDN) for volume and no step command whatsoever for
    # bass/treble trim.

    def has_bass_trim(self) -> bool:
        """Whether this model has bass trim control at all. TDAI-2170 is
        the current example of a model with none (see has_treble_trim)."""
        return Msg.TRIM_BASS in self.messages

    def has_treble_trim(self) -> bool:
        """Whether this model has treble trim control at all. TDAI-2170
        has neither bass nor treble trim; TDAI-1120/3400 have both but
        can't step either one - see has_bass_trim_step/has_treble_trim_step."""
        return Msg.TRIM_TREBLE in self.messages

    def has_bass_trim_step(self) -> bool:
        """Whether this model can step bass trim up/down, as opposed to
        only setting it to an absolute value."""
        return Msg.TRIM_BASS in self.messages

    def has_treble_trim_step(self) -> bool:
        """Whether this model can step treble trim up/down, as opposed to
        only setting it to an absolute value."""
        return Msg.TRIM_TREBLE_SET in self.messages

    def has_lipsync(self) -> bool:
        """Whether this model has lip sync (audio/video delay) control.
        True for the MP and P families; the TDAI family has no LIP_SYNC
        mapping at all."""
        return Msg.LIP_SYNC in self.messages

    def volume_up_command(self) -> str:
        return f"{self.lookup_command(Msg.VOLUME)}+"

    def volume_down_command(self) -> str:
        return f"{self.lookup_command(Msg.VOLUME)}-"

    def zone_b_volume_up_command(self) -> str:
        return f"{self.lookup_command(Msg.ZONE_B_VOLUME)}+"

    def zone_b_volume_down_command(self) -> str:
        return f"{self.lookup_command(Msg.ZONE_B_VOLUME)}-"

    def trim_bass_up_command(self) -> str | None:
        if not self.has_bass_trim_step():
            return None
        return f"{self.lookup_command(Msg.TRIM_BASS)}+"

    def trim_bass_down_command(self) -> str | None:
        if not self.has_bass_trim_step():
            return None
        return f"{self.lookup_command(Msg.TRIM_BASS)}-"

    def trim_centre_up_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_CENTRE)}+"

    def trim_centre_down_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_CENTRE)}-"

    def trim_height_up_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_HEIGHT)}+"

    def trim_height_down_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_HEIGHT)}-"

    def trim_lfe_up_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_LFE)}+"

    def trim_lfe_down_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_LFE)}-"

    def trim_surround_up_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_SURROUND)}+"

    def trim_surround_down_command(self) -> str:
        return f"{self.lookup_command(Msg.TRIM_SURROUND)}-"

    def trim_treble_set_command(self) -> str:
        return self.lookup_command(Msg.TRIM_TREBLE_SET)

    def trim_treble_up_command(self) -> str | None:
        if not self.has_treble_trim_step():
            return None
        return f"{self.lookup_command(Msg.TRIM_TREBLE_SET)}+"

    def trim_treble_down_command(self) -> str | None:
        if not self.has_treble_trim_step():
            return None
        return f"{self.lookup_command(Msg.TRIM_TREBLE_SET)}-"
