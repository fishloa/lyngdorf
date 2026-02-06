"""TDAI Series integrated amplifier configurations.

This module contains configurations for the TDAI family of Lyngdorf
integrated amplifiers (TDAI-1120, TDAI-2170, TDAI-3400), which use
different control protocols.

Protocol Families:
- TDAI-1120/2170: Standard TDAI protocol
- TDAI-3400: I-prefixed protocol variant

:license: MIT, see LICENSE for more details.
"""

from ..const import Msg
from .base import ModelConfig

# TDAI-1120/2170 Shared Protocol Commands
# Standard TDAI protocol (different from MP series)
TDAI_MESSAGES: dict[Msg, str] = {
    Msg.DEVICE: "DEVICE",
    Msg.VERBOSE: "VERB",
    Msg.PING: "PING",
    Msg.PONG: "PONG",
    Msg.POWER: "PWR",
    Msg.POWER_ON: "ON",
    Msg.POWER_OFF: "OFF",
    Msg.VOLUME: "VOL",
    Msg.MUTE: "MUTE",
    Msg.MUTE_ON: "MUTEON",
    Msg.MUTE_OFF: "MUTEOFF",
    Msg.SOURCES_COUNT: "SRCCOUNT",
    Msg.SOURCE: "SRC",
    Msg.STREAM_TYPE: "STREAMTYPE",
    Msg.ROOM_PERFECT_POSITIONS_COUNT: "RPCOUNT",
    Msg.ROOM_PERFECT_POSITION: "RP",
    Msg.ROOM_PERFECT_VOICINGS_COUNT: "VOICOUNT",
    Msg.ROOM_PERFECT_VOICING: "VOI",
    Msg.TRIM_BASS: "BASS",
    Msg.TRIM_TREBLE: "TREBLE",
}

# TDAI-1120/2170 Shared Setup Sequence
TDAI_SETUP_MESSAGES: list[str] = [
    "VERB(1)",
    "DEVICE?",
    "PWR?",
    "SRCLIST?",
    "RPLIST?",
    "VOILIST?",
    "SRC?",
    "RP?",
    "VOI?",
    "STREAMTYPE?",
    "VOL?",
    "MUTE?",
    "BASS?",
    "TREBLE?",
    "BAL?",
]

# TDAI-1120 Hardware Configuration
# Entry-level integrated amplifier with streaming
TDAI1120_STREAM_TYPES = {
    0: "None",
    1: "vTuner",
    2: "Spotify",
    3: "AirPlay",
    4: "uPnP",
    5: "USB File",
    6: "Roon Ready",
    7: "Bluetooth",
    8: "GoogleCast",
    9: "Unknown",
}

TDAI1120_ROOM_PERFECT_POSITIONS = {
    0: "Bypass",
    1: "Focus 1",
    2: "Focus 2",
    3: "Focus 3",
    4: "Focus 4",
    5: "Focus 5",
    6: "Focus 6",
    7: "Focus 7",
    8: "Focus 8",
    9: "Global",
}

TDAI1120_CONFIG = ModelConfig(
    model_name="tdai-1120",
    manufacturer="Lyngdorf",
    messages=TDAI_MESSAGES,
    setup_commands=TDAI_SETUP_MESSAGES,
    video_inputs={},  # No video inputs on integrated amplifiers
    audio_inputs={},  # TDAI uses source list instead of fixed inputs
    stream_types=TDAI1120_STREAM_TYPES,
    room_perfect_positions=TDAI1120_ROOM_PERFECT_POSITIONS,
)

# TDAI-2170 Hardware Configuration
# Older integrated amplifier model (shares protocol with 1120)
TDAI2170_STREAM_TYPES = {
    0: "None",
    1: "vTuner",
    2: "Spotify",
    3: "AirPlay",
    4: "uPnP",
    5: "USB File",
    6: "Roon Ready",
    7: "Unknown",
}

TDAI2170_ROOM_PERFECT_POSITIONS = {
    0: "Bypass",
    1: "Focus 1",
    2: "Focus 2",
    3: "Focus 3",
    4: "Focus 4",
    5: "Focus 5",
    6: "Focus 6",
    7: "Focus 7",
    8: "Focus 8",
    9: "Global",
}

TDAI2170_CONFIG = ModelConfig(
    model_name="tdai-2170",
    manufacturer="Lyngdorf",
    messages=TDAI_MESSAGES,  # Same protocol as TDAI-1120
    setup_commands=TDAI_SETUP_MESSAGES,
    video_inputs={},
    audio_inputs={},
    stream_types=TDAI2170_STREAM_TYPES,
    room_perfect_positions=TDAI2170_ROOM_PERFECT_POSITIONS,
)

# TDAI-3400 Protocol Commands
# I-prefixed protocol variant (different from standard TDAI)
TDAI3400_MESSAGES: dict[Msg, str] = {
    Msg.DEVICE: "IDEVICE",
    Msg.VERBOSE: "VERB",
    Msg.PING: "IPING",
    Msg.PONG: "IPONG",
    Msg.POWER: "IPWR",
    Msg.POWER_ON: "ION",
    Msg.POWER_OFF: "IOFF",
    Msg.VOLUME: "IVOL",
    Msg.MUTE: "IMUTE",
    Msg.MUTE_ON: "IMUTEON",
    Msg.MUTE_OFF: "IMUTEOFF",
    Msg.SOURCES_COUNT: "ISRCCOUNT",
    Msg.SOURCE: "ISRC",
    Msg.STREAM_TYPE: "ISTREAMTYPE",
    Msg.ROOM_PERFECT_POSITIONS_COUNT: "IRPCOUNT",
    Msg.ROOM_PERFECT_POSITION: "IRP",
    Msg.ROOM_PERFECT_VOICINGS_COUNT: "IVOICOUNT",
    Msg.ROOM_PERFECT_VOICING: "IVOI",
    Msg.TRIM_BASS: "IBASS",
    Msg.TRIM_TREBLE: "ITREBLE",
}

TDAI3400_SETUP_MESSAGES: list[str] = [
    "VERB(1)",
    "IDEVICE?",
    "IPWR?",
    "SRCLIST?",
    "RPLIST?",
    "VOILIST?",
    "ISRC?",
    "IRP?",
    "IVOI?",
    "ISTREAMTYPE?",
    "IVOL?",
    "IMUTE?",
    "IBASS?",
    "ITREBLE?",
    "BAL?",
]

# TDAI-3400 Hardware Configuration
# Top-of-line networked integrated amplifier
TDAI3400_STREAM_TYPES = {
    0: "None",
    1: "vTuner",
    2: "Spotify",
    3: "AirPlay",
    4: "uPnP",
    5: "USB File",
    6: "Roon Ready",
    7: "Bluetooth",
    8: "TIDAL",
    9: "Unknown",
}

TDAI3400_ROOM_PERFECT_POSITIONS = {
    0: "Bypass",
    1: "Focus 1",
    2: "Focus 2",
    3: "Focus 3",
    4: "Focus 4",
    5: "Focus 5",
    6: "Focus 6",
    7: "Focus 7",
    8: "Focus 8",
    9: "Global",
}

TDAI3400_CONFIG = ModelConfig(
    model_name="tdai-3400",
    manufacturer="Lyngdorf",
    messages=TDAI3400_MESSAGES,  # I-prefixed protocol
    setup_commands=TDAI3400_SETUP_MESSAGES,
    video_inputs={},
    audio_inputs={},
    stream_types=TDAI3400_STREAM_TYPES,
    room_perfect_positions=TDAI3400_ROOM_PERFECT_POSITIONS,
)
