"""P Series multichannel processor configurations.

This module contains configurations for the P family of Steinway Lyngdorf
multichannel processors (P100, P200, P300), which share a protocol closely
related to the MP series but with no discrete channel trim controls
(no TRIMBASS/TRIMTREB/TRIMCENTER/TRIMHEIGHT/TRIMLFE/TRIMSURRS/BAL) and no
built-in streaming source (no STREAMTYPE).

Note: this configuration is derived from the vendor External Control
Manual only and has not been verified against real hardware.

:license: MIT, see LICENSE for more details.
"""

from ..const import Msg
from ..remote import RemoteKey, RemoteKeyTable
from .base import ModelConfig, NumericRange

# Fallback for Receiver.lipsync_range before a real LIPSYNCRANGE? reply
# arrives - see Receiver._lipsync_range_callback. The P series has never
# been verified against real hardware (see module docstring); this
# mirrors the MP-60 measurement (!LIPSYNCRANGE(0,500)) since both
# families document the same LIPSYNC/LIPSYNCRANGE commands.
P_LIPSYNC_DEFAULT_RANGE = NumericRange(min=0.0, max=500.0, step=1.0)

# !VOL/!ZVOL: -999..240 (-99.9..+24.0 dB), 0.1 dB step - docs/p-series.md
# documents the same bound as the MP family for both the main-zone and
# Zone B volume commands (checked individually, not assumed). The P
# series manual also documents a "Head Unit" variant with a completely
# different scale (0..999 = 0..99.9 dB) - this library does not model
# head units, so that variant is deliberately not represented here. See
# issue #42.
P_VOLUME_RANGE = NumericRange(min=-99.9, max=24.0, step=0.1)

# Shared P Series Protocol Commands
P_MESSAGES: dict[Msg, str] = {
    Msg.DEVICE: "DEVICE",
    Msg.VERBOSE: "VERB",
    Msg.PING: "PING",
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
    # !MAXVOL: contrary to issue #40's original premise, MAXVOL is not
    # MP-only - docs/p-series.md documents it too (see the note above
    # Msg.MAX_VOLUME in mp_series.py's MP_MESSAGES for why its bounds
    # aren't validated).
    Msg.MAX_VOLUME: "MAXVOL",
}

# P-series remote-key wire commands (write-only - see lyngdorf/remote.py).
# Checked against docs/p-series.md. `!BACK` is documented directly for
# the whole family, unlike the MP manuals, which omit it entirely - but a
# real MP-60 accepts it too (see MP_REMOTE_KEYS in mp_series.py for the
# measurement), so MP gets BACK as well now. The rest of this base set -
# navigation, ENTER, MENU/INFO/SETUP, EXIT, digits - is likewise common
# to all three P models.
#
# `!MULTIVIEW` is deliberately NOT in this base set. docs/p-series.md:69
# restricts it explicitly - "Multiview button (same as "PiP" on remote,
# P200 only)" - a stated hardware restriction, not an omission the way
# MP's missing `!BACK` was. There is no hardware measurement to overrule
# it with (no P-series device has been available to test, per the module
# docstring) and no third-party mapping either - unlike BACK,
# jsoutter/ha-lyngdorf does not implement MULTIVIEW at all. With no
# contradicting evidence, follow the manual: P100_CONFIG and P300_CONFIG
# get `P_REMOTE_KEYS` (no MULTIVIEW), P200_CONFIG gets `P200_REMOTE_KEYS`
# (P_REMOTE_KEYS plus MULTIVIEW). If a P100 or P300 is ever tested and
# accepts `!MULTIVIEW`, widen `P_REMOTE_KEYS` itself rather than adding a
# third variant.
P_REMOTE_KEYS = RemoteKeyTable(
    commands={
        RemoteKey.UP: "DIRU",
        RemoteKey.DOWN: "DIRD",
        RemoteKey.LEFT: "DIRL",
        RemoteKey.RIGHT: "DIRR",
        RemoteKey.ENTER: "ENTER",
        RemoteKey.MENU: "MENU",
        RemoteKey.INFO: "INFO",
        RemoteKey.SETTINGS: "SETUP",
        RemoteKey.BACK: "BACK",
        RemoteKey.EXIT: "EXIT",
    },
    # `!NUM(X)` is one parameterised command, not ten literal entries.
    digit_format="NUM({})",
)

# P200 only (see the note above P_REMOTE_KEYS) - everything the rest of
# the family has, plus MULTIVIEW.
P200_REMOTE_KEYS = RemoteKeyTable(
    commands={**P_REMOTE_KEYS.commands, RemoteKey.MULTIVIEW: "MULTIVIEW"},
    digit_format=P_REMOTE_KEYS.digit_format,
)

