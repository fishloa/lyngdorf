"""Tests for lyngdorf/controls.py - the NumericControl/SteppableControl
hierarchy and the Trim enum (spec §2.3), plus (from Task 2 onward) the
per-model factories."""

import pytest

from lyngdorf.controls import NumericControl, SteppableControl, Trim
from lyngdorf.models import NumericRange

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
