"""TDAI Series integrated amplifier configurations.

This module contains configurations for the TDAI family of Lyngdorf
integrated amplifiers (TDAI-1120, TDAI-2170, TDAI-3400).

Protocol Families (verified against the vendor External Control Manuals in
docs/):
- TDAI-1120 and TDAI-3400 share the same protocol (unprefixed commands,
  feedback-level based push notifications via VERB(1)). TDAI-3400 was
  previously (incorrectly) modeled with a fabricated "I"-prefixed command
  set that does not exist in its spec - see issue #16 follow-up.
- TDAI-2170 uses an older, materially different and more limited protocol:
  no VERBOSE/PING/PONG/SRCCOUNT/SRCLIST/STREAMTYPE/RP-or-VOI list-count/BASS/
  TREBLE/BAL commands, and uses SUBSCRIBE/SUBSCRIBEVOL instead of a
  feedback-level setting to enable push notifications.

None of the TDAI models document a PING/PONG command - the Msg.PING key
used for connection keep-alive (see api.py) is simply absent from all
three dicts below; the keep-alive is skipped defensively for these models.

Note: the TDAI-2170 and TDAI-3400 corrections below are derived from the
vendor PDF spec only and have not been verified against real hardware
(unlike the MP series fixes, which were checked against a real MP-60).

:license: MIT, see LICENSE for more details.
"""

from ..const import STATE_ON, Msg
from .base import ModelConfig

# TDAI-1120 / TDAI-3400 Shared Protocol Commands
TDAI_MESSAGES: dict[Msg, str] = {
    Msg.DEVICE: "DEVICE",
    Msg.VERBOSE: "VERB",
    Msg.POWER: "PWR",
    Msg.POWER_ON: "ON",
    Msg.POWER_OFF: "OFF",
    Msg.VOLUME: "VOL",
    Msg.MUTE: "MUTE",
    Msg.MUTE_ON: "MUTEON",
    Msg.MUTE_OFF: "MUTEOFF",
    Msg.SOURCES_COUNT: "SRCCOUNT",
    Msg.SOURCE: "SRC",
    Msg.SOURCE_LIST: "SRCLIST",
    # !SRC? replies with a bare index (!SRC(n)), no name. The name-bearing
    # replies - both the SRCLIST? list-population burst
    # (!SRCNAME(a,"Name") repeated) and the current-source query
    # (!SRCNAME(n,"Name")) - are keyed under SRCNAME instead. See
    # docs/tdai-1120.md.
    Msg.SOURCE_NAME: "SRCNAME",
    Msg.STREAM_TYPE: "STREAMTYPE",
    Msg.ROOM_PERFECT_POSITIONS_COUNT: "RPCOUNT",
    Msg.ROOM_PERFECT_POSITION: "RP",
    Msg.ROOM_PERFECT_POSITION_LIST: "RPLIST",
    # Same story as SOURCE_NAME above: !RP? replies with a bare index, no
    # name. The list-population burst and the current-position query are
    # both keyed under RPNAME instead.
    Msg.ROOM_PERFECT_POSITION_NAME: "RPNAME",
    Msg.ROOM_PERFECT_VOICINGS_COUNT: "VOICOUNT",
    Msg.ROOM_PERFECT_VOICING: "VOI",
    Msg.ROOM_PERFECT_VOICING_LIST: "VOILIST",
    # Same story again: !VOI? replies with a bare index, no name.
    Msg.ROOM_PERFECT_VOICING_NAME: "VOINAME",
    Msg.TRIM_BASS: "BASS",
    Msg.TRIM_TREBLE: "TREBLE",
    Msg.BALANCE: "BAL",
}

