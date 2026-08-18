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

None of the TDAI models document a PING/PONG command, so Msg.PING/PONG
are simply absent from all three dicts below. Connection keep-alive
(api.py's LyngdorfApi._monitor) queries ModelConfig.keepalive_message
instead, which defaults to DEVICE - the one query every model, including
TDAI-2170, actually supports.

TDAIModelConfig also overrides the MP/P family's `<cmd>+`/`<cmd>-` step
convention (see models/base.py): TDAI has no such shorthand at all,
using distinct literal tokens (VOLUP/VOLDN) for volume and no step
command whatsoever for bass/treble trim - only an absolute set.

Note: the TDAI-2170 and TDAI-3400 corrections below are derived from the
vendor PDF spec only and have not been verified against real hardware
(unlike the MP series fixes, which were checked against a real MP-60).

:license: MIT, see LICENSE for more details.
"""

from ..const import STATE_ON, Msg
from .base import ModelConfig, NumericRange

# docs/tdai-1120.md and docs/tdai-3400.md both document !BASS(n)/!TREBLE(n)
# as "n = -12 to 12 (dB)" - whole dB values, with no "10 = 1dB"-style
# sub-decibel encoding the way the MP series' TRIMBASS/TRIMTREB commands
# have (see mp_series.py's MP_BASS_TREBLE_TRIM_RANGE) - hence the 1.0 dB
# step here even though the min/max bound happens to match the MP series
# exactly. TDAI-2170 has neither BASS nor TREBLE at all (see
# TDAI2170_MESSAGES) so gets no range - has_bass_trim()/has_treble_trim()
# already reflect that via Msg.TRIM_BASS/Msg.TRIM_TREBLE absence.
TDAI_BASS_TREBLE_TRIM_RANGE = NumericRange(min=-12.0, max=12.0, step=1.0)

# Same "whole dB, no sub-decibel encoding" fact as the range above, but
# expressed as the wire scale factor that ModelConfig.trim_bass_treble_scale
# needs: 1 wire unit = 1 dB, unlike the MP/P family's 10 wire units = 1 dB
# default. See issue #41 - derived from the vendor manuals, not yet
# confirmed against real TDAI hardware.
TDAI_BASS_TREBLE_SCALE = 1.0

# !VOL: -999..120 (-99.9..+12.0 dB), 0.1 dB step - docs/tdai-1120.md,
# docs/tdai-2170.md and docs/tdai-3400.md all document this same bound,
# lower than the MP/P families' -99.9..+24.0 dB (see mp_series.py's
# MP_VOLUME_RANGE) - checked individually, not assumed uniform across
# families that otherwise share a protocol. TDAI-2210 shares this bound
# too, since it shares TDAI-1120/3400's protocol. Independently
# corroborated outside our own manuals too: avcontrol/pyavcontrol's
# TDAI-3400 definition and thejens/lyngdorf-mcp both agree on
# -999..120. No TDAI model maps Zone B at all, so there is no
# zone_b_volume_range constant here - see ModelConfig.zone_b_volume_range.
# See issue #42.
TDAI_VOLUME_RANGE = NumericRange(min=-99.9, max=12.0, step=0.1)


class TDAIModelConfig(ModelConfig):
    """Command-shape overrides shared by TDAI-1120, TDAI-2170 and
    TDAI-3400 - see module docstring."""

    def volume_up_command(self) -> str:
        return self.lookup_command(Msg.VOLUME_UP)

    def volume_down_command(self) -> str:
        return self.lookup_command(Msg.VOLUME_DOWN)

    def has_bass_trim_step(self) -> bool:
        return False

    def has_treble_trim_step(self) -> bool:
        return False

    def trim_treble_set_command(self) -> str:
        # TDAI has one TREBLE command for both query and set - no
        # TRIMTREB/TRIMTREBLE-style split.
        return self.lookup_command(Msg.TRIM_TREBLE)


# TDAI-1120 / TDAI-3400 Shared Protocol Commands
TDAI_MESSAGES: dict[Msg, str] = {
    Msg.DEVICE: "DEVICE",
    Msg.VERBOSE: "VERB",
    Msg.POWER: "PWR",
    Msg.POWER_ON: "ON",
    Msg.POWER_OFF: "OFF",
    Msg.VOLUME: "VOL",
    # No VOL+/VOL- shorthand (unlike MP/P) - distinct literal tokens instead.
    Msg.VOLUME_UP: "VOLUP",
    Msg.VOLUME_DOWN: "VOLDN",
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
    # Same shape as SRCNAME above: !RP? replies with a bare index, and
    # both the RPLIST? burst and the current-position query carry the
    # name under RPNAME instead - !RPNAME(n,"Name").
    Msg.ROOM_PERFECT_POSITION_NAME: "RPNAME",
    Msg.ROOM_PERFECT_VOICINGS_COUNT: "VOICOUNT",
    Msg.ROOM_PERFECT_VOICING: "VOI",
    Msg.ROOM_PERFECT_VOICING_LIST: "VOILIST",
    # And again for voicings: !VOINAME(n,"Name").
    Msg.ROOM_PERFECT_VOICING_NAME: "VOINAME",
    Msg.TRIM_BASS: "BASS",
    Msg.TRIM_TREBLE: "TREBLE",
    Msg.BALANCE: "BAL",
    Msg.SOURCE_NEXT: "SRCUP",
    Msg.SOURCE_PREV: "SRCDN",
    Msg.VOICING_NEXT: "VOIUP",
    Msg.VOICING_PREV: "VOIDN",
    Msg.FOCUS_POSITION_NEXT: "RPUP",
    Msg.FOCUS_POSITION_PREV: "RPDN",
}

# TDAI-1120 / TDAI-3400 Shared Setup Sequence
TDAI_SETUP_MESSAGES: list[str] = [
    f"{TDAI_MESSAGES[Msg.VERBOSE]}(1)",
    f"{TDAI_MESSAGES[Msg.DEVICE]}?",
    f"{TDAI_MESSAGES[Msg.POWER]}?",
    f"{TDAI_MESSAGES[Msg.SOURCE_LIST]}?",
    f"{TDAI_MESSAGES[Msg.ROOM_PERFECT_POSITION_LIST]}?",
    f"{TDAI_MESSAGES[Msg.ROOM_PERFECT_VOICING_LIST]}?",
    # SRCNAME?, not SRC? - the current-source query needs the name, and
    # !SRC? doesn't carry one (see Msg.SOURCE_NAME above).
    f"{TDAI_MESSAGES[Msg.SOURCE_NAME]}?",
    # RPNAME?/VOINAME? rather than RP?/VOI?, for the same reason as
    # SRCNAME? above - the bare queries carry no name.
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
    3: "Airplay",
    4: "UPnP",
    5: "USB File",
    6: "Roon Ready",
    7: "Bluetooth",
    8: "GoogleCast",
    9: "TIDAL",
    10: "airable",
    11: "Qobuz",
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

TDAI1120_CONFIG = TDAIModelConfig(
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
    has_streaming=True,
    trim_bass_range=TDAI_BASS_TREBLE_TRIM_RANGE,
    trim_treble_range=TDAI_BASS_TREBLE_TRIM_RANGE,
    trim_bass_treble_scale=TDAI_BASS_TREBLE_SCALE,
    volume_range=TDAI_VOLUME_RANGE,
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
    Msg.VOLUME_UP: "VOLUP",
    Msg.VOLUME_DOWN: "VOLDN",
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
TDAI2170_STREAM_TYPES: dict[int, str] = {}

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

TDAI2170_CONFIG = TDAIModelConfig(
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
    # TDAI-2170 has neither BASS nor TREBLE (see TDAI2170_MESSAGES), so
    # this scale is never actually read - but ModelConfig's dataclass
    # default (10.0, the MP/P family's "10 = 1dB" encoding) is the wrong
    # value for the TDAI family regardless, and leaving it unset would
    # mean this config silently inherits it. Set it explicitly to the
    # TDAI family's real "1 = 1dB" scale so there's no wrong value
    # sitting latent, in case a future firmware revision adds BASS/
    # TREBLE support here.
    trim_bass_treble_scale=TDAI_BASS_TREBLE_SCALE,
    volume_range=TDAI_VOLUME_RANGE,
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
    4: "UPnP",
    5: "USB File",
    6: "Roon Ready",
    8: "TIDAL",
    9: "airable",
    10: "Qobuz",
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

TDAI2210_STREAM_TYPES = TDAI1120_STREAM_TYPES
TDAI2210_ROOM_PERFECT_POSITIONS = TDAI1120_ROOM_PERFECT_POSITIONS

TDAI2210_CONFIG = TDAIModelConfig(
    model_name="tdai-2210",
    manufacturer="Lyngdorf",
    messages=TDAI_MESSAGES,
    setup_commands=TDAI_SETUP_MESSAGES,
    video_inputs={},
    audio_inputs={},
    stream_types=TDAI2210_STREAM_TYPES,
    room_perfect_positions=TDAI2210_ROOM_PERFECT_POSITIONS,
    power_state_on=STATE_ON,
    mute_state_in_parameter=True,
    has_streaming=True,
    trim_bass_range=TDAI_BASS_TREBLE_TRIM_RANGE,
    trim_treble_range=TDAI_BASS_TREBLE_TRIM_RANGE,
    trim_bass_treble_scale=TDAI_BASS_TREBLE_SCALE,
    volume_range=TDAI_VOLUME_RANGE,
)

TDAI3400_CONFIG = TDAIModelConfig(
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
    has_streaming=True,
    trim_bass_range=TDAI_BASS_TREBLE_TRIM_RANGE,
    trim_treble_range=TDAI_BASS_TREBLE_TRIM_RANGE,
    trim_bass_treble_scale=TDAI_BASS_TREBLE_SCALE,
    volume_range=TDAI_VOLUME_RANGE,
)
