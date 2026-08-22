"""Numeric controls: one shape for volume, Zone B volume, trims and lipsync.

`NumericControl` is the public value / advisory-range / async-set triple
(2.0 design §2.3); `SteppableControl` adds up()/down() where the model has
a step command. Stepping is a fixed-per-model fact, so it is expressed as
a subtype, never a `can_step` flag a caller must remember to consult
(design §1.2, decision D4).

The controls hold no protocol knowledge: writes go through
constructor-injected bound methods of the internal RioClient, which owns
the per-model wire encoding (the #41 trim_bass_treble_scale split, TDAI's
literal VOLUP/VOLDN step tokens, the TRIMTREB set-command). The factory
functions at the bottom of this module select those writers per model, so
a caller never sees a scale or a wire token.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from .models import NumericRange


class Trim(StrEnum):
    """A tone/speaker trim band, keying `LyngdorfReceiver.trims`.

    Values are permanent public API strings. Spelling is American -
    CENTER/"center" - maintainer-ruled (design §2.3): it matches both Home
    Assistant core's conventions and the device's own TRIMCENTER wire
    command (models/mp_series.py). Internal identifiers that never surface
    (Msg.TRIM_CENTRE, ModelConfig.trim_centre_range, the _trim_centre_*
    callbacks) keep their existing British spelling - respelling them is
    churn with no consumer payoff; do not "tidy" them to match.
    """

    BASS = "bass"
    TREBLE = "treble"
    CENTER = "center"
    HEIGHT = "height"
    LFE = "lfe"
    SURROUND = "surround"


class NumericControl:
    """A settable numeric on the device: current value, advisory range,
    and an async setter.

    One instance exists per control the connected model actually has -
    capability is structural (design §5): a model without the control has
    no NumericControl at all, so nothing here can raise "unsupported".
    """

    def __init__(
        self,
        *,
        initial_range: NumericRange,
        send_set: Callable[[float], None],
    ) -> None:
        self._range = initial_range
        self._send_set = send_set
        self._value: float | None = None

    @property
    def value(self) -> float | None:
        """Current device-reported value in the control's unit (dB for
        volume/trims, ms for lipsync). None until the device first
        reports one."""
        return self._value

    @property
    def range(self) -> NumericRange:
        """Advisory (min, max, step). Never None - a model without the
        control has no NumericControl at all. For lipsync this is LIVE:
        seeded from the documented default, overwritten when the device
        answers LIPSYNCRANGE (see `_update_range`).

        ADVISORY ONLY - `set()` sends the value unchanged, unchecked
        (issues #37/#41/#42/#43). Versions 1.6.0/1.7.0 raised
        LyngdorfInvalidValueError for out-of-range values; that check was
        removed deliberately because the device itself already bounds
        these values sensibly - probing a real MP-60, !VOL(240) is
        accepted and 250, 300 and 400 all clamp back to 240, predictably
        and safely. Where the device already clamps like that, a library
        rejecting the write first adds nothing but a second place for a
        legitimate write to fail. This range exists purely so a consumer
        (in particular Home Assistant's `number` platform) can build a
        correctly-bounded, correctly-grained slider. The device is the
        enforcement point. Do not reintroduce a bounds check here on the
        assumption one was lost by accident - it was removed deliberately.
        """
        return self._range

    async def set(self, value: float) -> None:
        """Send `value` to the device unchanged - no bounds check against
        `range` (see that property's docstring for why).

        The await returns when the command has been queued for paced
        delivery, not when the device has acted (design §3): the
        authoritative new state arrives through the device's own
        notification and is observable via `value`.
        """
        self._send_set(value)

    # -- internal wiring surface (called by the receiver layer, never by
    # -- consumers) --------------------------------------------------------

    def _update_value(self, value: float | None) -> None:
        """Record a device-reported value (already converted to the
        control's unit by the receiver's wire callback)."""
        self._value = value

    def _update_range(self, range_: NumericRange) -> None:
        """Overwrite the advisory range with a live device report.

        The lipsync path (design §2.3): the range is seeded from the
        documented default at construction and overwritten when the
        device answers a LIPSYNCRANGE? query - the receiver's callback
        parses `!LIPSYNCRANGE(min,max)` and calls this.
        """
        self._range = range_


class SteppableControl(NumericControl):
    """A NumericControl whose model also has a step command.

    Stepping is a fixed-per-model fact, so per design §1.2 it is expressed
    as a subtype, not a `can_step` flag: a non-steppable control simply
    has no up() to call, and there is nothing left to raise or to forget
    to check. (1.x logged a warning and did nothing; an interim ruling to
    raise was superseded by this subtype - decision D4.)
    """

    def __init__(
        self,
        *,
        initial_range: NumericRange,
        send_set: Callable[[float], None],
        send_up: Callable[[], None],
        send_down: Callable[[], None],
    ) -> None:
        super().__init__(initial_range=initial_range, send_set=send_set)
        self._send_up = send_up
        self._send_down = send_down

    async def up(self) -> None:
        """Step the control up by one device-defined increment."""
        self._send_up()

    async def down(self) -> None:
        """Step the control down by one device-defined increment."""
        self._send_down()
