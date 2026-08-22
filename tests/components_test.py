"""Tests for lyngdorf/components.py - ZoneB (this task) and Remote
(Task 4). Player has its own file (tests/player_test.py)."""

import pytest
from conftest import RecordingRio

from lyngdorf.components import ZoneB, build_zone_b
from lyngdorf.const import LyngdorfModel
from lyngdorf.controls import SteppableControl
from lyngdorf.exceptions import LyngdorfInvalidValueError


class TestZoneBFactory:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_presence_matches_model_config(self, model):
        """spec §5 tier 1: `zone_b is None` replaces has_zone_b_feature()."""
        assert (build_zone_b(RecordingRio(model)) is not None) is (
            model.config.has_zone_b
        )

    def test_presence_anchors(self):
        """Anchors: Zone B exists on MP and P families only - the whole
        TDAI family maps no Zone B command at all (spec §2.4)."""
        assert build_zone_b(RecordingRio(LyngdorfModel.MP_60)) is not None
        assert build_zone_b(RecordingRio(LyngdorfModel.P_200)) is not None
        for model in (
            LyngdorfModel.TDAI_1120,
            LyngdorfModel.TDAI_2170,
            LyngdorfModel.TDAI_2210,
            LyngdorfModel.TDAI_3400,
        ):
            assert build_zone_b(RecordingRio(model)) is None

    def test_volume_is_steppable_with_the_documented_range(self):
        """spec §2.3: zone_b.volume is SteppableControl statically - Zone
        B exists only on MP/P, which step ZVOL."""
        zone_b = build_zone_b(RecordingRio(LyngdorfModel.MP_60))
        assert zone_b is not None
        assert isinstance(zone_b.volume, SteppableControl)
        assert zone_b.volume.range == LyngdorfModel.MP_60.config.zone_b_volume_range


class TestZoneB:
    def _zone_b(self, rio: RecordingRio) -> ZoneB:
        zone_b = build_zone_b(rio)
        assert zone_b is not None
        return zone_b

    @pytest.mark.asyncio
    async def test_wire_formats(self):
        rio = RecordingRio(LyngdorfModel.MP_60)
        zone_b = self._zone_b(rio)
        await zone_b.set_power(True)
        await zone_b.set_power(False)
        await zone_b.set_muted(True)
        await zone_b.set_muted(False)
        await zone_b.volume.set(-40.0)
        await zone_b.volume.up()
        await zone_b.volume.down()
        assert rio.writes == [
            "POWERONZONE2",
            "POWEROFFZONE2",
            "ZMUTEON",
            "ZMUTEOFF",
            "ZVOL(-400)",
            "ZVOL+",
            "ZVOL-",
        ]

    @pytest.mark.asyncio
    async def test_set_source_validates_by_name_and_sends_the_index(self):
        """Unchanged 1.x semantics: names are validated against the
        device-enumerated list; the wire carries the index; an unknown
        name raises before anything is sent."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        zone_b = self._zone_b(rio)
        zone_b._sources.count_callback("2", "")
        zone_b._sources.add(0, "Apple TV")
        zone_b._sources.add(1, "Wonk")
        assert zone_b.sources == ["Apple TV", "Wonk"]

        await zone_b.set_source("Wonk")
        assert rio.writes == ["ZSRC(1)"]

        with pytest.raises(LyngdorfInvalidValueError):
            await zone_b.set_source("Nope")
        assert rio.writes == ["ZSRC(1)"]  # nothing extra was sent

    def test_state_is_none_until_updated_then_tracks(self):
        zone_b = self._zone_b(RecordingRio(LyngdorfModel.MP_60))
        assert zone_b.power_on is None
        assert zone_b.muted is None
        assert zone_b.source is None
        assert zone_b.audio_input is None
        assert zone_b.streaming_source is None
        assert zone_b.sources == []

        zone_b._update_power(True)
        zone_b._update_muted(False)
        zone_b._update_source("Apple TV")
        zone_b._update_audio_input("HDMI 1")
        zone_b._update_streaming_source("AirPlay")
        assert zone_b.power_on is True
        assert zone_b.muted is False
        assert zone_b.source == "Apple TV"
        assert zone_b.audio_input == "HDMI 1"
        assert zone_b.streaming_source == "AirPlay"

    def test_zone_b_has_no_sound_mode_and_no_trims(self):
        """spec §2.4: Zone B has exactly what the hardware has - no
        sound_mode, no trims - so nothing on it can raise 'unsupported'."""
        zone_b = self._zone_b(RecordingRio(LyngdorfModel.MP_60))
        assert not hasattr(zone_b, "sound_mode")
        assert not hasattr(zone_b, "trims")
