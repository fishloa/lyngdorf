"""Compile-only. The §6 entity-description contract, pinned.

Never imported, never run: `mypy --strict` checks it in CI beside the
package, so a change that breaks the consumer's lambda pattern fails here
before it fails in Home Assistant. The negative cases are commented out
with the exact error they must produce — uncomment one to check the
pin still bites.

That claim was false until now: CI only ever ran `mypy lyngdorf/`, so
this file was type-checked by nobody and its guarantee was decorative.
It is in the gate as of this commit — see run-tests.yml, which now names
this directory explicitly.
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

# The D9 compat surface, pinned in ANNOTATION position on purpose. A
# deprecated name has to stay usable as a *type* for the release window,
# not merely resolve at runtime - and those are different properties. The
# first attempt at the const shim satisfied the second and failed the
# first, because a module __getattr__ hands mypy a variable rather than a
# class; consumers still annotating with the 1.x name got "Variable ...
# is not valid as a type" plus attr-defined on every member access.
#
# Nothing in our own suite annotates with a compat name, so nothing here
# could have caught it. That is why these three exist.
from lyngdorf.const import LyngdorfModel as _CompatModel
from lyngdorf.device import Receiver as _CompatReceiver
from lyngdorf.device import lookup_receiver_model as _compat_lookup


def compat_model_is_usable_as_a_type(model: _CompatModel) -> str:
    return model.config.model_name


def compat_receiver_is_usable_as_a_type(receiver: _CompatReceiver) -> bool | None:
    return receiver.muted


def compat_lookup_keeps_its_return_type(name: str) -> str | None:
    model = _compat_lookup(name)
    return None if model is None else model.config.model_name


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


# ---------------------------------------------------------------------------
# 1.11 ONLY: both surfaces, type-checked together.
#
# This is the release's entire thesis as a compile test. A consumer
# migrating platform by platform has, mid-migration, 1.x call sites and
# 2.0 call sites in the same tree against the same pin. If both do not
# type-check at once, the migration cannot be split into separate PRs and
# 1.11.0 has no reason to exist.
#
# Deleted with the rest of the compat layer.
# ---------------------------------------------------------------------------


def legacy_reads_volume_as_a_float(receiver: LyngdorfReceiver) -> float | None:
    """1.10 shape: the value IS the property, and may be None."""
    volume = receiver.volume
    if volume is None:
        return None
    return volume / 2.0  # arithmetic on it, as 1.x code does


async def modern_sets_volume_through_the_control(receiver: LyngdorfReceiver) -> None:
    """2.0 shape, same pin, same property."""
    volume = receiver.volume
    if volume is not None:
        await volume.set(-25.0)
        await volume.up()


def modern_passes_volume_where_a_control_is_wanted(
    receiver: LyngdorfReceiver,
) -> tuple[float, float, float] | None:
    """The dual type is a real NumericControl, not a look-alike: it
    satisfies a signature written against the 2.0 surface."""
    volume = receiver.volume
    return None if volume is None else entity_bounds(volume)


def legacy_assigns_the_restored_setters(receiver: LyngdorfReceiver) -> None:
    """The 18 restored setters, in the shapes 1.x consumers use. Every
    one of these is a `[misc] read-only` error against 2.0.0 - that is
    the wall this release exists to remove."""
    receiver.volume = -25.0
    receiver.power_on = True
    receiver.mute_enabled = True
    receiver.source = "Apple TV"
    receiver.sound_mode = "Stereo"
    receiver.voicing = "Neutral"
    receiver.room_perfect_position = "Focus 1"
    receiver.lipsync = 80.0
    receiver.trim_bass = 3.0
    receiver.zone_b_volume = -30.0


# --- Negative cases: each MUST fail. Uncomment one to verify the pin. ---
#
# def volume_is_not_unconditionally_a_float(receiver: LyngdorfReceiver) -> float:
#     # error: Incompatible return value type (got "FloatSteppableControl |
#     #   None", expected "float")  [return-value]
#     return receiver.volume
#
# async def a_non_steppable_dual_control_cannot_step(
#     receiver: LyngdorfReceiver,
# ) -> None:
#     # error: "FloatNumericControl" has no attribute "up"  [attr-defined]
#     if (lipsync := receiver.lipsync) is not None:
#         await lipsync.up()
