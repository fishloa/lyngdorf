"""P Series multichannel processor configurations.

This module contains configurations for the P family of Steinway Lyngdorf
multichannel processors (P100, P200, P300), which share a protocol closely
related to the MP series but with no discrete channel trim controls
(no TRIMBASS/TRIMTREB/TRIMCENTER/TRIMHEIGHT/TRIMLFE/TRIMSURRS/BAL).

Streaming is NOT uniform across this family. The manual implies none of
them have it; a real P200 does, and answers both !STREAMTYPE and the
StreamUnlimited HTTP API the MP models use (issue #60). P100 and P300
are unmeasured and keep the manual's position - see P200_STREAM_TYPES.

Verification status: derived from the vendor External Control Manual,
then measured against a real P200 (firmware p20.5.4.1) - see issue #57
and the "Hardware measurements" section of docs/p-series.md, which is
the authoritative record and overrides the manual where they differ.
One real divergence was found, in Zone B. P100 and P300 remain
manual-derived and unmeasured; the P200's results are deliberately not
extended to them.

A handful of P200 queries remain unmodelled - !MVIEW*, !INTERFACE,
!SWUPD, !MQASTATUS, !STANDBYLEVEL, !DTSDIALOGAVAILABLE, !ZVIDIN. Listed
in docs/p-series.md, tracked in #60. Several are legal but SILENT on
this hardware (!MVIEWACTIVE, !MVIEWSRC, !ZVIDIN, !MQASTATUS and
!CDINPUT answered nothing at all), so anything polling them must
tolerate never getting a reply - from outside, indistinguishable from
an unknown verb.

:license: MIT, see LICENSE for more details.
"""

from ..const import Msg
from ..remote import RemoteKey, RemoteKeyTable
from .base import ModelConfig, NumericRange
from .mp_series import MP60_STREAM_TYPES

# Fallback for `receiver.lipsync.range` before a real LIPSYNCRANGE? reply
# arrives - see Receiver._lipsync_range_callback. Borrowed from the MP-60
# and since confirmed on a P200: !LIPSYNCRANGE(0,500), identical.
P_LIPSYNC_DEFAULT_RANGE = NumericRange(min=0.0, max=500.0, step=1.0)

# !VOL/!ZVOL: -999..240 (-99.9..+24.0 dB), 0.1 dB step. Documented for
# the family and MEASURED end to end on a P200 - both bounds, the clamp
# behaviour and the step. See "Hardware measurements" in docs/p-series.md
# for the probe results, and issue #42 for why the manual's "Head Unit"
# variant (0..999) is deliberately not modelled.
#
# This is the hardware's capability. The user's live ceiling is !MAXVOL,
# a separate runtime quantity that clamps sets - see
# VolumeControl.maximum_volume. Keeping them apart is the whole of #54;
# do not fold one into the other.
P_VOLUME_RANGE = NumericRange(min=-99.9, max=24.0, step=0.1)

# P200 Zone B only - the one place P hardware disagrees with the manual.
# Measured: !ZVOL(-999) reads back as !ZVOL(-990), so the floor is -99.0,
# 0.9 dB narrower than documented. The ceiling matches the main zone. The
# main zone reaches -999 on the same unit in the same session, so this is
# a real per-zone difference, not a transcription slip. Probe results in
# docs/p-series.md.
#
# Zone B's own ceiling has NO query in this protocol, which is why
# zone_b.volume is a plain SteppableControl: there is nothing that could
# populate a maximum_volume. Pinned by
# test_zone_b_volume_never_reports_a_maximum.
#
# P200 only. P100 and P300 are unmeasured and #36 (trim steps differing
# inside one family) is the precedent for not assuming they match; widen
# to the family if either is ever probed, rather than adding a third
# constant.
P200_ZONE_B_VOLUME_RANGE = NumericRange(min=-99.0, max=24.0, step=0.1)

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
# it with - the P200 capture in #57 shows no !MULTIVIEW traffic either
# way - and no third-party mapping, unlike BACK:
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

