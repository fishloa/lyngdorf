"""Tests for lyngdorf/controls.py - the NumericControl/SteppableControl
hierarchy and the Trim enum (spec §2.3), plus (from Task 2 onward) the
per-model factories."""

import pytest
from conftest import RecordingRio

from lyngdorf.controls import (
    NumericControl,
    SteppableControl,
    Trim,
    VolumeControl,
    build_lipsync,
    build_trims,
    build_volume,
)
from lyngdorf.models import LyngdorfModel, NumericRange
from lyngdorf.receiver import LyngdorfReceiver

TEST_RANGE = NumericRange(min=-12.0, max=12.0, step=0.1)


class TestTrimEnum:
    def test_members_and_values(self):
        assert {member.value for member in Trim} == {
            "bass",
            "treble",
            "center",
            "height",
            "lfe",
            "surround",
        }

    def test_center_is_american_spelling(self):
        """Maintainer-ruled (spec §2.3): enum values are permanent public
        API strings; American matches HA core AND the device's own
        TRIMCENTER wire command (models/mp_series.py:125). Internal
        identifiers (Msg.TRIM_CENTRE etc.) keep the British spelling."""
        assert Trim.CENTER.value == "center"
        assert "centre" not in {member.value for member in Trim}


class TestNumericControl:
    def test_value_none_until_first_report_then_tracks_updates(self):
        control = NumericControl(initial_range=TEST_RANGE, send_set=lambda v: None)
        assert control.value is None
        control._update_value(-2.5)
        assert control.value == -2.5
        control._update_value(None)  # power-off style clear
        assert control.value is None

    def test_range_reflects_live_updates(self):
        control = NumericControl(initial_range=TEST_RANGE, send_set=lambda v: None)
        assert control.range == TEST_RANGE
        live = NumericRange(min=0.0, max=450.0, step=1.0)
        control._update_range(live)
        assert control.range == live

    @pytest.mark.asyncio
    async def test_set_sends_the_exact_value_unchanged_and_unchecked(self):
        """Issues #37/#41/#42/#43: ranges are ADVISORY. set() sends the
        value unchanged with no bounds check - the device is the
        enforcement point (a real MP-60 clamps 250/300/400 -> 240
        predictably and safely; see Receiver.volume_range's 1.x docstring,
        relocated onto NumericControl.range). The bounds check was removed
        DELIBERATELY. If this test ever fails because set() started
        raising, clamping or warning, the fix is to delete that check -
        never to update this test."""
        sent: list[float] = []
        control = NumericControl(initial_range=TEST_RANGE, send_set=sent.append)
        await control.set(999.0)  # far outside the advisory -12..+12
        assert sent == [999.0]

    def test_base_control_has_no_step_members_and_no_can_step(self):
        """spec §1.2/D4: stepping is a subtype, never a flag. A control
        that cannot step has no up() to call and nothing to consult."""
        control = NumericControl(initial_range=TEST_RANGE, send_set=lambda v: None)
        assert not hasattr(control, "up")
        assert not hasattr(control, "down")
        assert not hasattr(control, "can_step")
        assert not hasattr(SteppableControl, "can_step")


class TestSteppableControl:
    def test_is_a_numeric_control(self):
        assert issubclass(SteppableControl, NumericControl)

    @pytest.mark.asyncio
    async def test_up_down_send_and_set_still_works(self):
        calls: list[str] = []
        control = SteppableControl(
            initial_range=TEST_RANGE,
            send_set=lambda v: calls.append(f"set:{v}"),
            send_up=lambda: calls.append("up"),
            send_down=lambda: calls.append("down"),
        )
        await control.up()
        await control.down()
        await control.set(-3.0)
        assert calls == ["up", "down", "set:-3.0"]