# Shared P Series Setup Command Sequence
P_SETUP_MESSAGES: list[str] = [
    f"{P_MESSAGES[Msg.VERBOSE]}(1)",
    f"{P_MESSAGES[Msg.DEVICE]}?",
    f"{P_MESSAGES[Msg.POWER]}?",
    f"{P_MESSAGES[Msg.ZONE_B_POWER]}?",
    f"{P_MESSAGES[Msg.AUDIO_MODEL]}?",
    f"{P_MESSAGES[Msg.SOURCES]}?",
    f"{P_MESSAGES[Msg.ZONE_B_SOURCES]}?",
    f"{P_MESSAGES[Msg.ROOM_PERFECT_POSITIONS]}?",
    f"{P_MESSAGES[Msg.ROOM_PERFECT_VOICINGS]}?",
    f"{P_MESSAGES[Msg.AUDIO_MODE]}?",
    f"{P_MESSAGES[Msg.SOURCE]}?",
    f"{P_MESSAGES[Msg.ZONE_B_SOURCE]}?",
    f"{P_MESSAGES[Msg.ROOM_PERFECT_POSITION]}?",
    f"{P_MESSAGES[Msg.ROOM_PERFECT_VOICING]}?",
    f"{P_MESSAGES[Msg.VIDEO_TYPE]}?",
    f"{P_MESSAGES[Msg.LIP_SYNC]}?",
    f"{P_MESSAGES[Msg.LIP_SYNC_MIN_MAX]}?",
    f"{P_MESSAGES[Msg.AUDIO_IN]}?",
    f"{P_MESSAGES[Msg.VIDEO_IN]}?",
    f"{P_MESSAGES[Msg.AUDIO_TYPE]}?",
    f"{P_MESSAGES[Msg.VOLUME]}?",
    f"{P_MESSAGES[Msg.ZONE_B_VOLUME]}?",
    f"{P_MESSAGES[Msg.MUTE]}?",
    f"{P_MESSAGES[Msg.ZONE_B_MUTE]}?",
    f"{P_MESSAGES[Msg.MAX_VOLUME]}?",
]

# P100 Hardware Configuration
# Entry-level processor: 4 HDMI inputs, no video output routing
P100_VIDEO_INPUTS = {
    0: "None",
    1: "HDMI 1",
    2: "HDMI 2",
    3: "HDMI 3",
    4: "HDMI 4",
}

P_AUDIO_INPUTS = {
    0: "None",
    1: "HDMI",
    2: "8 Channel Analog",
    3: "Spdif 1 (Optical)",
    4: "Spdif 2 (Optical)",
    5: "Spdif 3 (Optical)",
    6: "Spdif 4 (Optical)",
    7: "Spdif 5 (AES)",
    8: "Spdif 6 (Coax)",
    9: "Spdif 7 (Coax)",
    10: "Spdif 8 (Coax)",
    11: "Internal Player",
    12: "USB",
    13: "Analog 1 (Unbalanced)",
    14: "Analog 2 (Unbalanced)",
    15: "Analog 3 (Unbalanced)",
    16: "Analog 4 (Unbalanced)",
    17: "Analog 5 (Balanced)",
    20: "16-Channel Input (optional for P200/P300)",
    21: "Audio Return Channel",
}

P100_CONFIG = ModelConfig(
    model_name="p100",
    manufacturer="Lyngdorf",
    messages=P_MESSAGES,
    setup_commands=P_SETUP_MESSAGES,
    video_inputs=P100_VIDEO_INPUTS,
    audio_inputs=P_AUDIO_INPUTS,
    stream_types={},
    has_zone_b=True,
    has_video=True,
    lipsync_default_range=P_LIPSYNC_DEFAULT_RANGE,
    volume_range=P_VOLUME_RANGE,
    zone_b_volume_range=P_VOLUME_RANGE,
    remote_keys=P_REMOTE_KEYS,
)

# P200 / P300 Hardware Configuration
# Full processors: 9 HDMI inputs, up to 5 HDMI outputs
P_VIDEO_INPUTS = {
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

P_VIDEO_OUTPUTS = {
    0: "None",
    1: "HDMI Out 1",
    2: "HDMI Out 2",
    3: "HDMI Out 3",
    4: "HDMI Out 4",
    5: "HDBT Out",
    7: "Video Wall",
}

P200_CONFIG = ModelConfig(
    model_name="p200",
    manufacturer="Lyngdorf",
    messages=P_MESSAGES,
    setup_commands=P_SETUP_MESSAGES,
    video_inputs=P_VIDEO_INPUTS,
    audio_inputs=P_AUDIO_INPUTS,
    stream_types={},
    video_outputs=P_VIDEO_OUTPUTS,
    has_zone_b=True,
    has_video=True,
    lipsync_default_range=P_LIPSYNC_DEFAULT_RANGE,
    volume_range=P_VOLUME_RANGE,
    zone_b_volume_range=P_VOLUME_RANGE,
    # P200 only - see the MULTIVIEW note above P_REMOTE_KEYS.
    remote_keys=P200_REMOTE_KEYS,
)

P300_CONFIG = ModelConfig(
    model_name="p300",
    manufacturer="Lyngdorf",
    messages=P_MESSAGES,
    setup_commands=P_SETUP_MESSAGES,
    video_inputs=P_VIDEO_INPUTS,
    audio_inputs=P_AUDIO_INPUTS,
    stream_types={},
    video_outputs=P_VIDEO_OUTPUTS,
    has_zone_b=True,
    has_video=True,
    lipsync_default_range=P_LIPSYNC_DEFAULT_RANGE,
    volume_range=P_VOLUME_RANGE,
    zone_b_volume_range=P_VOLUME_RANGE,
    remote_keys=P_REMOTE_KEYS,
)
