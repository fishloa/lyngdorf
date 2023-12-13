#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This module inherits constants for Lyngdorf receivers.

:license: MIT, see LICENSE for more details.
"""

import attr
from enum import Enum
from typing import Dict
from dataclasses import dataclass

ATTR_SETATTR = [attr.setters.validate, attr.setters.convert]

DEFAULT_LYNGDORF_PORT = 84
RECONNECT_BACKOFF = 0.5 # half a second to wait for the first reconnect
RECONNECT_SCALE = 2.5 # each reconnect attempt waits this times longer than the previous one
RECONNECT_MAX_WAIT = 30.0 # Reconnect tasks will wait this many seconds at a maximum between each attempt
MONITOR_INTERVAL = 90 # 90 seconds between PING commands

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
    35: "vTuner",
    36: "TIDAL",
    37: "Spotify",
    38: "Airplay",
    39: "Roon",
    40: "DLNA",
    41: "Storage",
    42: "airable"
}

MP60_ROOM_PERFECT_POSITIONS = {
    0: "Bypass",
    1: "Focus 1",
    2: "Focus 2",
    3: "Focus 3",
    4: "Focus 4",
    9: "Global"
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
    
Msg = Enum('Msg',
    ['DEVICE','VERBOSE', 'PING','PONG',
     'POWER', 'POWER_ON', 'POWER_OFF', 'VOLUME', 'MUTE', 'MUTE_ON', "MUTE_OFF", 'SOURCES_COUNT', 'SOURCE',
     'ZONE_B_POWER', 'ZONE_B_POWER_ON', 'ZONE_B_POWER_OFF', 'ZONE_B_VOLUME', 'ZONE_B_MUTE_ON', "ZONE_B_MUTE_OFF", 'ZONE_B_SOURCES_COUNT', 'ZONE_B_SOURCE',
     'AUDIO_IN', 'ZONE_B_AUDIO_IN', 'VIDEO_IN', 'STREAM_TYPE', 'ZONE_B_STREAM_TYPE',
     'VIDEO_TYPE', 'AUDIO_TYPE', 'AUDIO_MODES_COUNT', 'AUDIO_MODE',
     'ROOM_PERFECT_POSITIONS_COUNT', 'ROOM_PERFECT_POSITION', 'ROOM_PERFECT_VOICINGS_COUNT', 'ROOM_PERFECT_VOICING',
     'LIP_SYNC', 'LIP_SYNC_MIN_MAX',
     'TRIM_BASS', 'TRIM_CENTRE', 'TRIM_HEIGHT', 'TRIM_LFE', 'TRIM_SURROUND', 'TRIM_TREBLE', 'TRIM_TREBLE_SET'
     ]
    )



MP60_MESSAGES: Dict[Msg, str] = {
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
    Msg.AUDIO_IN: "AUDIN",
    Msg.STREAM_TYPE: "STREAMTYPE",
    Msg.VIDEO_IN: "VIDIN",
    Msg.AUDIO_MODES_COUNT: "AUDMODECOUNT",
    Msg.AUDIO_MODE: "AUDMODE",
    Msg.AUDIO_TYPE: "AUDTYPE",
    Msg.VIDEO_TYPE: "VIDTYPE",
    Msg.ROOM_PERFECT_POSITIONS_COUNT: "RPFOCCOUNT",
    Msg.ROOM_PERFECT_POSITION: "RPFOC",
    Msg.ROOM_PERFECT_VOICINGS_COUNT: "RPVOICOUNT",
    Msg.ROOM_PERFECT_VOICING: "RPVOI",
    Msg.LIP_SYNC: "LIPSYNC",
    Msg.LIP_SYNC_MIN_MAX: "LIPSYNCRANGE",
    Msg.ZONE_B_POWER: "POWERZONE2",
    Msg.ZONE_B_POWER_ON: "POWERONZONE2",
    Msg.ZONE_B_POWER_OFF: "POWEROFFZONE2",
    Msg.ZONE_B_VOLUME: "ZVOL",
    Msg.ZONE_B_MUTE_ON: "ZMUTEON",
    Msg.ZONE_B_MUTE_OFF: "ZMUTEOFF",
    Msg.ZONE_B_SOURCES_COUNT: "ZSRCCOUNT",
    Msg.ZONE_B_SOURCE: "ZSRC",
    Msg.ZONE_B_AUDIO_IN: "ZAUDIN",
    Msg.ZONE_B_STREAM_TYPE: "ZSTREAMTYPE",
    Msg.TRIM_BASS: "TRIMBASS",
    Msg.TRIM_CENTRE: "TRIMCENTER",
    Msg.TRIM_HEIGHT: "TRIMHEIGHT",
    Msg.TRIM_LFE: "TRIMLFE",
    Msg.TRIM_SURROUND: "TRIMSURRS",
    Msg.TRIM_TREBLE: "TRIMTREBLE",
    Msg.TRIM_TREBLE_SET: "TRIMTREB"
}
 

MP60_SETUP_MESSAGES = [
    "VERB(1)",
    "DEVICE?",
    "POWER?",
    "POWERZONE2?",
    "AUDMODEL?",
    "SRCS?",
    "ZSRCS?",
    "RPFOCS?",
    "RPVOIS?",
    
    "AUDMODE?",
    "SRC?",
    "ZSRC?",
    "RPFOC?",
    "RPVOI?",
    "VIDTYPE?",
    "STREAMTYPE?",
    "LIPSYNC?"
    "ZSTREAMTYPE?",
    
    "AUDIN?",
    "VIDIN?",
    "AUDTYPE?",
    "VOL?",
    "ZVOL?",
    "MUTE?",
    "ZMUTE?",
    
    "TRIMBASS?",
    "TRIMCENTER?",
    "TRIMHEIGHT?",
    "TRIMLFE?",
    "TRIMSURRS?",
    "TRIMTREB?"
]


# @dataclass
# class LyngdorfModelMixin:
#     _model: str
#     _manufacterer: str
#     _commands: Dict[Msg, str]
#     _setup_commands: list[str]
    
#     @property
#     def model(self) -> str:
#         return self._model
    
#     @property
#     def manufacturer(self) -> str:
#         return self._manufacterer
    
#     @property
#     def setup_commands(self) -> list[str]:
#         return self._setup_commands
    
#     @property
#     def commands(self) -> Dict[Msg, str]:
#         return self._commands
    
#     def lookup_command(self, key: Msg) -> str:
#         return self.commands[key]
@dataclass
class LyngdorfModelMixin:
    _model: str
    _manufacterer: str
    _commands: Dict[Msg, str]
    _setup_commands: list[str]
    
    @property
    def model(self) -> str:
        return self._model
    
    @property
    def manufacturer(self) -> str:
        return self._manufacterer
    
    @property
    def setup_commands(self) -> list[str]:
        return self._setup_commands
    
    def lookup_command(self, key: Msg) -> str:
        return self._commands[key]
    

class LyngdorfModel(LyngdorfModelMixin, Enum):
    MP_60 = "mp-60", "Lyngdorf", MP60_MESSAGES, MP60_SETUP_MESSAGES


# RESPONSES = {
#     "AUDIN": "Selected audio input",
#     "AUDMODE": "Audio processing mode",
#     "AUDMODECOUNT": "List of audio processing modes",
#     "AUDTYPE": "String describing the current audio input type",
#     "DEFVOL": "Default volume setting",
#     "DEVICE": "Device Name",
#     "DTSDIALOG": "DTS Dialog Control",
#     "DTSDIALOGAVAILABLE": "Current availability of DTS Dialog Control",
#     "HDMIMAINOUT": "Which HDMI output is used for main out",
#     "LIPSYNC": 
#     "LOUDNESS": "Loudness status",
#     "MAXVOL": "Maximum volume setting",
#     "POWER": "Power status",
#     "POWERZONE2": "Power status for Zone B",
#     "MUTEON": "Mute is ON",
#     "MUTEOFF": "Mute is OFF",
#     "RPFOC": "RoomPerfect position",
#     "RPFOCCOUNT": "Available RoomPerfect positions",
#     "RPVOI": "Active voicing",
#     "RPVOICOUNT": "List of available voicings",
#     "SRCOFF": "Source volume offset for current source",
#     "SRCCOUNT": "List of available sources",
#     "STANDBYLEVEL": "Current setting for standby level",
#     "STREAMTYPE": "Type of the current network player source",
#     "TRIMBASS": "Bass level trim (10 = 1dB)",
#     "TRIMCENTER": "Center channel level trim (10 = 1dB)",
#     "TRIMHEIGHT": "Height channels level trim (10 = 1dB)",
#     "TRIMLFE": "LFE channel level trim (10 = 1dB)",
#     "TRIMSURRS": "Surround channels level trim (10 = 1dB)",
#     "TRIMTREB": "Treble level trim (10 = 1dB)",
#     "VERB": "Verbosity level of active interface.",
#     "VIDIN": "Selected video input",
#     "VIDTYPE": "Current video input",
#     "VOL": "Main Volume",
#     "ZAUDIN": "Zone B audio input. (See list)",
#     "ZSRCCOUNT": "List of available Zone B sources",
#     "ZSTREAMTYPE": "Type of the network player when playing on Zone B",
#     "ZVOL": "Zone B volume",
#     "SRC": "Active source",
#     "ZSRC": "Zone B source",
#     "ZMUTEON": "Zone B Mute is ON",
#     "ZMUTEOFF": "Zone B Mute is OFF",
# }

# RESPONSES_KEYS_ALL = sorted(set(RESPONSES.keys()))
