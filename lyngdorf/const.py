#!/usr/bin/env python3
"""
Lyngdorf Audio Control Library - Constants Module.

Shared constants and protocol definitions for all supported Lyngdorf
receiver models.

Protocol Families:
- MP Family: MP-40, MP-50, MP-60 (shared protocol)
- TDAI Family: TDAI-1120, TDAI-2170 (shared protocol), TDAI-3400 (I-prefixed)

:license: MIT, see LICENSE for more details.
"""

from enum import Enum

# Connection Configuration
DEFAULT_LYNGDORF_PORT = 84
RECONNECT_BACKOFF = 0.5  # half a second to wait for the first reconnect
RECONNECT_SCALE = (
    2.5  # each reconnect attempt waits this times longer than the previous one
)
RECONNECT_MAX_WAIT = 30.0  # Reconnect tasks will wait this many seconds at a maximum between each attempt
MONITOR_INTERVAL = 90  # 90 seconds between PING commands

# Power States
POWER_ON = "1"
POWER_OFF = "0"

# Message Types
# Shared across all Lyngdorf models (protocol commands may differ per model)
Msg = Enum(
    "Msg",
    [
        "DEVICE",
        "VERBOSE",
        "PING",
        "PONG",
        "POWER",
        "POWER_ON",
        "POWER_OFF",
        "VOLUME",
        "MUTE",
        "MUTE_ON",
        "MUTE_OFF",
        "SOURCES_COUNT",
        "SOURCE",
        "SOURCES",  # Source list query
        "ZONE_B_POWER",
        "ZONE_B_POWER_ON",
        "ZONE_B_POWER_OFF",
        "ZONE_B_VOLUME",
        "ZONE_B_MUTE",  # Zone B mute query
        "ZONE_B_MUTE_ON",
        "ZONE_B_MUTE_OFF",
        "ZONE_B_SOURCES_COUNT",
        "ZONE_B_SOURCE",
        "ZONE_B_SOURCES",  # Zone B source list query
        "AUDIO_IN",
        "ZONE_B_AUDIO_IN",
        "VIDEO_IN",
        "STREAM_TYPE",
        "ZONE_B_STREAM_TYPE",
        "VIDEO_TYPE",
        "AUDIO_TYPE",
        "AUDIO_MODES_COUNT",
        "AUDIO_MODE",
        "AUDIO_MODEL",  # Audio model query
        "ROOM_PERFECT_POSITIONS_COUNT",
        "ROOM_PERFECT_POSITION",
        "ROOM_PERFECT_POSITIONS",  # Room Perfect position list query
        "ROOM_PERFECT_VOICINGS_COUNT",
        "ROOM_PERFECT_VOICING",
        "ROOM_PERFECT_VOICINGS",  # Room Perfect voicing list query
        "LIP_SYNC",
        "LIP_SYNC_MIN_MAX",
        "TRIM_BASS",
        "TRIM_CENTRE",
        "TRIM_HEIGHT",
        "TRIM_LFE",
        "TRIM_SURROUND",
        "TRIM_TREBLE",
        "TRIM_TREBLE_SET",
    ],
)

# Import model configurations from models module
from .models import (  # noqa: E402, F401
    MP40_CONFIG,
    MP50_CONFIG,
    MP60_CONFIG,
    TDAI1120_CONFIG,
    TDAI2170_CONFIG,
    TDAI3400_CONFIG,
    LyngdorfModel,
    supported_models,
)

