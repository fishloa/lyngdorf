"""MP Series multichannel processor configurations.

This module contains configurations for the MP family of Lyngdorf
multichannel processors (MP-40, MP-50, MP-60), which share a common
TCP/IP control protocol.

Protocol Characteristics:
- Shared command structure across all MP models
- Main zone + Zone B (Zone 2) control
- Video input/output routing
- Room Perfect and voicing support

:license: MIT, see LICENSE for more details.
"""

from ..const import Msg
from .base import ModelConfig

# Shared MP Protocol Commands
# All MP-40, MP-50, and MP-60 models use this command mapping
MP_MESSAGES: dict[Msg, str] = {
    Msg.DEVICE: "DEVICE",
    Msg.VERBOSE: "VERB",
    Msg.PING: "PING",
    Msg.PONG: "PONG",
    Msg.POWER: "POWER",
    Msg.POWER_ON: "POWERONMAIN",
    Msg.POWER_OFF: "POWEROFFMAIN",
    Msg.VOLUME: "VOL",
    Msg.MUTE: "MUTE",
    Msg.MUTE_ON: "MUTEON",
    Msg.MUTE_OFF: "MUTEOFF",
    Msg.SOURCES_COUNT: "SRCCOUNT",
    Msg.SOURCE: "SRC",
    Msg.SOURCES: "SRCS",
    Msg.AUDIO_IN: "AUDIN",
    Msg.STREAM_TYPE: "STREAMTYPE",
    Msg.VIDEO_IN: "VIDIN",
    Msg.AUDIO_MODES_COUNT: "AUDMODECOUNT",
    Msg.AUDIO_MODE: "AUDMODE",
    Msg.AUDIO_MODEL: "AUDMODEL",
    Msg.AUDIO_TYPE: "AUDTYPE",
    Msg.VIDEO_TYPE: "VIDTYPE",
    Msg.ROOM_PERFECT_POSITIONS_COUNT: "RPFOCCOUNT",
    Msg.ROOM_PERFECT_POSITION: "RPFOC",
    Msg.ROOM_PERFECT_POSITIONS: "RPFOCS",
    Msg.ROOM_PERFECT_VOICINGS_COUNT: "RPVOICOUNT",
    Msg.ROOM_PERFECT_VOICING: "RPVOI",
    Msg.ROOM_PERFECT_VOICINGS: "RPVOIS",
    Msg.LIP_SYNC: "LIPSYNC",
    Msg.LIP_SYNC_MIN_MAX: "LIPSYNCRANGE",
    Msg.ZONE_B_POWER: "POWERZONE2",
    Msg.ZONE_B_POWER_ON: "POWERONZONE2",
    Msg.ZONE_B_POWER_OFF: "POWEROFFZONE2",
    Msg.ZONE_B_VOLUME: "ZVOL",
    Msg.ZONE_B_MUTE: "ZMUTE",
    Msg.ZONE_B_MUTE_ON: "ZMUTEON",
    Msg.ZONE_B_MUTE_OFF: "ZMUTEOFF",
    Msg.ZONE_B_SOURCES_COUNT: "ZSRCCOUNT",
    Msg.ZONE_B_SOURCE: "ZSRC",
    Msg.ZONE_B_SOURCES: "ZSRCS",
    Msg.ZONE_B_AUDIO_IN: "ZAUDIN",
    Msg.ZONE_B_STREAM_TYPE: "ZSTREAMTYPE",
    Msg.TRIM_BASS: "TRIMBASS",
    Msg.TRIM_CENTRE: "TRIMCENTER",
    Msg.TRIM_HEIGHT: "TRIMHEIGHT",
    Msg.TRIM_LFE: "TRIMLFE",
    Msg.TRIM_SURROUND: "TRIMSURRS",
    Msg.TRIM_TREBLE: "TRIMTREBLE",
    Msg.TRIM_TREBLE_SET: "TRIMTREB",
}

