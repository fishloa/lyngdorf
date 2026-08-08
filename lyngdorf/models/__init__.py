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
from typing import cast

from ..const import Msg
from .base import ModelCapability, ModelConfig
from .mp_series import MP40_CONFIG, MP50_CONFIG, MP60_CONFIG
from .p_series import P100_CONFIG, P200_CONFIG, P300_CONFIG
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
        P_100: P100 multichannel processor
        P_200: P200 multichannel processor
        P_300: P300 multichannel processor
    """

    MP_40 = MP40_CONFIG
    MP_50 = MP50_CONFIG
    MP_60 = MP60_CONFIG
    TDAI_1120 = TDAI1120_CONFIG
    TDAI_2170 = TDAI2170_CONFIG
    TDAI_3400 = TDAI3400_CONFIG
    P_100 = P100_CONFIG
    P_200 = P200_CONFIG
    P_300 = P300_CONFIG

    @property
    def _config(self) -> ModelConfig:
        """Typed accessor for `self.value`.

        Enum members here hold `ModelConfig` (and subclass) instances,
        but `Enum.value` itself is typed `Any` - this cast is what lets
        every delegate method below type-check cleanly instead of
        silently returning `Any`.
        """
        return cast(ModelConfig, self.value)

    @property
    def config(self) -> ModelConfig:
        """Get the model configuration.

        Returns:
            ModelConfig instance for this model
        """
        return self._config

    @property
    def commands(self) -> dict:
        """Get the protocol command mapping for this model."""
        return self._config.messages

    @property
    def model_name(self) -> str:
        """Get model name."""
        return self._config.model_name

    @property
    def manufacturer(self) -> str:
        """Get manufacturer name."""
        return self._config.manufacturer

    @property
    def setup_commands(self) -> list[str]:
        """Get setup command sequence."""
        return self._config.setup_commands

    def lookup_command(self, key) -> str:
        """Lookup protocol command for a given message type.

        Args:
            key: Message type (Msg enum value)

        Returns:
            Protocol command string for this model

        Raises:
            KeyError: If message type not supported by this model
        """
        return self._config.messages[key]

    def has_zone_b_feature(self) -> bool:
        """Check if this model supports Zone B (Zone 2) functionality.

        Returns:
            True if the model has Zone B support, False otherwise
        """
        return self._config.has_zone_b

    def has_video_feature(self) -> bool:
        """Check if this model supports video inputs and outputs.

        Returns:
            True if the model has video capability, False otherwise
        """
        return self._config.has_video

    def has_surround_feature(self) -> bool:
        """Check if this model has discrete per-channel multichannel trims
        (center/height/LFE/surround speaker trims).

        Returns:
            True if the model has channel trim capability, False otherwise
        """
        return self._config.has_surround

    def power_state_on_value(self) -> str:
        """Return the power-state parameter value that means "powered on".

        Returns:
            "1" for the MP and P families (`!POWER(1)`), "ON" for the TDAI
            family (`!PWR(ON)`)
        """
        return self._config.power_state_on

    def has_mute_state_in_parameter(self) -> bool:
        """Check whether mute state arrives as a parameter on MUTE.

        Returns:
            True if the model reports mute as `!MUTE(ON)` / `!MUTE(OFF)`
            (TDAI family), False if it uses distinct `!MUTEON` /
            `!MUTEOFF` messages (MP and P families)
        """
        return self._config.mute_state_in_parameter

    def has_bass_trim_feature(self) -> bool:
        """Check whether this model has bass trim control at all.

        Returns:
            True if the model can set bass trim (absolute value, with or
            without stepping - see has_bass_trim_step_feature), False if
            it has no bass trim control whatsoever (TDAI-2170)
        """
        return self._config.has_bass_trim()

    def has_treble_trim_feature(self) -> bool:
        """Check whether this model has treble trim control at all.

        Returns:
            True if the model can set treble trim (absolute value, with
            or without stepping - see has_treble_trim_step_feature),
            False if it has no treble trim control whatsoever (TDAI-2170)
        """
        return self._config.has_treble_trim()

    def has_bass_trim_step_feature(self) -> bool:
        """Check whether this model can step bass trim up/down.

        Returns:
            True if the model supports incremental bass trim adjustment,
            False if it only supports setting an absolute value (the TDAI
            family)
        """
        return self._config.has_bass_trim_step()

    def has_treble_trim_step_feature(self) -> bool:
        """Check whether this model can step treble trim up/down.

        Returns:
            True if the model supports incremental treble trim
            adjustment, False if it only supports setting an absolute
            value (the TDAI family)
        """
        return self._config.has_treble_trim_step()

    def volume_up_command(self) -> str:
        return self._config.volume_up_command()

    def volume_down_command(self) -> str:
        return self._config.volume_down_command()

    def zone_b_volume_up_command(self) -> str:
        return self._config.zone_b_volume_up_command()

    def zone_b_volume_down_command(self) -> str:
        return self._config.zone_b_volume_down_command()

    def trim_bass_up_command(self) -> str | None:
        return self._config.trim_bass_up_command()

    def trim_bass_down_command(self) -> str | None:
        return self._config.trim_bass_down_command()

    def trim_centre_up_command(self) -> str:
        return self._config.trim_centre_up_command()

    def trim_centre_down_command(self) -> str:
        return self._config.trim_centre_down_command()

    def trim_height_up_command(self) -> str:
        return self._config.trim_height_up_command()

    def trim_height_down_command(self) -> str:
        return self._config.trim_height_down_command()

    def trim_lfe_up_command(self) -> str:
        return self._config.trim_lfe_up_command()

    def trim_lfe_down_command(self) -> str:
        return self._config.trim_lfe_down_command()

    def trim_surround_up_command(self) -> str:
        return self._config.trim_surround_up_command()

    def trim_surround_down_command(self) -> str:
        return self._config.trim_surround_down_command()

    def trim_treble_set_command(self) -> str:
        return self._config.trim_treble_set_command()

    def trim_treble_up_command(self) -> str | None:
        return self._config.trim_treble_up_command()

    def trim_treble_down_command(self) -> str | None:
        return self._config.trim_treble_down_command()

    @property
    def keepalive_message(self) -> Msg | None:
        """Message type this model uses for connection keep-alive/probing.

        Returns:
            The Msg to query to keep the connection alive, or None if this
            model has no keep-alive query
        """
        return self._config.keepalive_message

    def supports_message(self, key) -> bool:
        """Check whether this model's protocol defines a given message.

        Args:
            key: Message type (Msg enum value)

        Returns:
            True if this model's command dictionary has an entry for key
        """
        return key in self._config.messages

    @property
    def capabilities(self) -> dict:
        """Mapping of every known message type to whether this model's
        protocol supports it.

        Useful for tests and diagnostics to assert against without
        hardcoding per-model command strings.

        Returns:
            dict[Msg, bool] covering every Msg enum member
        """
        return {msg: msg in self._config.messages for msg in Msg}


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
    "P100_CONFIG",
    "P200_CONFIG",
    "P300_CONFIG",
]