# Trim band -> the ModelConfig range field that gates it. The American
# public key deliberately maps to the British-spelled internal field
# (spec §2.3's scope-of-rename ruling).
TRIM_RANGE_FIELDS: dict[Trim, str] = {
    Trim.BASS: "trim_bass_range",
    Trim.TREBLE: "trim_treble_range",
    Trim.CENTER: "trim_centre_range",
    Trim.HEIGHT: "trim_height_range",
    Trim.LFE: "trim_lfe_range",
    Trim.SURROUND: "trim_surround_range",
}


class TestVolumeFactory:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_every_model_steps_volume(self, model):
        """spec §2.3's static-typing claim, VERIFIED against ModelConfig
        rather than trusted: `volume` is annotated SteppableControl
        because every supported model has volume step commands (MP/P via
        VOL+/VOL-, TDAI via literal VOLUP/VOLDN). If this fails for a
        future model, that is a real capability change and the annotation
        must change with it - do not paper over it here."""
        assert model.config.volume_up_command()
        assert model.config.volume_down_command()
        control = build_volume(RecordingRio(model))
        assert isinstance(control, SteppableControl)

    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_volume_range_comes_from_model_config(self, model):
        control = build_volume(RecordingRio(model))
        assert control.range == model.config.volume_range

    def test_volume_range_anchors(self):
        """Anchors transcribed from the vendor manuals (docs/), so the
        parametrised test above cannot be satisfied by a config bug: the
        TDAI ceiling really is lower (spec §9 item 4)."""
        assert build_volume(RecordingRio(LyngdorfModel.MP_60)).range.max == 24.0
        assert build_volume(RecordingRio(LyngdorfModel.TDAI_3400)).range.max == 12.0

    @pytest.mark.asyncio
    async def test_wire_format_mp(self):
        rio = RecordingRio(LyngdorfModel.MP_60)
        volume = build_volume(rio)
        await volume.set(-25.0)
        await volume.up()
        await volume.down()
        assert rio.writes == ["VOL(-250)", "VOL+", "VOL-"]

    @pytest.mark.asyncio
    async def test_wire_format_tdai_uses_literal_step_tokens(self):
        """TDAI has no +/- suffix convention (spec §9 item 1's per-model
        token derivation): distinct literal VOLUP/VOLDN tokens."""
        rio = RecordingRio(LyngdorfModel.TDAI_3400)
        volume = build_volume(rio)
        await volume.set(-25.0)
        await volume.up()
        await volume.down()
        assert rio.writes == ["VOL(-250)", "VOLUP", "VOLDN"]

    @pytest.mark.asyncio
    async def test_out_of_range_volume_reaches_the_wire_unchanged(self):
        """The advisory-range rule (#37/#41/#42/#43) proven end to end
        through the real writer: 999.0 dB is far outside every model's
        range and must still be encoded and sent. The device clamps; the
        library does not. Do not reintroduce a bounds check."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        await build_volume(rio).set(999.0)
        assert rio.writes == ["VOL(9990)"]


class TestTrimsFactory:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_bands_match_model_config(self, model):
        """The per-model matrix, regenerated from ModelConfig (spec §12
        WP3): only the bands the model documents a range for appear."""
        trims = build_trims(RecordingRio(model))
        expected = {
            band
            for band, field_name in TRIM_RANGE_FIELDS.items()
            if getattr(model.config, field_name) is not None
        }
        assert set(trims) == expected

    def test_band_anchors_one_model_per_family(self):
        """Non-tautological anchors (the parametrised test proves
        factory==config; these prove config==reality, from the manuals):
        MP has all six bands, TDAI-1120/3400/2210 bass+treble only,
        TDAI-2170 none, the P series none at all."""
        assert set(build_trims(RecordingRio(LyngdorfModel.MP_60))) == set(Trim)
        assert set(build_trims(RecordingRio(LyngdorfModel.TDAI_3400))) == {
            Trim.BASS,
            Trim.TREBLE,
        }
        assert set(build_trims(RecordingRio(LyngdorfModel.TDAI_2170))) == set()
        assert set(build_trims(RecordingRio(LyngdorfModel.P_100))) == set()

    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_stepping_matches_model_config(self, model):
        """Steppability matrix, regenerated from config: bass/treble step
        where the family's config says so (MP yes, TDAI no - the
        TDAIModelConfig override); channel trims are MP-only and always
        step. isinstance() is exactly the consumer narrowing from §6.3."""
        for band, control in build_trims(RecordingRio(model)).items():
            if band is Trim.BASS:
                expected = model.config.has_bass_trim_step()
            elif band is Trim.TREBLE:
                expected = model.config.has_treble_trim_step()
            else:
                expected = True
            assert isinstance(control, SteppableControl) is expected

    def test_tdai_bass_cannot_step_structurally(self):
        """1.x warned-and-ignored a TDAI bass step; 2.0 makes it
        unrepresentable (D4): the control is a plain NumericControl with
        no up() at all."""
        bass = build_trims(RecordingRio(LyngdorfModel.TDAI_3400))[Trim.BASS]
        assert not isinstance(bass, SteppableControl)
        assert not hasattr(bass, "up")

    @pytest.mark.asyncio
    async def test_trim_scale_mp_tenths_vs_tdai_whole_db(self):
        """#41, pinned end to end: +3 dB is TRIMBASS(30) on MP (tenths)
        but BASS(3) on TDAI (whole dB) - the scale is wired in by the
        factory and never surfaces to the caller (spec §2.3)."""
        mp = RecordingRio(LyngdorfModel.MP_60)
        await build_trims(mp)[Trim.BASS].set(3.0)
        assert mp.writes == ["TRIMBASS(30)"]

        tdai = RecordingRio(LyngdorfModel.TDAI_3400)
        await build_trims(tdai)[Trim.BASS].set(3.0)
        assert tdai.writes == ["BASS(3)"]

    @pytest.mark.asyncio
    async def test_treble_set_and_step_use_trimtreb_not_trimtreble(self):
        """The TRIMTREB/TRIMTREBLE query-vs-reply mismatch (spec §9
        item 4, verified on real hardware): the set/step command is
        TRIMTREB; TRIMTREBLE is only ever a reply key."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        treble = build_trims(rio)[Trim.TREBLE]
        await treble.set(1.5)
        assert isinstance(treble, SteppableControl)
        await treble.up()
        assert rio.writes == ["TRIMTREB(15)", "TRIMTREB+"]

    @pytest.mark.asyncio
    async def test_channel_trim_wire_format_and_step(self):
        rio = RecordingRio(LyngdorfModel.MP_60)
        trims = build_trims(rio)
        center = trims[Trim.CENTER]
        await center.set(0.5)
        assert isinstance(center, SteppableControl)
        await center.down()
        assert rio.writes == ["TRIMCENTER(5)", "TRIMCENTER-"]

    @pytest.mark.asyncio
    async def test_out_of_range_trim_reaches_the_wire_unchanged(self):
        """Advisory ranges again, on the trim path (#41's model): 99 dB
        against a documented -12..+12 range still encodes and sends."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        await build_trims(rio)[Trim.BASS].set(99.0)
        assert rio.writes == ["TRIMBASS(990)"]

    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_ranges_come_from_model_config(self, model):
        trims = build_trims(RecordingRio(model))
        for band, control in trims.items():
            assert control.range == getattr(model.config, TRIM_RANGE_FIELDS[band])


class TestLipsyncFactory:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_presence_matches_model_config(self, model):
        control = build_lipsync(RecordingRio(model))
        assert (control is not None) == (model.config.lipsync_default_range is not None)

    def test_absent_on_the_whole_tdai_family(self):
        """Anchor: spec §2.2 - lipsync is None on the whole TDAI family."""
        for model in (
            LyngdorfModel.TDAI_1120,
            LyngdorfModel.TDAI_2170,
            LyngdorfModel.TDAI_2210,
            LyngdorfModel.TDAI_3400,
        ):
            assert build_lipsync(RecordingRio(model)) is None
        assert build_lipsync(RecordingRio(LyngdorfModel.MP_60)) is not None
        assert build_lipsync(RecordingRio(LyngdorfModel.P_100)) is not None

    def test_range_is_live_not_frozen_at_the_default(self):
        """spec §2.3: lipsync's range is seeded from the documented
        default and OVERWRITTEN when the device answers LIPSYNCRANGE.
        This pins the control side of that contract - the range genuinely
        updates rather than staying at the default. (WP4 wires the
        !LIPSYNCRANGE(min,max) reply callback to _update_range; the
        end-to-end wire path is covered by the ported wiring tests
        there.)"""
        lipsync = build_lipsync(RecordingRio(LyngdorfModel.MP_60))
        assert lipsync is not None
        assert lipsync.range == NumericRange(min=0.0, max=500.0, step=1.0)
        lipsync._update_range(NumericRange(min=0.0, max=450.0, step=1.0))
        assert lipsync.range == NumericRange(min=0.0, max=450.0, step=1.0)

    @pytest.mark.asyncio
    async def test_wire_format_is_integer_milliseconds(self):
        """set() takes float (one shape per concept, §2.3) but the wire
        format stays 1.x's integer - LIPSYNC(20), never LIPSYNC(20.0)."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        lipsync = build_lipsync(rio)
        assert lipsync is not None
        await lipsync.set(20)
        await lipsync.set(35.0)
        assert rio.writes == ["LIPSYNC(20)", "LIPSYNC(35)"]

    def test_lipsync_is_not_steppable(self):
        """spec §2.3: no model steps lipsync - base type only."""
        lipsync = build_lipsync(RecordingRio(LyngdorfModel.MP_60))
        assert lipsync is not None
        assert not isinstance(lipsync, SteppableControl)


