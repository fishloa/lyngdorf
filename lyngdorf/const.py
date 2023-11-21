#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This module inherits constants for Lyngdorf receivers.

:license: MIT, see LICENSE for more details.
"""

import attr

ATTR_SETATTR = [attr.setters.validate, attr.setters.convert]

DEFAULT_LYNGDORF_PORT = 84

POWER_ON = "1"
POWER_OFF = "0"


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

COMMANDS_SETUP = [
    "VERB(1)",
    "DEVICE?",
    "POWER?",
    "POWERZONE2?",
    "AUDIN?",
    "AUDMODE?",
    "AUDTYPE?",
    "RPFOCS?",
    "RPFOC?",
    "AUDMODEL?",
    "SRC?",
    "SRCS?",
    "VOL?",
    "ZVOL?",
    "MUTE?",
    "ZMUTE?",
    "VIDIN?",
    "VIDTYPE?",
    "STREAMTYPE?",
    "ZSTREAMTYPE?",
]

COMMAND_KEEP_ALIVE = "PING?"
RESPONSE_KEEP_ALIVE = "PONG"

RESPONSES = {
    "AUDIN": "Selected audio input",
    "AUDMODE": "Audio processing mode",
    "AUDMODECOUNT": "List of audio processing modes",
    "AUDTYPE": "String describing the current audio input type",
    "DEFVOL": "Default volume setting",
    "DEVICE": "Device Name",
    "DTSDIALOG": "DTS Dialog Control",
    "DTSDIALOGAVAILABLE": "Current availability of DTS Dialog Control",
    "HDMIMAINOUT": "Which HDMI output is used for main out",
    "LOUDNESS": "Loudness status",
    "MAXVOL": "Maximum volume setting",
    "POWER": "Power status",
    "POWERZONE2": "Power status for Zone B",
    "MUTEON": "Mute is ON",
    "MUTEOFF": "Mute is OFF",
    "RPFOC": "RoomPerfect position",
    "RPFOCCOUNT": "Available RoomPerfect positions",
    "RPVOI": "Active voicing",
    "RPVOICOUNT": "List of available voicings",
    "SRCOFF": "Source volume offset for current source",
    "SRCCOUNT": "List of available sources",
    "STANDBYLEVEL": "Current setting for standby level",
    "STREAMTYPE": "Type of the current network player source",
    "TRIMBASS": "Bass level trim (10 = 1dB)",
    "TRIMCENTER": "Center channel level trim (10 = 1dB)",
    "TRIMHEIGHT": "Height channels level trim (10 = 1dB)",
    "TRIMLFE": "LFE channel level trim (10 = 1dB)",
    "TRIMSURRS": "Surround channels level trim (10 = 1dB)",
    "TRIMTREB": "Treble level trim (10 = 1dB)",
    "VERB": "Verbosity level of active interface.",
    "VIDIN": "Selected video input",
    "VIDTYPE": "Current video input",
    "VOL": "Main Volume",
    "ZAUDIN": "Zone B audio input. (See list)",
    "ZSRCCOUNT": "List of available Zone B sources",
    "ZSTREAMTYPE": "Type of the network player when playing on Zone B",
    "ZVOL": "Zone B volume",
    "SRC": "Active source",
    "ZSRC": "Zone B source",
    "ZMUTEON": "Zone B Mute is ON",
    "ZMUTEOFF": "Zone B Mute is OFF",
}

RESPONSES_KEYS_ALL = sorted(set(RESPONSES.keys()))