# P200 only. The P200 has the embedded StreamUnlimited streaming module
# and the family docstring above is wrong about it - measured, with a
# live Spotify Connect session (issue #60):
#
#   !SRC(4)"Spotify"  !STREAMTYPE? -> !STREAMTYPE(2)
#
# 2 is Spotify in MP60_STREAM_TYPES, so the P200 uses the MP numbering
# rather than one of its own. !STREAMTYPE follows what the streaming
# MODULE is playing, not the selected source: it stayed 2 while the
# Spotify session was alive with an unrelated source selected, and went
# to 0 once switching sources ended it. So 0 means "idle", not "this
# model has no streaming" - which is how the earlier !STREAMTYPE(0)
# capture with nothing playing was misread.
#
# Only Spotify (2) is directly confirmed; the rest of the table is
# carried over from MP on the strength of index 2 matching. The device
# also answers the StreamUnlimited HTTP JSON API on port 8080 for every
# path streaming/client.py uses, and reports settings:/version 5.4.1 -
# the same streaming firmware as the MP family, which is why sharing
# their table is reasonable rather than merely convenient.
# The WHOLE P family has the streaming module, not just the P200.
#
# The P200 is measured (issue #60). P100 and P300 rest on the vendor
# manual, and specifically on how carefully it marks model restrictions:
#
#   20 16-Channel Input (optional for P200/P300)
#    5 HDMI 5 (applicable for P200/P300 only)
#    9 Internal (applicable for P200/P300 only)
#   VIDEO OUTPUTS (applicable for P200/P300 only)
#   "The P100 and Head Unit features the installer menu only."
#
# Every P100 limitation is called out explicitly, including an on-screen
# menu difference. In that table:
#
#   11 Internal Player      <- unmarked
#   12 USB                  <- unmarked
#
# An unmarked entry in a document that annotates every other per-model
# restriction is positive evidence, not merely silence. Index 11 also
# agrees with the MP table and with the P200's measured !AUDIN(11), so
# it is not a transcription artefact.
#
# The manual documents no !STREAMTYPE for ANY P model - including the
# P200, which demonstrably has it - so the command's absence there says
# nothing either way. The manual predates the per-service audio inputs
# (its Audio Return Channel is 21, where the P200 reports 24, and it
# lacks 37/41/42 entirely), which is consistent with it describing an
# earlier firmware rather than a different capability.
#
# This is manual-derived, NOT measured, for P100/P300. It is a weaker
# footing than the P200 and is recorded as such. If either is ever
# probed and lacks streaming, narrow this rather than arguing with the
# device.
P_STREAM_TYPES = MP60_STREAM_TYPES

# Kept as a name because P200_CONFIG referenced it before the manual
# settled the rest of the family; identical to P_STREAM_TYPES.
P200_STREAM_TYPES = P_STREAM_TYPES

# The streaming queries. Measured on a P200; extended to P100/P300 on
# the manual's own evidence - see P_HAS_STREAMING below.
P_STREAMING_MESSAGES: dict[Msg, str] = {
    **P_MESSAGES,
    Msg.STREAM_TYPE: "STREAMTYPE",
    Msg.ZONE_B_STREAM_TYPE: "ZSTREAMTYPE",
}

# Retained name; P200 uses the same table as the rest of the family.
P200_MESSAGES = P_STREAMING_MESSAGES

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

# P200 only - P_SETUP_MESSAGES plus the two streaming queries. Both
# answer on this model (issue #60).
P_STREAMING_SETUP_MESSAGES: list[str] = [
    *P_SETUP_MESSAGES,
    f"{P_STREAMING_MESSAGES[Msg.STREAM_TYPE]}?",
    f"{P_STREAMING_MESSAGES[Msg.ZONE_B_STREAM_TYPE]}?",
]

P200_SETUP_MESSAGES = P_STREAMING_SETUP_MESSAGES

# P100 Hardware Configuration
# Entry-level processor: 4 HDMI inputs, no video output routing
P100_VIDEO_INPUTS = {
    0: "None",
    1: "HDMI 1",
    2: "HDMI 2",
    3: "HDMI 3",
    4: "HDMI 4",
}