# Shared MP Setup Command Sequence
MP_SETUP_MESSAGES: list[str] = [
    f"{MP_MESSAGES[Msg.VERBOSE]}(1)",
    f"{MP_MESSAGES[Msg.DEVICE]}?",
    f"{MP_MESSAGES[Msg.POWER]}?",
    f"{MP_MESSAGES[Msg.ZONE_B_POWER]}?",
    f"{MP_MESSAGES[Msg.AUDIO_MODEL]}?",
    f"{MP_MESSAGES[Msg.SOURCES]}?",
    f"{MP_MESSAGES[Msg.ZONE_B_SOURCES]}?",
    f"{MP_MESSAGES[Msg.ROOM_PERFECT_POSITIONS]}?",
    f"{MP_MESSAGES[Msg.ROOM_PERFECT_VOICINGS]}?",
    f"{MP_MESSAGES[Msg.AUDIO_MODE]}?",
    f"{MP_MESSAGES[Msg.SOURCE]}?",
    f"{MP_MESSAGES[Msg.ZONE_B_SOURCE]}?",
    f"{MP_MESSAGES[Msg.ROOM_PERFECT_POSITION]}?",
    f"{MP_MESSAGES[Msg.ROOM_PERFECT_VOICING]}?",
    f"{MP_MESSAGES[Msg.VIDEO_TYPE]}?",
    f"{MP_MESSAGES[Msg.STREAM_TYPE]}?",
    f"{MP_MESSAGES[Msg.LIP_SYNC]}?",
    f"{MP_MESSAGES[Msg.ZONE_B_STREAM_TYPE]}?",
    f"{MP_MESSAGES[Msg.AUDIO_IN]}?",
    f"{MP_MESSAGES[Msg.VIDEO_IN]}?",
    f"{MP_MESSAGES[Msg.AUDIO_TYPE]}?",
    f"{MP_MESSAGES[Msg.VOLUME]}?",
    f"{MP_MESSAGES[Msg.ZONE_B_VOLUME]}?",
    f"{MP_MESSAGES[Msg.MUTE]}?",
    f"{MP_MESSAGES[Msg.ZONE_B_MUTE]}?",
    f"{MP_MESSAGES[Msg.TRIM_BASS]}?",
    f"{MP_MESSAGES[Msg.TRIM_CENTRE]}?",
    f"{MP_MESSAGES[Msg.TRIM_HEIGHT]}?",
    f"{MP_MESSAGES[Msg.TRIM_LFE]}?",
    f"{MP_MESSAGES[Msg.TRIM_SURROUND]}?",
    f"{MP_MESSAGES[Msg.TRIM_TREBLE_SET]}?",
]

# MP-40 Hardware Configuration
# Entry-level processor: 3 HDMI inputs, 12-channel decoding
MP40_VIDEO_INPUTS = {
    0: "None",
    1: "HDMI 1",
    2: "HDMI 2",
    3: "HDMI 3",
    9: "Internal",
}

MP40_AUDIO_INPUTS = {
    0: "None",
    1: "HDMI",
    3: "Spdif 1 (Opt.)",
    4: "Spdif 2 (Opt.)",
    5: "Spdif 3 (Opt.)",
    6: "Spdif 4 (Opt.)",
    7: "Spdif 5 (AES)",
    8: "Spdif 6 (Coax)",
    9: "Spdif 7 (Coax)",
    10: "Spdif 8 (Coax)",
    11: "Internal Player",
    12: "USB",
    24: "Audio Return Channel",
}

MP40_STREAM_TYPES = {
    0: "None",
    1: "vTuner",
    2: "Spotify",
    3: "AirPlay",
    4: "UPnP",
    5: "Storage",
    6: "Roon ready",
    7: "Unknown",
}

MP40_CONFIG = ModelConfig(
    model_name="mp-40",
    manufacturer="Lyngdorf",
    messages=MP_MESSAGES,
    setup_commands=MP_SETUP_MESSAGES,
    video_inputs=MP40_VIDEO_INPUTS,
    audio_inputs=MP40_AUDIO_INPUTS,
    stream_types=MP40_STREAM_TYPES,
)

# MP-50 Hardware Configuration
# Mid-level processor: 8 HDMI inputs, 11.1 + 4 aux outputs
MP50_VIDEO_INPUTS = {
    0: "None",
    1: "HDMI 1",
    2: "HDMI 2",
    3: "HDMI 3",
    4: "HDMI 4",
    5: "HDMI 5",
    6: "HDMI 6",
    7: "HDMI 7",
    8: "HDMI 8",
    9: "Internal",
}

