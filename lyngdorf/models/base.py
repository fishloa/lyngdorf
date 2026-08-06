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
    power_state_on: str = POWER_ON
    mute_state_in_parameter: bool = False

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
