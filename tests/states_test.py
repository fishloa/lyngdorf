"""Tests for `lyngdorf.states`, importable with no HTTP layer involved.

No device or fake server needed: these are pure value-type tests.
"""

import pytest

from lyngdorf.states import Control, PlaybackState, PlayMode, Repeat


class TestPlayModeRoundTrip:
    """All six wire values round-trip through `from_wire`/`wire`."""

    WIRE_VALUES = [
        "normal",
        "shuffle",
        "repeatOne",
        "repeatAll",
        "shuffleRepeatOne",
        "shuffleRepeatAll",
    ]

    @pytest.mark.parametrize("value", WIRE_VALUES)
    def test_round_trips(self, value):
        mode = PlayMode.from_wire(value)
        assert mode is not None
        assert mode.wire == value

    def test_grid_mapping(self):
        """The six values are a 2x3 grid of (shuffle, repeat), not six
        independent states."""
        assert PlayMode.from_wire("normal") == PlayMode(False, Repeat.OFF)
        assert PlayMode.from_wire("repeatOne") == PlayMode(False, Repeat.ONE)
        assert PlayMode.from_wire("repeatAll") == PlayMode(False, Repeat.ALL)
        assert PlayMode.from_wire("shuffle") == PlayMode(True, Repeat.OFF)
        assert PlayMode.from_wire("shuffleRepeatOne") == PlayMode(True, Repeat.ONE)
        assert PlayMode.from_wire("shuffleRepeatAll") == PlayMode(True, Repeat.ALL)

    def test_unrecognised_value_returns_none(self):
        """The device will happily store and read back `bogusMode` - this
        must not raise, and must not be mistaken for a known mode."""
        assert PlayMode.from_wire("bogusMode") is None

    def test_empty_string_returns_none(self):
        assert PlayMode.from_wire("") is None

    def test_defaults_to_normal(self):
        assert PlayMode() == PlayMode(shuffle=False, repeat=Repeat.OFF)
        assert PlayMode().wire == "normal"

    def test_frozen_and_hashable(self):
        mode = PlayMode(shuffle=True, repeat=Repeat.ALL)
        with pytest.raises(AttributeError):
            mode.shuffle = False  # type: ignore[misc]
        # Hashable, so it can live in a frozenset/dict key.
        assert {mode, PlayMode(True, Repeat.ALL)} == {mode}

    def test_equality_by_value(self):
        assert PlayMode(True, Repeat.ONE) == PlayMode(shuffle=True, repeat=Repeat.ONE)
        assert PlayMode(True, Repeat.ONE) != PlayMode(False, Repeat.ONE)


class TestControlLeniency:
    """The device is the source of truth for what controls exist, and it
    changes under us - an unrecognised control must not raise."""

    def test_known_member(self):
        assert Control.PAUSE == "pause"

    def test_next_track_has_trailing_underscore(self):
        """The device really does spell it this way - nothing about the
        name gives a caller any way to guess that."""
        assert Control.NEXT_TRACK == "next_"

    def test_unknown_value_does_not_raise(self):
        control = Control("someFutureControl")
        assert control == "someFutureControl"

    def test_unknown_value_is_a_control_instance(self):
        assert isinstance(Control("someFutureControl"), Control)

    def test_non_string_value_raises(self):
        """`_missing_` only copes with strings - the device's wire format.
        A non-string is a caller error, not an unrecognised control, and
        must raise like a normal enum rather than fabricate a member."""
        with pytest.raises(ValueError):
            Control(123)


class TestPlaybackStateLeniency:
    def test_known_member(self):
        assert PlaybackState.PLAYING == "playing"

    def test_unknown_value_does_not_raise(self):
        state = PlaybackState("buffering")
        assert state == "buffering"

    def test_unknown_value_is_a_playback_state_instance(self):
        assert isinstance(PlaybackState("buffering"), PlaybackState)

    def test_non_string_value_raises(self):
        """Same contract as `Control._missing_` - see its test above."""
        with pytest.raises(ValueError):
            PlaybackState(123)


class TestRepeatValues:
    """Chosen to match Home Assistant's RepeatMode, not the device's wire
    spelling - the device has no separate repeat field at all."""

    def test_values(self):
        assert Repeat.OFF == "off"
        assert Repeat.ONE == "one"
        assert Repeat.ALL == "all"
