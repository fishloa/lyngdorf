#!/usr/bin/env python3
"""
Lyngdorf Audio Control Library - Constants Module.

Shared constants and protocol definitions for all supported Lyngdorf
receiver models.

Protocol Families (member models are enumerated in the per-family modules,
not repeated here):
- MP Family: shared protocol - see models/mp_series.py
- TDAI Family: TDAI-1120/TDAI-2210/TDAI-3400 share one protocol; TDAI-2170
  is the odd one out, with an older, more limited protocol - see
  models/tdai_series.py
- P Family: MP-like protocol, no channel trims. Streaming is NOT uniform:
  the P200 has the module and uses the MP stream-type numbering, the
  P100/P300 are unmeasured - see models/p_series.py

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
# Delay between setup commands during connection. Verified against a real
# MP-60: writing all ~30 setup commands back-to-back with no pacing causes
# the device to silently stop replying partway through the burst (volume,
# mute, and trim never populate). 50ms pacing was confirmed sufficient.
SETUP_COMMAND_DELAY = 0.05

# Minimum spacing enforced between writes drained from LyngdorfApi's
# outbound command queue (see LyngdorfApi._writeCommand/_drain_write_queue).
# A real MP-60 has a fixed queue-depth cliff of ~16 in-flight commands -
# past it, everything is silently dropped with no error, though the device
# self-heals once traffic backs off - see
# https://github.com/fishloa/lyngdorf/issues/35 for the measurement. 50ms
# matches SETUP_COMMAND_DELAY above, already confirmed sufficient for the
# analogous connect-time burst, and keeps any runtime burst's in-flight
# count far under that cliff.
COMMAND_PACING_MS = 50

# Now-playing metadata (streaming-capable models only - see
# ModelConfig.has_streaming). A separate HTTP JSON API run by the embedded
# streaming module (StreamUnlimited StreamSDK), not part of the :84 RIO
# protocol at all - reverse-engineered, no vendor documentation. Confirmed
# live against a real MP-60. See lyngdorf/streaming.py.
STREAMMAGIC_PORT = 8080
NOW_PLAYING_PATH = "player:player/data"
# Elapsed playback position, in milliseconds. A sibling node of
# NOW_PLAYING_PATH rather than a field inside it - the payload at
# NOW_PLAYING_PATH carries `status.duration` but no position. Subscribing
# to this path on the event queue pushes a new value roughly once a
# second while playing (the device's own web client does exactly this).
NOW_PLAYING_POSITION_PATH = "player:player/data/playTime"
# Transport control. `activate` rather than `value`: this node is an action,
# not a setting. Confirmed against a real MP-60 - see lyngdorf/streaming.py.
CONTROL_PATH = "player:player/control"
# Combined shuffle/repeat mode. One enum, not two independent flags.
PLAY_MODE_PATH = "settings:/mediaPlayer/playMode"
# The device's global play-mode enum (e.g. normal/shuffle/repeatOne on an
# MP-60), fetched via `getRows` rather than `getData` since this node is a
# list. Unioned with a source's own per-source `controls.playMode` in the
# now-playing payload rather than preferred over it - each list is a
# partial view of the device's six-value 2x3 grid (this global list omits
# the repeatAll variants; the per-source list separately omits `normal`) -
# see `LyngdorfApi.available_play_modes`.
PLAY_MODES_PATH = "settings:/mediaPlayer/playModes"
# How long a single long-poll (`pollQueue`) call blocks server-side waiting
# for a change before returning empty. Comfortably under typical HTTP
# client/proxy idle timeouts.
NOW_PLAYING_POLL_TIMEOUT = 25
# How far a reported position may drift from where the clock says it should
# be (previous position + elapsed wall-clock time) before it counts as a
# discontinuity rather than ordinary progression. Loose enough to absorb
# network jitter and the device's own ~1s reporting granularity, but tight
# enough to catch a real seek. See LyngdorfApi.register_position_jump_callback.
POSITION_DRIFT_TOLERANCE_MS = 2000

# Power States
# The MP and P families report power as a numeric parameter: `!POWER(1)`.
POWER_ON = "1"
POWER_OFF = "0"

# The TDAI family spells its power and mute states as words instead:
# `!PWR(ON)` / `!PWR(OFF)` and `!MUTE(ON)` / `!MUTE(OFF)`. See
# docs/tdai-1120.md, docs/tdai-2170.md and docs/tdai-3400.md; the MP and
# P equivalents are in docs/mp-60.md and docs/p-series.md.
STATE_ON = "ON"
STATE_OFF = "OFF"

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
        "VOLUME_UP",  # TDAI: literal VOLUP token (no VOL+ shorthand)
        "VOLUME_DOWN",  # TDAI: literal VOLDN token (no VOL- shorthand)
        "MUTE",
        "MUTE_ON",
        "MUTE_OFF",
        "SOURCES_COUNT",
        "SOURCE",
        "SOURCES",  # Source list query
        "SOURCE_LIST",  # TDAI source list query
        "SOURCE_NAME",  # TDAI current-source-with-name query / list-population key
        "SOURCES_ENABLED",  # TDAI-2170 bitmask of which fixed sources are enabled
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
        "ROOM_PERFECT_POSITION_LIST",  # TDAI Room Perfect position list query
        "ROOM_PERFECT_POSITION_NAME",  # TDAI current-position-with-name query / list-population key
        "ROOM_PERFECT_POSITIONS_PRESENT",  # TDAI-2170 bitmask of which fixed positions are present
        "ROOM_PERFECT_VOICINGS_COUNT",
        "ROOM_PERFECT_VOICING",
        "ROOM_PERFECT_VOICINGS",  # Room Perfect voicing list query
        "ROOM_PERFECT_VOICING_LIST",  # TDAI Room Perfect voicing list query
        "ROOM_PERFECT_VOICING_NAME",  # TDAI current-voicing-with-name query / list-population key
        "ROOM_PERFECT_VOICINGS_ENABLED",  # TDAI-2170 bitmask of which fixed voicings are enabled
        "LIP_SYNC",
        "LIP_SYNC_MIN_MAX",
        "TRIM_BASS",
        "TRIM_CENTRE",
        "TRIM_HEIGHT",
        "TRIM_LFE",
        "TRIM_SURROUND",
        "TRIM_TREBLE",
        "TRIM_TREBLE_SET",
        "BALANCE",  # Audio balance control
        # Max volume query. MP and P families (docs/p-series.md documents
        # !MAXVOL too, and a real P200 answers it - see #57); query only,
        # never written, see VolumeControl.maximum_volume.
        "MAX_VOLUME",
        # !DEFVOL - the power-on default volume - is deliberately NOT
        # modelled, and this is a decision rather than an omission.
        #
        # It is a speaker-safety setting, and the hazard is specific to
        # what it does: it takes effect at power-on, when nobody is at
        # the controls. A bad write to !VOL is audible immediately and
        # someone turns it down. A bad write to !DEFVOL is silent now and
        # arrives at whatever volume it was left at the next time the
        # device comes out of standby - into a room that may be empty, or
        # not. A library bug, a mistaken automation or a misread scale
        # would all express themselves that way, and the library cannot
        # tell any of them from a deliberate change.
        #
        # So this is left to the front panel and the official app, where
        # a human is present for the decision. Consistent with !MAXVOL
        # above, which is likewise read and never written: the two safety
        # ceilings are things this library reports, not things it sets.
        # Reading !DEFVOL alone would be harmless, but it earns nothing
        # on its own and having the message present is an invitation to
        # add the setter later, so it stays out entirely.
        #
        # Documented for both families and measured on a P200
        # (!DEFVOL(-450), #57). Do not add it because the manual has it.
        # Loudness toggle (MP only)
        "LOUDNESS",
        # DTS Dialog Control (MP only, surround content)
        "DTS_DIALOG_AVAILABLE",
        "DTS_DIALOG",
        "DTS_DIALOG_UP",
        "DTS_DIALOG_DOWN",
        # Video output query (MP only)
        "VIDEO_OUTPUT",
        # Source/voicing/position stepping
        "SOURCE_NEXT",
        "SOURCE_PREV",
        "SOURCE_BUTTON",  # MP only - toggles source menu
        "VOICING_NEXT",
        "VOICING_PREV",
        "FOCUS_POSITION_NEXT",
        "FOCUS_POSITION_PREV",
        "AUDIO_MODE_NEXT",  # MP only
        "AUDIO_MODE_PREV",  # MP only
        "AUDIO_MODE_BUTTON",  # MP only - toggles audio mode menu
    ],
)

# Navigation/remote-control buttons (DIRU/DIRD/.../MENU/INFO/SETUP/BACK/EXIT/
# MULTIVIEW/NUM(0..9)) are deliberately NOT in `Msg` above - see
# lyngdorf/remote.py's module docstring for why. They are write-only (the
# device never replies to any of them), so they do not fit `Msg`'s
# bidirectional shape at all; each model's `RemoteKey` -> wire-command table
# lives in `ModelConfig.remote_keys` instead. See issue #46.

# Message types whose wire command is an *absolute* setter - `TOKEN(value)`,
# where the latest value fully supersedes any earlier one still waiting to
# be sent. LyngdorfApi's outbound command queue (see
# LyngdorfApi._writeCommand) coalesces repeated writes down to the latest
# only for the wire tokens these resolve to per model, since collapsing
# anything else would be wrong: a relative/stepping command (VOLUP/VOLDN,
# SRC+/SRC-, RPVOI+/-, ...) means "one more step" each time, and sequential
# input (the NUM(0..9) digits, cursor/menu navigation) means something
# different depending on order and count. Queries (`TOKEN?`) are excluded
# by shape alone - they never match `TOKEN(value)` - so a caller
# deliberately re-querying (e.g. mute on power-on) is never coalesced away.
ABSOLUTE_SETTER_MESSAGES: frozenset[Msg] = frozenset(
    {
        Msg.VOLUME,
        Msg.ZONE_B_VOLUME,
        Msg.TRIM_BASS,
        Msg.TRIM_CENTRE,
        Msg.TRIM_HEIGHT,
        Msg.TRIM_LFE,
        Msg.TRIM_SURROUND,
        Msg.TRIM_TREBLE,
        Msg.TRIM_TREBLE_SET,
        Msg.LIP_SYNC,
        Msg.BALANCE,
    }
)