# TDAI-1120 / TDAI-3400 Shared Setup Sequence
TDAI_SETUP_MESSAGES: list[str] = [
    f"{TDAI_MESSAGES[Msg.VERBOSE]}(1)",
    f"{TDAI_MESSAGES[Msg.DEVICE]}?",
    f"{TDAI_MESSAGES[Msg.POWER]}?",
    f"{TDAI_MESSAGES[Msg.SOURCE_LIST]}?",
    f"{TDAI_MESSAGES[Msg.ROOM_PERFECT_POSITION_LIST]}?",
    f"{TDAI_MESSAGES[Msg.ROOM_PERFECT_VOICING_LIST]}?",
    # SRCNAME?/RPNAME?/VOINAME?, not SRC?/RP?/VOI? - the current-value
    # queries need the name, and the bare forms don't carry one (see
    # Msg.SOURCE_NAME/ROOM_PERFECT_POSITION_NAME/ROOM_PERFECT_VOICING_NAME
    # above).
    f"{TDAI_MESSAGES[Msg.SOURCE_NAME]}?",
    f"{TDAI_MESSAGES[Msg.ROOM_PERFECT_POSITION_NAME]}?",
    f"{TDAI_MESSAGES[Msg.ROOM_PERFECT_VOICING_NAME]}?",
    f"{TDAI_MESSAGES[Msg.STREAM_TYPE]}?",
    f"{TDAI_MESSAGES[Msg.VOLUME]}?",
    f"{TDAI_MESSAGES[Msg.MUTE]}?",
    f"{TDAI_MESSAGES[Msg.TRIM_BASS]}?",
    f"{TDAI_MESSAGES[Msg.TRIM_TREBLE]}?",
    f"{TDAI_MESSAGES[Msg.BALANCE]}?",
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
    # Power and mute states are words, not digits: !PWR(ON), !MUTE(OFF)
    power_state_on=STATE_ON,
    mute_state_in_parameter=True,
)

# TDAI-2170 Protocol Commands
# Older, more limited protocol - no VERBOSE/PING/PONG/SRCCOUNT/SRCLIST/
# STREAMTYPE/RP-or-VOI list-count/BASS/TREBLE/BAL. Push notifications are
# enabled via SUBSCRIBE/SUBSCRIBEVOL rather than a feedback-level setting.
TDAI2170_MESSAGES: dict[Msg, str] = {
    Msg.DEVICE: "DEVICE",
    Msg.POWER: "PWR",
    Msg.POWER_ON: "ON",
    Msg.POWER_OFF: "OFF",
    Msg.VOLUME: "VOL",
    Msg.MUTE: "MUTE",
    Msg.MUTE_ON: "MUTEON",
    Msg.MUTE_OFF: "MUTEOFF",
    Msg.SOURCE: "SRC",
    Msg.ROOM_PERFECT_POSITION: "RP",
    Msg.ROOM_PERFECT_VOICING: "VOI",
    # This device has no count+enumeration burst for sources, RP
    # positions, or voicings (no SRCLIST/RPLIST/VOILIST) - instead each
    # has a fixed, hardware-defined set of entries (see the TDAI2170_*
    # tables below) and a bitmask reply saying which of them are
    # currently enabled/present. !SRC(n)/!RP(n)/!VOI(n) all reply with a
    # bare index too, no name.
    Msg.SOURCES_ENABLED: "SRCENABLED",
    Msg.ROOM_PERFECT_POSITIONS_PRESENT: "RPSTATUS",
    Msg.ROOM_PERFECT_VOICINGS_ENABLED: "VOIENABLED",
}

