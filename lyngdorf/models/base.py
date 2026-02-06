"""Base model classes and protocols for Lyngdorf devices.

This module defines the core data structures and protocols that all
Lyngdorf device models must implement.

:license: MIT, see LICENSE for more details.
"""

from dataclasses import dataclass
from typing import Protocol

from ..const import Msg


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
        room_perfect_positions: Optional Room Perfect position mapping
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
