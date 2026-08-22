"""Compile-only. The §6 entity-description contract, pinned.

Never imported, never run: `mypy --strict` checks it in CI beside the
package, so a change that breaks the consumer's lambda pattern fails here
before it fails in Home Assistant. The negative cases are commented out
with the exact error they must produce — uncomment one to check the
pin still bites.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from lyngdorf import (
    LyngdorfReceiver,
    NumericControl,
    Player,
    SteppableControl,
    Trim,
    ZoneB,
)


@dataclass(frozen=True, kw_only=True)
class SelectDescription:
    key: str
    options_fn: Callable[[LyngdorfReceiver], list[str]]
    current_fn: Callable[[LyngdorfReceiver], str | None]
    select_fn: Callable[[LyngdorfReceiver, str], Awaitable[None]]


SOURCE = SelectDescription(
    key="source",
    options_fn=lambda r: r.sources,
    current_fn=lambda r: r.source,
    select_fn=lambda r, v: r.set_source(v),
)


@dataclass(frozen=True, kw_only=True)
class SwitchDescription:
    key: str
    is_on_fn: Callable[[LyngdorfReceiver], bool | None]
    set_fn: Callable[[LyngdorfReceiver, bool], Awaitable[None]]


MUTE = SwitchDescription(
    key="mute",
    is_on_fn=lambda r: r.muted,
    set_fn=lambda r, v: r.set_muted(v),
)


@dataclass(frozen=True, kw_only=True)
class NumberDescription:
    key: str
    control_fn: Callable[[LyngdorfReceiver], NumericControl | None]


NUMBERS = [
    NumberDescription(key="volume", control_fn=lambda r: r.volume),
    NumberDescription(key="lipsync", control_fn=lambda r: r.lipsync),
    NumberDescription(key="bass", control_fn=lambda r: r.trims.get(Trim.BASS)),
]


def entity_bounds(ctl: NumericControl) -> tuple[float, float, float]:
    rng = ctl.range
    return rng.min, rng.max, rng.step


async def set_value(ctl: NumericControl, value: float) -> None:
    await ctl.set(value)


def step_only_where_stepping_exists(receiver: LyngdorfReceiver) -> list[str]:
    steppable: list[str] = []
    for trim, ctl in receiver.trims.items():
        if isinstance(ctl, SteppableControl):
            steppable.append(trim.value)
    return steppable


async def gated_zone_b(receiver: LyngdorfReceiver) -> float | None:
    if (zone_b := receiver.zone_b) is None:
        return None
    return _zone_b_volume(zone_b)


def _zone_b_volume(zone_b: ZoneB) -> float | None:
    return zone_b.volume.value


async def gated_player(receiver: LyngdorfReceiver) -> bool:
    if (player := receiver.player) is None:
        return False
    return await _pause(player)


async def _pause(player: Player) -> bool:
    return await player.pause()


# --- Negative cases: each MUST fail. Uncomment one to verify the pin. ---
#
# def unguarded_component(receiver: LyngdorfReceiver) -> float:
#     # error: Item "None" of "ZoneB | None" has no attribute "volume"
#     #   [union-attr]
#     return receiver.zone_b.volume.value
#
# async def step_a_non_steppable(ctl: NumericControl) -> None:
#     # error: "NumericControl" has no attribute "up"  [attr-defined]
#     await ctl.up()
#
# def assign_a_read_only_property(receiver: LyngdorfReceiver) -> None:
#     # error: Property "power_on" defined in "LyngdorfReceiver" is
#     #   read-only  [misc]
#     receiver.power_on = True