# TDAI-2170 Setup Sequence
# SUBSCRIBE/SUBSCRIBEVOL activate push notifications for status/volume
# changes (this device has no VERB feedback-level command). The bitmask
# queries must come before the current-value queries they resolve against.
TDAI2170_SETUP_MESSAGES: list[str] = [
    "SUBSCRIBE",
    "SUBSCRIBEVOL",
    f"{TDAI2170_MESSAGES[Msg.DEVICE]}?",
    f"{TDAI2170_MESSAGES[Msg.POWER]}?",
    f"{TDAI2170_MESSAGES[Msg.SOURCES_ENABLED]}?",
    f"{TDAI2170_MESSAGES[Msg.ROOM_PERFECT_POSITIONS_PRESENT]}?",
    f"{TDAI2170_MESSAGES[Msg.ROOM_PERFECT_VOICINGS_ENABLED]}?",
    f"{TDAI2170_MESSAGES[Msg.SOURCE]}?",
    f"{TDAI2170_MESSAGES[Msg.ROOM_PERFECT_POSITION]}?",
    f"{TDAI2170_MESSAGES[Msg.ROOM_PERFECT_VOICING]}?",
    f"{TDAI2170_MESSAGES[Msg.VOLUME]}?",
    f"{TDAI2170_MESSAGES[Msg.MUTE]}?",
]

# TDAI-2170 Hardware Configuration
# Older integrated amplifier model
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

# Fixed hardware inputs (see docs/tdai-2170.md, Input Source Numbering).
# Which of these are actually enabled comes from the SRCENABLED bitmask.
TDAI2170_SOURCES = {
    0: "Coax Digital 1",
    1: "Coax Digital 2",
    2: "Optical Digital 3",
    3: "Optical Digital 4",
    4: "Optical Digital 5",
    5: "Optical Digital 6",
    6: "USB Input",
    7: "HDMI Input 1",
    8: "HDMI Input 2",
    9: "HDMI Input 3",
    10: "HDMI Input 4",
    11: "HDMI Audio Return Channel (ARC)",
    12: "Analog 1 (RCA on main board)",
    13: "Analog 2 (RCA on main board)",
    14: "Analog 3 (RCA on extension board)",
    15: "Analog 4 (RCA on extension board)",
    16: "Analog 5 (RCA on extension board)",
    17: "Analog 6 (XLR on extension board)",
}

# Fixed voicings (see docs/tdai-2170.md, Voicing Numbering). Which of these
# are enabled comes from the VOIENABLED bitmask (Voicing 0/Neutral is
# always enabled).
TDAI2170_VOICINGS = {
    0: "Neutral",
    1: "Music 1",
    2: "Music 2",
    3: "Relaxed",
    4: "Open",
    5: "Open Air",
    6: "Soft",
    7: "Action 1",
    8: "Action 2",
    9: "Movie",
    10: "Action Movie",
    11: "News",
    12: "Bass 1",
    13: "Bass 2",
}

TDAI2170_CONFIG = ModelConfig(
    model_name="tdai-2170",
    manufacturer="Lyngdorf",
    messages=TDAI2170_MESSAGES,
    setup_commands=TDAI2170_SETUP_MESSAGES,
    video_inputs={},
    audio_inputs={},
    stream_types=TDAI2170_STREAM_TYPES,
    room_perfect_positions=TDAI2170_ROOM_PERFECT_POSITIONS,
    fixed_sources=TDAI2170_SOURCES,
    fixed_voicings=TDAI2170_VOICINGS,
    # Power and mute states are words, not digits: !PWR(ON), !MUTE(OFF)
    power_state_on=STATE_ON,
    mute_state_in_parameter=True,
)

# TDAI-3400 Hardware Configuration
# Top-of-line networked integrated amplifier. Same protocol family as
# TDAI-1120 (TDAI_MESSAGES/TDAI_SETUP_MESSAGES above) - it does not use a
# separate "I"-prefixed command set.
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
    messages=TDAI_MESSAGES,
    setup_commands=TDAI_SETUP_MESSAGES,
    video_inputs={},
    audio_inputs={},
    stream_types=TDAI3400_STREAM_TYPES,
    room_perfect_positions=TDAI3400_ROOM_PERFECT_POSITIONS,
    # Power and mute states are words, not digits: !PWR(ON), !MUTE(OFF)
    power_state_on=STATE_ON,
    mute_state_in_parameter=True,
)
