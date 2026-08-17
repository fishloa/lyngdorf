"""Base model classes and protocols for Lyngdorf devices.

This module defines the core data structures and protocols that all
Lyngdorf device models must implement.

:license: MIT, see LICENSE for more details.
"""

from dataclasses import dataclass
from typing import Protocol

from ..const import POWER_ON, Msg


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
    power_state_on: str = POWER_ON
    mute_state_in_parameter: bool = False
    keepalive_message: Msg | None = Msg.DEVICE

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