class TestLipsyncIsIntegral:
    """Issue #56, and the SCOPE of it, which was decided twice.

    A general coercion was implemented first: snap every value to its
    control's `range.step` and store an int where that step is integral.
    Correct, and it also caught bass/treble on the TDAI family, whose
    step is 1.0 where the MP family's is 0.1.

    Scoped back to lipsync alone. Both versions were correct, so
    correctness was not the deciding axis - cost was. Restoring lipsync
    nets ZERO user-visible change across the upgrade (`int` in 1.10,
    float in 1.11/2.0.1, `int` again now). Coercing the TDAI trims would
    net ONE, newly introduced, for owners who never had a defect:
    `convert_decibel` has returned a float on every path in every
    version, so a template comparing bass to "3.0" would break so that a
    value could stop contradicting a step nobody reads.

    The general form is the right end state and is recorded on #56 as
    consciously scoped out - to be done in a release where it is the
    announced change rather than a side effect of a lipsync fix. These
    tests pin the narrow behaviour so that reinstating it is a decision
    rather than an accident.
    """

    def test_lipsync_is_an_int_restoring_1x_behaviour(self):
        """1.10 did `self._lipsync = int(param1)` and typed the property
        `int | None`. 2.0 made it a float, which changed the state STRING
        a consumer renders - `50` to `50.0` - breaking recorded history
        and templates comparing against "50"."""
        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        r._register_callbacks()
        r._lipsync_callback("50", "")
        assert r._lipsync is not None
        assert r._lipsync.value == 50
        assert isinstance(r._lipsync.value, int)
        assert str(r._lipsync.value) == "50", "the state string is the point"

    def test_lipsync_survives_a_fractional_wire_value(self):
        """1.x used `int(param1)`, which raises ValueError on "50.0".
        This path uses `round(float(...))`, so a device answering in that
        form still yields an int rather than crashing the callback."""
        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        r._register_callbacks()
        r._lipsync_callback("50.0", "")
        assert r._lipsync is not None
        assert r._lipsync.value == 50
        assert isinstance(r._lipsync.value, int)

    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_nothing_else_is_coerced(self, model):
        """The scoping, pinned over every control on every model rather
        than over the TDAI trims by name.

        TDAI bass/treble are the ones that would move under the general
        form - step 1.0 against the MP family's 0.1 - and they must not.
        Written as a population because the previous version of this
        file asserted the opposite, and a by-name test would leave the
        other nine models unexamined either way.
        """
        r = LyngdorfReceiver("127.0.0.1", model)
        controls = [("volume", r.volume)]
        if r.zone_b is not None:
            controls.append(("zone_b.volume", r.zone_b.volume))
        controls += [(f"trims[{t.value}]", c) for t, c in r.trims.items()]
        for name, ctl in controls:
            ctl._update_value(3.0)
            assert isinstance(ctl.value, float), (
                f"{model.name} {name} was coerced to "
                f"{type(ctl.value).__name__}; only lipsync is integral"
            )

    def test_none_survives(self):
        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        r.volume._update_value(None)
        assert r.volume.value is None


