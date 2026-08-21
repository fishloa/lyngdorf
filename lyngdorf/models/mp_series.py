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
from ..remote import RemoteKey, RemoteKeyTable
from .base import ModelConfig, NumericRange

# The MP volume ceiling of +24.0 dB is measured, not just transcribed: on a
# real MP-60, !VOL(240) is accepted and !VOL(250), !VOL(300) and !VOL(400)
# all clamp back to 240. A third-party table elsewhere claims the MP-50
# stops at +20.0 dB, but that source marks its own MP entries untested and
# cites nothing, and docs/mp-50.md gives the same -999..240 as its siblings,
# so no per-model exception is made here.
#
# Trim ranges below are transcribed from docs/mp-40.md, docs/mp-50.md and
# docs/mp-60.md, which all document identical bounds and "10 = 1dB"
# encoding (hence the 0.1 dB step) for every MP model - not assumed, each
# was checked individually. !TRIMBASS/!TRIMTREB: -120..120 (-12..+12 dB).
#
# Confirmed on a real MP-60 (firmware 5.4.2) rather than taken on trust:
# every one of the six trims accepts its documented bound exactly and
# silently clamps beyond it - sending 150 stores 120, sending -150 stores
# -120, with no error either way. That silent clamping is why the setters
# raise rather than clamp: the device already swallows an out-of-range
# value without telling anyone, so a library that did the same would
# leave a caller no way at all to discover the mistake.
#
# Worth checking rather than assuming, because this manual is not reliable
# in general - the same document was wrong about stream-type names, about
# `seek`, and about MAXVOL's range (it gives -550..-200, while a real
# MP-60 reports 0).
MP_BASS_TREBLE_TRIM_RANGE = NumericRange(min=-12.0, max=12.0, step=0.1)
# !TRIMCENTER/!TRIMHEIGHT/!TRIMLFE/!TRIMSURRS: -100..100 (-10..+10 dB).
MP_CHANNEL_TRIM_RANGE = NumericRange(min=-10.0, max=10.0, step=0.1)
# Fallback for Receiver.lipsync_range before a real LIPSYNCRANGE? reply
# arrives - see Receiver._lipsync_range_callback. Matches a real MP-60's
# measured reply on firmware 5.4.2: !LIPSYNCRANGE(0,500).
LIPSYNC_DEFAULT_RANGE = NumericRange(min=0.0, max=500.0, step=1.0)