MP50_AUDIO_INPUTS = {
    0: "None",
    1: "HDMI",
    3: "Spdif 1 (Opt.)",
    4: "Spdif 2 (Opt.)",
    5: "Spdif 3 (Opt.)",
    6: "Spdif 4 (Opt.)",
    7: "Spdif 5 (AES)",
    8: "Spdif 6 (Coax)",
    9: "Spdif 7 (Coax)",
    10: "Spdif 8 (Coax)",
    11: "Internal Player",
    12: "USB",
    20: "16-Channel (optional AES module)",
    21: "16-Channel 2.0 (optional AES module)",
    22: "16-Channel 5.1 (optional AES module)",
    23: "16-Channel 7.1 (optional AES module)",
    24: "Audio Return Channel",
    35: "vTuner",
    36: "TIDAL",
    37: "Spotify",
    38: "Airplay",
    39: "Roon",
    40: "DLNA",
    41: "Storage",
    42: "airable",
}

MP50_VIDEO_OUTPUTS = {
    0: "None",
    1: "HDMI Out 1",
    2: "HDMI Out 2",
    3: "HDBT Out",
}

MP50_STREAM_TYPES = {
    0: "None",
    1: "vTuner",
    2: "Spotify",
    3: "AirPlay",
    4: "UPnP",
    5: "Storage",
    6: "Roon ready",
    7: "Unknown",
}

MP50_CONFIG = ModelConfig(
    model_name="mp-50",
    manufacturer="Lyngdorf",
    messages=MP_MESSAGES,
    setup_commands=MP_SETUP_MESSAGES,
    video_inputs=MP50_VIDEO_INPUTS,
    audio_inputs=MP50_AUDIO_INPUTS,
    stream_types=MP50_STREAM_TYPES,
    video_outputs=MP50_VIDEO_OUTPUTS,
)

# MP-60 Hardware Configuration
# Flagship processor: 8 HDMI inputs, 16-channel decoding, Room Perfect
MP60_VIDEO_INPUTS = {
    0: "None",
    1: "HDMI 1",
    2: "HDMI 2",
    3: "HDMI 3",
    4: "HDMI 4",
    5: "HDMI 5",
    6: "HDMI 6",
    7: "HDMI 7",
    8: "HDMI 8",
    9: "Internal",
}

MP60_VIDEO_OUTPUTS = {0: "None", 1: "HDMI Out 1", 2: "HDMI Out 2", 3: "HDBT Out"}

MP60_AUDIO_INPUTS = {
    0: "None",
    1: "HDMI",
    3: "Spdif 1 (Opt.)",
    4: "Spdif 2 (Opt.)",
    5: "Spdif 3 (Opt.)",
    6: "Spdif 4 (Opt.)",
    7: "Spdif 5 (AES)",
    8: "Spdif 6 (Coax)",
    9: "Spdif 7 (Coax)",
    10: "Spdif 8 (Coax)",
    11: "Internal Player",
    12: "USB",
    20: "16-Channel (optional AES module)",
    21: "16-Channel 2.0 (optional AES module)",
    22: "16-Channel 5.1 (optional AES module)",
    23: "16-Channel 7.1 (optional AES module)",
    24: "Audio Return Channel",
    35: "vTuner",
    36: "TIDAL",
    37: "Spotify",
    38: "Airplay",
    39: "Roon",
    40: "DLNA",
    41: "Storage",
    42: "airable",
}

MP60_ROOM_PERFECT_POSITIONS = {
    0: "Bypass",
    1: "Focus 1",
    2: "Focus 2",
    3: "Focus 3",
    4: "Focus 4",
    9: "Global",
}

MP60_STREAM_TYPES = {
    0: "None",
    1: "vTuner",
    2: "Spotify",
    3: "AirPlay",
    4: "UPnP",
    5: "Storage",
    6: "Roon ready",
    7: "Unknown",
}

MP60_CONFIG = ModelConfig(
    model_name="mp-60",
    manufacturer="Lyngdorf",
    messages=MP_MESSAGES,
    setup_commands=MP_SETUP_MESSAGES,
    video_inputs=MP60_VIDEO_INPUTS,
    audio_inputs=MP60_AUDIO_INPUTS,
    stream_types=MP60_STREAM_TYPES,
    video_outputs=MP60_VIDEO_OUTPUTS,
    room_perfect_positions=MP60_ROOM_PERFECT_POSITIONS,
)
