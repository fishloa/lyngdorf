"""Model configurations for all supported Lyngdorf devices.

This module provides the LyngdorfModel enum and model configurations
for all supported Lyngdorf A/V processors and integrated amplifiers.

Usage:
    from lyngdorf.models import LyngdorfModel, supported_models

    # Get model configuration
    model = LyngdorfModel.MP_60
    config = model.config

    # Access model properties
    print(config.model_name)  # "mp-60"
    print(config.manufacturer)  # "Lyngdorf"

    # Lookup command
    cmd = model.lookup_command(Msg.POWER_ON)

:license: MIT, see LICENSE for more details.
"""

from enum import Enum

from .base import ModelCapability, ModelConfig
from .mp_series import MP40_CONFIG, MP50_CONFIG, MP60_CONFIG
from .tdai_series import TDAI1120_CONFIG, TDAI2170_CONFIG, TDAI3400_CONFIG


class LyngdorfModel(Enum):
    """Enum of supported Lyngdorf receiver models.

    Each enum value contains a ModelConfig instance with all
    model-specific configuration and capabilities.

    Attributes:
        MP_40: MP-40 multichannel processor
        MP_50: MP-50 multichannel processor
        MP_60: MP-60 multichannel processor
        TDAI_1120: TDAI-1120 integrated amplifier
        TDAI_2170: TDAI-2170 integrated amplifier
        TDAI_3400: TDAI-3400 integrated amplifier
    """

    MP_40 = MP40_CONFIG
    MP_50 = MP50_CONFIG
    MP_60 = MP60_CONFIG
    TDAI_1120 = TDAI1120_CONFIG
    TDAI_2170 = TDAI2170_CONFIG
    TDAI_3400 = TDAI3400_CONFIG

    @property
    def config(self) -> ModelConfig:
        """Get the model configuration.

        Returns:
            ModelConfig instance for this model
        """
        return self.value

    @property
    def commands(self) -> dict:
        """Get the protocol command mapping for this model."""
        return self.value.messages

    @property
    def model_name(self) -> str:
        """Get model name."""
        return self.value.model_name

    @property
    def manufacturer(self) -> str:
        """Get manufacturer name."""
        return self.value.manufacturer

    @property
    def setup_commands(self) -> list[str]:
        """Get setup command sequence."""
        return self.value.setup_commands

    def lookup_command(self, key) -> str:
        """Lookup protocol command for a given message type.

        Args:
            key: Message type (Msg enum value)

        Returns:
            Protocol command string for this model

        Raises:
            KeyError: If message type not supported by this model
        """
        return self.value.messages[key]


def supported_models() -> list[LyngdorfModel]:
    """Return a list of all supported Lyngdorf receiver models.

    Returns:
        List of all LyngdorfModel enum values
    """
    return list(LyngdorfModel)


# Public API exports
__all__ = [
    "LyngdorfModel",
    "supported_models",
    "ModelConfig",
    "ModelCapability",
    "MP40_CONFIG",
    "MP50_CONFIG",
    "MP60_CONFIG",
    "TDAI1120_CONFIG",
    "TDAI2170_CONFIG",
    "TDAI3400_CONFIG",
]