# !VOL/!ZVOL: -999..240 (-99.9..+24.0 dB), 0.1 dB step (tenths on the
# wire - see LyngdorfApi.volume). Checked individually against
# docs/mp-40.md, docs/mp-50.md and docs/mp-60.md (all three main-zone
# !VOL) and docs/mp-60.md's !ZVOL specifically, not assumed equal - they
# turn out to document identical bounds for both commands across the
# whole family. See issue #42.
#
# One external source disagrees for the MP-50 specifically:
# homeassistant-projects/hass-lyngdorf gives it a +20.0 dB ceiling
# against +24.0 for the MP-60. That claim was checked and rejected: that
# repo marks both its MP entries 'tested': False, cites no manual or
# measurement anywhere in its history, and appears scaffolded from a
# sibling project's template rather than derived from Lyngdorf's own
# docs. Our own docs/mp-50.md (like docs/mp-40.md and docs/mp-60.md)
# gives !VOL as -999 to 240 (-99.9 to +24.0 dB) - the vendor's own MP-50
# documentation contradicts the +20.0 dB claim directly. Do not "fix"
# this constant to match that source without a better one.
#
# Each MP model is still given this constant individually below (not
# hardcoded into ModelConfig's default) precisely so a future model - or
# a better-sourced correction to this one - can diverge from the rest of
# the family without restructuring anything; #36 already found trim
# steps differing within a family and #41 found the encoding differing
# between families, so uniformity here is presently-true data, not an
# assumption baked into the shape of the code.
MP_VOLUME_RANGE = NumericRange(min=-99.9, max=24.0, step=0.1)

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
    # !MAXVOL: a user-settable safety ceiling, not MP-only despite issue
    # #40's original premise - the P series documents it too (see
    # p_series.py's P_MESSAGES). docs/mp-40.md and docs/mp-60.md document
    # -550..-200 (-55.0..-20.0 dB), but a real MP-60 on firmware 5.4.2
    # answered !MAXVOL(0), i.e. 0.0 dB - outside that documented range -
    # and docs/p-series.md documents yet another range for the same
    # command (-550..240, -55.0..+24.0 dB). The vendor-documented bounds
    # are therefore not reliable, so Receiver.max_volume (device.py)
    # reads and surfaces this value without validating it against any
    # range. Do not add validation.
    Msg.MAX_VOLUME: "MAXVOL",
    Msg.LOUDNESS: "LOUDNESS",
    Msg.DTS_DIALOG_AVAILABLE: "DTSDIALOGAVAILABLE",
    Msg.DTS_DIALOG: "DTSDIALOG",
    Msg.DTS_DIALOG_UP: "DTSDIALOGUP",
    Msg.DTS_DIALOG_DOWN: "DTSDIALOGDN",
    Msg.VIDEO_OUTPUT: "HDMIMAINOUT",
    Msg.SOURCE_NEXT: "SRC+",
    Msg.SOURCE_PREV: "SRC-",
    Msg.SOURCE_BUTTON: "SRCBTN",
    Msg.VOICING_NEXT: "RPVOI+",
    Msg.VOICING_PREV: "RPVOI-",
    Msg.FOCUS_POSITION_NEXT: "RPFOC+",
    Msg.FOCUS_POSITION_PREV: "RPFOC-",
    Msg.AUDIO_MODE_NEXT: "AUDMODE+",
    Msg.AUDIO_MODE_PREV: "AUDMODE-",
    Msg.AUDIO_MODE_BUTTON: "AUDIO",
}

# MP-40/50/60 remote-key wire commands (write-only - see lyngdorf/remote.py).
# Checked individually against docs/mp-40.md, docs/mp-50.md and
# docs/mp-60.md, which all document an identical button set - except for
# `!BACK`, which none of the three manuals mention (they document `!EXIT`
# only). The manuals are wrong here: probed against a real MP-60 on
# firmware 5.4.2 at `!VERB(2)` (which echoes every command the device
# recognises with a leading `#`, and stays silent for anything it
# doesn't), `!BACK` came back `#BACK` - accepted - while deliberately
# malformed controls sent in the same session got no echo at all, so the
# discriminator is sound and this is not noise. `!EXIT`, `!MULTIVIEW` and
# every other token below were also confirmed accepted the same way. This
# matches `jsoutter/ha-lyngdorf`, which ships `BACK` for MP models too.
# Measured on an MP-60 only - MP-40/MP-50 are inferred from the shared
# manual lineage and the same third-party mapping, not independently
# measured. `EXIT` is kept alongside `BACK`: both are genuinely accepted,
# distinct buttons, not two names for the same one. Do not remove `BACK`
# to "match the manual" - the manual is the thing that's wrong here.
MP_REMOTE_KEYS = RemoteKeyTable(
    commands={
        RemoteKey.UP: "DIRU",
        RemoteKey.DOWN: "DIRD",
        RemoteKey.LEFT: "DIRL",
        RemoteKey.RIGHT: "DIRR",
        RemoteKey.ENTER: "ENTER",
        RemoteKey.MENU: "MENU",
        RemoteKey.BACK: "BACK",
        RemoteKey.INFO: "INFO",
        RemoteKey.SETTINGS: "SETUP",
        RemoteKey.EXIT: "EXIT",
        RemoteKey.MULTIVIEW: "MULTIVIEW",
    },
    # `!NUM(X)` is one parameterised command, not ten literal entries.
    digit_format="NUM({})",
)

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
    f"{MP_MESSAGES[Msg.LIP_SYNC_MIN_MAX]}?",
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
    f"{MP_MESSAGES[Msg.MAX_VOLUME]}?",
    f"{MP_MESSAGES[Msg.LOUDNESS]}?",
    f"{MP_MESSAGES[Msg.DTS_DIALOG_AVAILABLE]}?",
    f"{MP_MESSAGES[Msg.DTS_DIALOG]}?",
    f"{MP_MESSAGES[Msg.VIDEO_OUTPUT]}?",
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
    6: "Roon Ready",
    7: "TIDAL",
    8: "airable",
    9: "PureAudio",
    10: "Qobuz",
}