class TestMaximumVolumeIsStructural:
    """Issue #54, and the last runtime-varying None on the receiver.

    `receiver.max_volume` was None for two different reasons - the model
    has no MAXVOL command, or it has one and has not answered yet - with
    nothing in the type to tell them apart. So `max_volume is None` read
    as a capability check and was wrong on an MP that had simply not
    replied yet.
    """

    def test_no_receiver_property_has_a_runtime_varying_none(self):
        """The done-when from #54, and deliberately asked of the whole
        surface rather than of max_volume by name: the defect was never
        that one annotation was wrong, it was that nothing asked the
        question of the receiver as a whole.

        A property whose None flips once the device speaks is a
        capability check that lies. Every remaining Optional on the
        receiver must be structural - fixed at construction.
        """
        import warnings as _w

        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        r._register_callbacks()
        with _w.catch_warnings():
            _w.simplefilter("ignore", DeprecationWarning)
            before = {
                n: getattr(r, n) is None
                for n in dir(type(r))
                if not n.startswith("_")
                and isinstance(getattr(type(r), n, None), property)
            }
            # everything the device can report
            r._max_volume_callback("-200", "")
            r._lipsync_callback("50", "")
            r._volume_callback("-400", "")
            after = {n: getattr(r, n) is None for n in before}
        flipped = sorted(n for n in before if before[n] and not after[n])
        assert flipped == ["max_volume"], (
            f"properties whose None varies at runtime: {flipped}. Only the "
            f"deprecated max_volume may, and it goes in 3.0."
        )

    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_the_capability_is_the_type(self, model):
        r = LyngdorfReceiver("127.0.0.1", model)
        from lyngdorf.const import Msg

        expected = Msg.MAX_VOLUME in model.config.messages
        assert isinstance(r.volume, VolumeControl) is expected
        assert hasattr(r.volume, "maximum_volume") is expected

    def test_none_only_ever_means_not_reported_yet(self):
        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        r._register_callbacks()
        assert isinstance(r.volume, VolumeControl)
        assert r.volume.maximum_volume is None, "present, nothing reported"
        r._max_volume_callback("-200", "")
        assert r.volume.maximum_volume == -20.0

    def test_zero_is_a_real_ceiling_not_a_sentinel(self):
        """A real MP-60 on firmware 5.4.2 answered !MAXVOL(0), outside
        the range its own manual documents. Surfaced as-is, never
        validated."""
        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        r._register_callbacks()
        r._max_volume_callback("0", "")
        assert isinstance(r.volume, VolumeControl)
        assert r.volume.maximum_volume == 0.0

    def test_the_old_accessor_still_works_and_warns(self):
        """One release of overlap, so a consumer can move its pin and its
        code in separate commits."""
        r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
        r._register_callbacks()
        r._max_volume_callback("-200", "")
        with pytest.warns(DeprecationWarning, match="3.0"):
            assert r.max_volume == -20.0
