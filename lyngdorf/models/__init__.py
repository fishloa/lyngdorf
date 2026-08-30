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
from ..remote import RemoteKey
from .base import ModelCapability, ModelConfig, NumericRange
from .mp_series import MP40_CONFIG, MP50_CONFIG, MP60_CONFIG
from .p_series import P100_CONFIG, P200_CONFIG, P300_CONFIG
from .tdai_series import (
    TDAI1120_CONFIG,
    TDAI2170_CONFIG,
    TDAI2210_CONFIG,
    TDAI3400_CONFIG,
)


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
        TDAI_2210: TDAI-2210 integrated amplifier
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
    TDAI_2210 = TDAI2210_CONFIG
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
    def commands(self) -> dict[Msg, str]:
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

    def lookup_command(self, key: Msg) -> str:
        """Lookup protocol command for a given message type.

        Args:
            key: Message type (Msg enum value)

        Returns:
            Protocol command string for this model

        Raises:
            KeyError: If message type not supported by this model
        """
        return self._config.messages[key]

    def trim_bass_range(self) -> NumericRange | None:
        """The documented dB range (and step) for bass trim, or None on a
        model with no bass trim at all (TDAI-2170)."""
        return self._config.trim_bass_range

    def trim_treble_range(self) -> NumericRange | None:
        """The documented dB range (and step) for treble trim, or None on
        a model with no treble trim at all (TDAI-2170)."""
        return self._config.trim_treble_range

    def trim_bass_treble_scale(self) -> float:
        """How many wire units make up 1 dB for bass/treble trim on this
        model - 10.0 for the MP/P family, 1.0 for the TDAI family. See
        ModelConfig.trim_bass_treble_scale."""
        return self._config.trim_bass_treble_scale

    def trim_centre_range(self) -> NumericRange | None:
        """The documented dB range (and step) for centre channel trim, or
        None on a model with no discrete channel trims (see
        has_surround_feature)."""
        return self._config.trim_centre_range

    def trim_height_range(self) -> NumericRange | None:
        """The documented dB range (and step) for height channel trim, or
        None on a model with no discrete channel trims (see
        has_surround_feature)."""
        return self._config.trim_height_range

    def trim_lfe_range(self) -> NumericRange | None:
        """The documented dB range (and step) for LFE channel trim, or
        None on a model with no discrete channel trims (see
        has_surround_feature)."""
        return self._config.trim_lfe_range

    def trim_surround_range(self) -> NumericRange | None:
        """The documented dB range (and step) for surround channel trim,
        or None on a model with no discrete channel trims (see
        has_surround_feature)."""
        return self._config.trim_surround_range

    def lipsync_default_range(self) -> NumericRange | None:
        """The range to assume for lipsync before the device answers a
        LIPSYNCRANGE? query, or None on a model with no lip sync control
        at all (the TDAI family - see has_lipsync_feature)."""
        return self._config.lipsync_default_range

    def volume_range(self) -> NumericRange | None:
        """The documented dB range (and step) for the main-zone volume -
        see ModelConfig.volume_range for why this is not uniform across
        every family sharing the same protocol (the TDAI family's ceiling
        is lower than the MP/P families')."""
        return self._config.volume_range

    def zone_b_volume_range(self) -> NumericRange | None:
        """The documented dB range (and step) for Zone B volume, or None
        on a model with no Zone B at all (see ModelConfig.has_zone_b)."""
        return self._config.zone_b_volume_range

    def power_state_on_value(self) -> str:
        """Return the power-state parameter value that means "powered on".

        Returns:
            "1" for the MP and P families (`!POWER(1)`), "ON" for the TDAI
            family (`!PWR(ON)`)
        """
        return self._config.power_state_on

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

    def available_remote_keys(self) -> frozenset[RemoteKey]:
        """Every remote key this model's protocol documents at all.

        Returns:
            frozenset[RemoteKey], empty for the whole TDAI family
        """
        return self._config.available_remote_keys()

    def lookup_remote_key(self, key: RemoteKey) -> str:
        """Lookup the wire command for a given remote key.

        Args:
            key: Remote key to lookup

        Returns:
            Wire command string for this model

        Raises:
            KeyError: If this model does not support the given key
        """
        return self._config.lookup_remote_key(key)

    @property
    def keepalive_message(self) -> Msg | None:
        """Message type this model uses for connection keep-alive/probing.

        Returns:
            The Msg to query to keep the connection alive, or None if this
            model has no keep-alive query
        """
        return self._config.keepalive_message

    def supports_message(self, key: Msg) -> bool:
        """Check whether this model's protocol defines a given message.

        Args:
            key: Message type (Msg enum value)

        Returns:
            True if this model's command dictionary has an entry for key
        """
        return key in self._config.messages

    @property
    def capabilities(self) -> dict[Msg, bool]:
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
    "NumericRange",
    "RemoteKey",
    "MP40_CONFIG",
    "MP50_CONFIG",
    "MP60_CONFIG",
    "TDAI1120_CONFIG",
    "TDAI2170_CONFIG",
    "TDAI2210_CONFIG",
    "TDAI3400_CONFIG",
    "P100_CONFIG",
    "P200_CONFIG",
    "P300_CONFIG",
]