MP40_CONFIG = ModelConfig(
    model_name="mp-40",
    manufacturer="Lyngdorf",
    messages=MP_MESSAGES,
    setup_commands=MP_SETUP_MESSAGES,
    video_inputs=MP40_VIDEO_INPUTS,
    audio_inputs=MP40_AUDIO_INPUTS,
    stream_types=MP40_STREAM_TYPES,
    has_zone_b=True,
    has_video=True,
    has_surround=True,
    has_streaming=True,
    trim_bass_range=MP_BASS_TREBLE_TRIM_RANGE,
    trim_treble_range=MP_BASS_TREBLE_TRIM_RANGE,
    trim_centre_range=MP_CHANNEL_TRIM_RANGE,
    trim_height_range=MP_CHANNEL_TRIM_RANGE,
    trim_lfe_range=MP_CHANNEL_TRIM_RANGE,
    trim_surround_range=MP_CHANNEL_TRIM_RANGE,
    lipsync_default_range=LIPSYNC_DEFAULT_RANGE,
    volume_range=MP_VOLUME_RANGE,
    zone_b_volume_range=MP_VOLUME_RANGE,
    remote_keys=MP_REMOTE_KEYS,
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
    43: "PureAudio",
    44: "Qobuz",
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
    6: "Roon Ready",
    7: "TIDAL",
    8: "airable",
    9: "PureAudio",
    10: "Qobuz",
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
    has_zone_b=True,
    has_video=True,
    has_surround=True,
    has_streaming=True,
    trim_bass_range=MP_BASS_TREBLE_TRIM_RANGE,
    trim_treble_range=MP_BASS_TREBLE_TRIM_RANGE,
    trim_centre_range=MP_CHANNEL_TRIM_RANGE,
    trim_height_range=MP_CHANNEL_TRIM_RANGE,
    trim_lfe_range=MP_CHANNEL_TRIM_RANGE,
    trim_surround_range=MP_CHANNEL_TRIM_RANGE,
    lipsync_default_range=LIPSYNC_DEFAULT_RANGE,
    volume_range=MP_VOLUME_RANGE,
    zone_b_volume_range=MP_VOLUME_RANGE,
    remote_keys=MP_REMOTE_KEYS,
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
    43: "PureAudio",
    44: "Qobuz",
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
    6: "Roon Ready",
    7: "TIDAL",
    8: "airable",
    9: "PureAudio",
    10: "Qobuz",
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
    has_zone_b=True,
    has_video=True,
    has_surround=True,
    has_streaming=True,
    trim_bass_range=MP_BASS_TREBLE_TRIM_RANGE,
    trim_treble_range=MP_BASS_TREBLE_TRIM_RANGE,
    trim_centre_range=MP_CHANNEL_TRIM_RANGE,
    trim_height_range=MP_CHANNEL_TRIM_RANGE,
    trim_lfe_range=MP_CHANNEL_TRIM_RANGE,
    trim_surround_range=MP_CHANNEL_TRIM_RANGE,
    lipsync_default_range=LIPSYNC_DEFAULT_RANGE,
    volume_range=MP_VOLUME_RANGE,
    zone_b_volume_range=MP_VOLUME_RANGE,
    remote_keys=MP_REMOTE_KEYS,
)