# The P family's audio inputs, and NEITHER published table is right on
# its own - this is a merge, and both halves are load-bearing.
#
# The manual's table is correct for the physical inputs: 2 (8 Channel
# Analog) and 13-17 (Analog 1-5) exist on these processors and appear in
# no MP table at all. Take those from the manual.
#
# It is wrong from 20 up. A real P200 reports Audio Return Channel as
# 24, where the manual says 21 - and the manual gives 21 to ARC while
# the MP table gives 21 to "16-Channel 2.0". So on this range the manual
# does not merely omit entries, it names one WRONG, which is worse: an
# index the device really sends would render as the wrong input. Take
# 20-24 and the per-service streaming inputs (35-44) from MP, which the
# P200 measurement confirms (37 Spotify, 41 Storage, 42 airable, 24 ARC
# - issue #60).
#
# The manual predates those per-service inputs (added to the MP line in
# firmware 5.0.1), which is why it describes an older device rather than
# a different one. That is also why this applies to all three models
# and not just the measured P200: the divergence is a firmware
# generation, not a hardware difference, and the three share a software
# line. A P100 given the manual's table alone would report ARC as
# "Audio Return Channel" at an index its firmware uses for something
# else.
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
    # 20-24 from MP, not the manual - see above.
    20: "16-Channel (optional AES module)",
    21: "16-Channel 2.0 (optional AES module)",
    22: "16-Channel 5.1 (optional AES module)",
    23: "16-Channel 7.1 (optional AES module)",
    24: "Audio Return Channel",
    # Per-streaming-service inputs. 37/41/42 measured on a P200.
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

# P100 has no 16-channel input: the manual marks index 20 "optional for
# P200/P300", the same annotation it uses for the HDMI inputs and video
# outputs the P100 lacks. Audio Return Channel (24) is unmarked and so
# stays. Dropping the four rather than leaving them harmless-but-wrong,
# because "this model has a 16-channel AES option" is a claim a consumer
# could reasonably render in a UI.
P100_AUDIO_INPUTS = {
    index: name
    for index, name in P_AUDIO_INPUTS.items()
    if index not in (20, 21, 22, 23)
}

P100_CONFIG = ModelConfig(
    model_name="p100",
    manufacturer="Lyngdorf",
    messages=P_STREAMING_MESSAGES,
    setup_commands=P_STREAMING_SETUP_MESSAGES,
    video_inputs=P100_VIDEO_INPUTS,
    audio_inputs=P100_AUDIO_INPUTS,
    stream_types=P_STREAM_TYPES,
    has_streaming=True,
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
    # The P200 diverges from the rest of the family on all four of these -
    # it has the streaming module, uses the MP stream-type numbering and
    # the MP audio-input table, and answers the streaming queries. All
    # measured (issue #60); P100 and P300 keep the manual's tables.
    messages=P200_MESSAGES,
    setup_commands=P200_SETUP_MESSAGES,
    video_inputs=P_VIDEO_INPUTS,
    audio_inputs=P_AUDIO_INPUTS,
    stream_types=P200_STREAM_TYPES,
    has_streaming=True,
    video_outputs=P_VIDEO_OUTPUTS,
    has_zone_b=True,
    has_video=True,
    lipsync_default_range=P_LIPSYNC_DEFAULT_RANGE,
    volume_range=P_VOLUME_RANGE,
    # Zone B clamps a tenth of a dB higher than the manual says and than
    # the main zone does - measured, see P200_ZONE_B_VOLUME_RANGE.
    zone_b_volume_range=P200_ZONE_B_VOLUME_RANGE,
    # P200 only - see the MULTIVIEW note above P_REMOTE_KEYS.
    remote_keys=P200_REMOTE_KEYS,
)

P300_CONFIG = ModelConfig(
    model_name="p300",
    manufacturer="Lyngdorf",
    messages=P_STREAMING_MESSAGES,
    setup_commands=P_STREAMING_SETUP_MESSAGES,
    video_inputs=P_VIDEO_INPUTS,
    audio_inputs=P_AUDIO_INPUTS,
    stream_types=P_STREAM_TYPES,
    has_streaming=True,
    video_outputs=P_VIDEO_OUTPUTS,
    has_zone_b=True,
    has_video=True,
    lipsync_default_range=P_LIPSYNC_DEFAULT_RANGE,
    volume_range=P_VOLUME_RANGE,
    zone_b_volume_range=P_VOLUME_RANGE,
    remote_keys=P_REMOTE_KEYS,
)