# Re-export model-specific constants for backward compatibility
# These are now defined in models/mp_series.py and models/tdai_series.py
from .models.mp_series import (  # noqa: E402, F401
    MP40_AUDIO_INPUTS,
    MP40_STREAM_TYPES,
    MP40_VIDEO_INPUTS,
    MP50_AUDIO_INPUTS,
    MP50_STREAM_TYPES,
    MP50_VIDEO_INPUTS,
    MP50_VIDEO_OUTPUTS,
    MP60_AUDIO_INPUTS,
    MP60_ROOM_PERFECT_POSITIONS,
    MP60_STREAM_TYPES,
    MP60_VIDEO_INPUTS,
    MP60_VIDEO_OUTPUTS,
    MP_MESSAGES,
    MP_SETUP_MESSAGES,
)
from .models.tdai_series import (  # noqa: E402, F401
    TDAI1120_ROOM_PERFECT_POSITIONS,
    TDAI1120_STREAM_TYPES,
    TDAI2170_ROOM_PERFECT_POSITIONS,
    TDAI2170_STREAM_TYPES,
    TDAI3400_MESSAGES,
    TDAI3400_ROOM_PERFECT_POSITIONS,
    TDAI3400_SETUP_MESSAGES,
    TDAI3400_STREAM_TYPES,
    TDAI_MESSAGES,
    TDAI_SETUP_MESSAGES,
)

# Backward compatibility: alias protocol names to match old constant names
MP60_MESSAGES: dict[Msg, str] = MP_MESSAGES
MP60_SETUP_MESSAGES: list[str] = MP_SETUP_MESSAGES
MP40_MESSAGES: dict[Msg, str] = MP_MESSAGES
MP40_SETUP_MESSAGES: list[str] = MP_SETUP_MESSAGES
MP50_MESSAGES: dict[Msg, str] = MP_MESSAGES
MP50_SETUP_MESSAGES: list[str] = MP_SETUP_MESSAGES

TDAI1120_MESSAGES: dict[Msg, str] = TDAI_MESSAGES
TDAI1120_SETUP_MESSAGES: list[str] = TDAI_SETUP_MESSAGES
TDAI2170_MESSAGES: dict[Msg, str] = TDAI_MESSAGES
TDAI2170_SETUP_MESSAGES: list[str] = TDAI_SETUP_MESSAGES

# Public API - explicitly export all backward-compatible constants
__all__ = [
    # Core constants
    "DEFAULT_LYNGDORF_PORT",
    "RECONNECT_BACKOFF",
    "RECONNECT_SCALE",
    "RECONNECT_MAX_WAIT",
    "MONITOR_INTERVAL",
    "POWER_ON",
    "POWER_OFF",
    "Msg",
    # Model configurations
    "LyngdorfModel",
    "supported_models",
    "MP40_CONFIG",
    "MP50_CONFIG",
    "MP60_CONFIG",
    "TDAI1120_CONFIG",
    "TDAI2170_CONFIG",
    "TDAI3400_CONFIG",
    # MP series constants
    "MP40_VIDEO_INPUTS",
    "MP40_AUDIO_INPUTS",
    "MP40_STREAM_TYPES",
    "MP40_MESSAGES",
    "MP40_SETUP_MESSAGES",
    "MP50_VIDEO_INPUTS",
    "MP50_VIDEO_OUTPUTS",
    "MP50_AUDIO_INPUTS",
    "MP50_STREAM_TYPES",
    "MP50_MESSAGES",
    "MP50_SETUP_MESSAGES",
    "MP60_VIDEO_INPUTS",
    "MP60_VIDEO_OUTPUTS",
    "MP60_AUDIO_INPUTS",
    "MP60_ROOM_PERFECT_POSITIONS",
    "MP60_STREAM_TYPES",
    "MP60_MESSAGES",
    "MP60_SETUP_MESSAGES",
    # TDAI series constants
    "TDAI1120_STREAM_TYPES",
    "TDAI1120_ROOM_PERFECT_POSITIONS",
    "TDAI1120_MESSAGES",
    "TDAI1120_SETUP_MESSAGES",
    "TDAI2170_STREAM_TYPES",
    "TDAI2170_ROOM_PERFECT_POSITIONS",
    "TDAI2170_MESSAGES",
    "TDAI2170_SETUP_MESSAGES",
    "TDAI3400_STREAM_TYPES",
    "TDAI3400_ROOM_PERFECT_POSITIONS",
    "TDAI3400_MESSAGES",
    "TDAI3400_SETUP_MESSAGES",
]
