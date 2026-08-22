"""Per-family RIO registration tables (spec §4's "dialects").

Each `Dialect` enumerates, per registration group, which wire `Msg` routes
to which receiver-instance callback attribute - mirroring `Receiver`'s
`_register_*_callbacks` hooks in device.py (mute, source,
room_perfect_position, voicing, video, zone_b, surround_trim). This module
holds pure data: no receiver import, no `_register_callback` call, no
cycle. `Receiver` resolves each attribute path on itself with
`resolve_attr` at registration time and hands the bound callable to its
own `_register_callback`.

Callback *bodies* (parsing SRCNAME's comma-packed name, TDAI-2170's
bitmask tables, ...) are not here - they are receiver state mutation, not
wire-protocol knowledge, and stay on `Receiver` in device.py. This module
only says which message means which callback, per family.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, cast

from ..const import Msg

if TYPE_CHECKING:
    from ..base import CountingNumberDict


def resolve_attr(receiver: object, path: str) -> Callable[[str, str], None]:
    """Resolve a possibly dotted attribute path against `receiver`, e.g.
    "_sources.count_callback" -> receiver._sources.count_callback.

    The cast is safe by construction, not by inspection: every path in
    the dialect tables below names either a `Receiver` callback method or
    a `CountingNumberDict.count_callback` - both always shaped
    `(self, param1: str, param2: str) -> None`. `getattr` cannot itself
    be typed narrower than `object` here, since `path` is arbitrary from
    mypy's point of view even though it never actually is at runtime.
    """
    target: object = receiver
    for part in path.split("."):
        target = getattr(target, part)
    return cast(Callable[[str, str], None], target)


def populate_fixed_list(
    target: CountingNumberDict, fixed_names: dict[int, str], bitmask: str
) -> None:
    """Populate a dict of fixed, hardware-defined names filtered by a
    bitmask reply (e.g. TDAI-2170's SRCENABLED/RPSTATUS/VOIENABLED).

    Bit 0 is the least-significant bit, i.e. the rightmost character
    of the bitmask string, per the vendor manual.
    """
    enabled_indices = [i for i, bit in enumerate(reversed(bitmask)) if bit == "1"]
    target.count_callback(str(len(enabled_indices)), "")
    for index in enabled_indices:
        if index in fixed_names:
            target.add(index, fixed_names[index])


@dataclasses.dataclass(frozen=True, slots=True)
class Dialect:
    """One family's registration table, one `Sequence[(Msg, attr path)]`
    per registration group. Groups with no entries mean "this family
    registers nothing for this group" - the same no-op the base `Receiver`
    class used to express as an empty method body.
    """

    mute: Sequence[tuple[Msg, str]]
    source: Sequence[tuple[Msg, str]]
    room_perfect_position: Sequence[tuple[Msg, str]]
    voicing: Sequence[tuple[Msg, str]]
    video: Sequence[tuple[Msg, str]] = ()
    zone_b: Sequence[tuple[Msg, str]] = ()
    surround_trim: Sequence[tuple[Msg, str]] = ()


_MP_P_VIDEO: tuple[tuple[Msg, str], ...] = (
    (Msg.AUDIO_IN, "_audio_input_callback"),
    (Msg.VIDEO_IN, "_video_input_callback"),
    (Msg.VIDEO_TYPE, "_video_info_callback"),
)

_MP_P_ZONE_B: tuple[tuple[Msg, str], ...] = (
    (Msg.ZONE_B_VOLUME, "_zone_b_volume_callback"),
    (Msg.ZONE_B_MUTE_ON, "_zone_b_mute_on_callback"),
    (Msg.ZONE_B_MUTE_OFF, "_zone_b_mute_off_callback"),
    (Msg.ZONE_B_SOURCES_COUNT, "_zone_b_sources.count_callback"),
    (Msg.ZONE_B_SOURCE, "_zone_b_source_callback"),
    (Msg.ZONE_B_AUDIO_IN, "_zone_b_audio_input_callback"),
    (Msg.ZONE_B_STREAM_TYPE, "_zone_b_stream_type_callback"),
    (Msg.ZONE_B_POWER, "_zone_b_power_callback"),
)

_MP_SURROUND_TRIM: tuple[tuple[Msg, str], ...] = (
    (Msg.TRIM_CENTRE, "_trim_centre_callback"),
    (Msg.TRIM_HEIGHT, "_trim_height_callback"),
    (Msg.TRIM_LFE, "_trim_lfe_callback"),
    (Msg.TRIM_SURROUND, "_trim_surround_callback"),
)

# The base Receiver's own defaults (device.py:202-237 at main@ae31374):
# MP/P-shaped mute/source/RoomPerfect, and no video/Zone B/surround trim -
# TestReceiverClassHierarchy.test_base_receiver_has_noop_defaults_for_optional_features
# pins this exact shape for a bare Receiver.
BASE_DIALECT = Dialect(
    mute=(
        (Msg.MUTE_ON, "_mute_on_callback"),
        (Msg.MUTE_OFF, "_mute_off_callback"),
    ),
    source=(
        (Msg.SOURCES_COUNT, "_sources.count_callback"),
        (Msg.SOURCE, "_source_callback"),
        (Msg.STREAM_TYPE, "_stream_type_callback"),
    ),
    room_perfect_position=(
        (Msg.ROOM_PERFECT_POSITIONS_COUNT, "_room_perfect_positions.count_callback"),
        (Msg.ROOM_PERFECT_POSITION, "_room_perfect_position_callback"),
    ),
    voicing=(
        (Msg.ROOM_PERFECT_VOICINGS_COUNT, "_voicings.count_callback"),
        (Msg.ROOM_PERFECT_VOICING, "_voicing_callback"),
    ),
)

# _VideoZoneBReceiverMixin + MPReceiver (device.py:1557-1586 at main@ae31374).
MP_DIALECT = dataclasses.replace(
    BASE_DIALECT,
    video=_MP_P_VIDEO,
    zone_b=_MP_P_ZONE_B,
    surround_trim=_MP_SURROUND_TRIM,
)

# _VideoZoneBReceiverMixin + PReceiver: video/Zone B, no discrete channel
# trims (device.py:1557-1591).
P_DIALECT = dataclasses.replace(BASE_DIALECT, video=_MP_P_VIDEO, zone_b=_MP_P_ZONE_B)

# TDAIReceiverBase (device.py:1603-1627): !MUTE(ON)/!MUTE(OFF) instead of
# distinct MUTEON/MUTEOFF; SRCNAME/RPNAME/VOINAME comma-packed names
# instead of the MP/P bare index+name burst; no video/Zone B/surround
# trim (base no-op applies).
TDAI_DIALECT = dataclasses.replace(
    BASE_DIALECT,
    mute=((Msg.MUTE, "_mute_callback"),),
    source=(
        (Msg.SOURCES_COUNT, "_sources.count_callback"),
        (Msg.SOURCE_NAME, "_source_name_callback"),
        (Msg.STREAM_TYPE, "_stream_type_callback"),
    ),
    room_perfect_position=(
        (Msg.ROOM_PERFECT_POSITIONS_COUNT, "_room_perfect_positions.count_callback"),
        (Msg.ROOM_PERFECT_POSITION_NAME, "_room_perfect_position_name_callback"),
    ),
    voicing=(
        (Msg.ROOM_PERFECT_VOICINGS_COUNT, "_voicings.count_callback"),
        (Msg.ROOM_PERFECT_VOICING_NAME, "_voicing_name_callback"),
    ),
)

# TDAI2170Receiver (device.py:1686-1704): fixed hardware tables gated by
# bitmask replies, replacing TDAI_DIALECT's source/RoomPerfect-position/
# voicing groups. Mute is unchanged from TDAI_DIALECT.
TDAI_2170_DIALECT = dataclasses.replace(
    TDAI_DIALECT,
    source=(
        (Msg.SOURCES_ENABLED, "_sources_enabled_callback"),
        (Msg.SOURCE, "_fixed_source_callback"),
    ),
    room_perfect_position=(
        (
            Msg.ROOM_PERFECT_POSITIONS_PRESENT,
            "_room_perfect_positions_present_callback",
        ),
        (Msg.ROOM_PERFECT_POSITION, "_fixed_room_perfect_position_callback"),
    ),
    voicing=(
        (Msg.ROOM_PERFECT_VOICINGS_ENABLED, "_voicings_enabled_callback"),
        (Msg.ROOM_PERFECT_VOICING, "_fixed_voicing_callback"),
    ),
)
