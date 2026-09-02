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

from collections.abc import Callable, Mapping
from enum import StrEnum

from .models import NumericRange
from .rio import RioClient


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
        control's unit by the receiver's wire callback).

        Deliberately does NOT coerce the value to agree with `range.step`.
        That was tried and scoped back out; see the note on
        `LyngdorfReceiver._lipsync_callback` and issue #56 for why, so
        the argument is not reconstructed from scratch.
        """
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


class VolumeControl(SteppableControl):
    """The main-zone volume on a model that reports a MAXVOL ceiling.

    Capability as a subtype, the same idiom `SteppableControl` uses for
    stepping (design §1.2, decision D4): the six MP and P models report
    `!MAXVOL` and get this type; the four TDAI models document no such
    command and get a plain SteppableControl, with no attribute to ask
    about.

    That is the whole point, and it fixes issue #54. `receiver.max_volume`
    was `None` for two different reasons - the model has no MAXVOL, or it
    has one and has not answered yet - and nothing in the type
    distinguished them, so `max_volume is None` read as a capability
    check and was wrong on an MP that simply had not replied. Here the
    capability question is `isinstance(receiver.volume, VolumeControl)`,
    answerable at construction, and `maximum_volume` is left meaning only
    "not reported yet" - the same reading semantics as `value`.
    """

    def __init__(
        self,
        *,
        initial_range: NumericRange,
        send_set: Callable[[float], None],
        send_up: Callable[[], None],
        send_down: Callable[[], None],
    ) -> None:
        super().__init__(
            initial_range=initial_range,
            send_set=send_set,
            send_up=send_up,
            send_down=send_down,
        )
        self._maximum_volume: float | None = None

    @property
    def maximum_volume(self) -> float | None:
        """The device's current MAXVOL setting in dB, or None until it
        reports one. None NEVER means "this model has no ceiling" - a
        model without the feature has no VolumeControl at all.

        A user-settable safety ceiling, changeable from the front panel
        or the official app, NOT the hardware's physical range - that is
        `range`. Do not treat it as a fixed slider maximum; subscribe to
        change notifications rather than caching it once.

        Read as-is and never validated, and a live ceiling that clamps
        writes rather than a marker: on a P200 at `!MAXVOL(0)`, every set
        from `!VOL(1)` to `!VOL(300)` read back `!VOL(0)`. 0.0 dB is a
        real value there, not "off" or "unset".

        Read-only, by the device's constraint rather than ours - the same
        P200 ignored `!MAXVOL(300)` and still answered `!MAXVOL(0)`. The
        ceiling changes only in the device's setup menu, so there is no
        setter here and adding one would write a command that is
        discarded. It is also a safety setting, the same reason `!DEFVOL`
        is not modelled at all (see const.py).

        Main zone only: Zone B's ceiling has no query in the protocol,
        which is why `zone_b.volume` is a plain SteppableControl.
        """
        return self._maximum_volume

    def _update_maximum_volume(self, value: float | None) -> None:
        self._maximum_volume = value


# ---------------------------------------------------------------------------
# Per-model factories. The receiver layer (WP4) calls these once at
# construction; capability is thereby structural (design §5): a model
# without a control never has the object at all.
# ---------------------------------------------------------------------------


def build_volume(rio: RioClient) -> SteppableControl:
    """The main-zone volume control for `rio`'s model.

    SteppableControl statically, not per-model: every supported model
    steps volume - MP/P via the VOL+/VOL- suffix convention, the TDAI
    family via its literal VOLUP/VOLDN tokens (design §2.3, pinned by
    test_every_model_steps_volume). If a future model cannot step volume,
    that is a real capability change and this return type must change
    with it.
    """
    volume_range = rio._model.config.volume_range
    assert volume_range is not None, "every supported model documents a volume range"
    from .const import Msg

    kind = (
        VolumeControl
        if Msg.MAX_VOLUME in rio._model.config.messages
        else SteppableControl
    )
    return kind(
        initial_range=volume_range,
        send_set=rio.volume,
        send_up=rio.volume_up,
        send_down=rio.volume_down,
    )


def build_trims(rio: RioClient) -> Mapping[Trim, NumericControl]:
    """The trim mapping for `rio`'s model - only the bands the model has
    appear as keys (design §5: `Trim.CENTER in trims` replaces 1.x's
    `trim_centre_range is None`).

    Capability is keyed off the ModelConfig range fields - the same
    source 1.x's `_require_capability` gated on (a band exists iff its
    documented range does). Bass/treble steppability comes from the
    family-overridden `has_*_trim_step()` predicates; the discrete
    channel trims are MP-only and always step where they exist at all,
    so they are unconditionally SteppableControl.

    The mapping is genuinely mixed (MP trims all step, TDAI bass/treble
    do not), so consumers hold it base-typed and narrow with
    `isinstance(ctl, SteppableControl)` - design §2.3/§6.3.
    """
    config = rio._model.config
    trims: dict[Trim, NumericControl] = {}

    if (bass_range := config.trim_bass_range) is not None:
        if config.has_bass_trim_step():
            trims[Trim.BASS] = SteppableControl(
                initial_range=bass_range,
                send_set=rio.change_trim_bass,
                send_up=rio.trim_bass_up,
                send_down=rio.trim_bass_down,
            )
        else:
            trims[Trim.BASS] = NumericControl(
                initial_range=bass_range, send_set=rio.change_trim_bass
            )

    if (treble_range := config.trim_treble_range) is not None:
        if config.has_treble_trim_step():
            trims[Trim.TREBLE] = SteppableControl(
                initial_range=treble_range,
                send_set=rio.change_trim_treble,
                send_up=rio.trim_treble_up,
                send_down=rio.trim_treble_down,
            )
        else:
            trims[Trim.TREBLE] = NumericControl(
                initial_range=treble_range, send_set=rio.change_trim_treble
            )

    channel_trims: tuple[
        tuple[
            Trim,
            NumericRange | None,
            Callable[[float], None],
            Callable[[], None],
            Callable[[], None],
        ],
        ...,
    ] = (
        (
            Trim.CENTER,
            config.trim_centre_range,
            rio.change_trim_centre,
            rio.trim_centre_up,
            rio.trim_centre_down,
        ),
        (
            Trim.HEIGHT,
            config.trim_height_range,
            rio.change_trim_height,
            rio.trim_height_up,
            rio.trim_height_down,
        ),
        (
            Trim.LFE,
            config.trim_lfe_range,
            rio.change_trim_lfe,
            rio.trim_lfe_up,
            rio.trim_lfe_down,
        ),
        (
            Trim.SURROUND,
            config.trim_surround_range,
            rio.change_trim_surround,
            rio.trim_surround_up,
            rio.trim_surround_down,
        ),
    )
    for band, band_range, send_set, send_up, send_down in channel_trims:
        if band_range is not None:
            trims[band] = SteppableControl(
                initial_range=band_range,
                send_set=send_set,
                send_up=send_up,
                send_down=send_down,
            )

    return trims


def build_lipsync(rio: RioClient) -> NumericControl | None:
    """The lipsync control, or None on a model with no lip sync control
    at all (the whole TDAI family - design §2.2).

    The range is seeded from the documented default
    (ModelConfig.lipsync_default_range); the receiver layer overwrites it
    via `_update_range` when the device answers a LIPSYNCRANGE? query
    (queried at startup on the MP and P families). Base NumericControl -
    no model steps lipsync.
    """
    default_range = rio._model.config.lipsync_default_range
    if default_range is None:
        return None

    def send(value: float) -> None:
        rio.change_lipsync(int(value))

    return NumericControl(initial_range=default_range, send_set=send)
