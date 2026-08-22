"""Tests for lyngdorf/components.py - ZoneB (this task) and Remote
(Task 4). Player has its own file (tests/player_test.py)."""

import pytest
from conftest import RecordingRio

from lyngdorf.components import Remote, ZoneB, build_remote, build_zone_b
from lyngdorf.controls import SteppableControl
from lyngdorf.exceptions import LyngdorfInvalidValueError, LyngdorfUnsupportedError
from lyngdorf.models import LyngdorfModel
from lyngdorf.remote import RemoteKey


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


class TestRemoteFactory:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_presence_and_keys_match_model_config(self, model):
        """spec §5 tier 1: `remote is None` replaces has_remote_keys;
        keys is the model's explicit per-family table, never inferred
        (#46)."""
        remote = build_remote(RecordingRio(model))
        expected_keys = model.config.available_remote_keys()
        assert (remote is not None) is bool(expected_keys)
        if remote is not None:
            assert remote.keys == expected_keys

    def test_presence_anchors(self):
        """Anchors: the whole TDAI family has no navigation hardware; MP
        and P families document full button sets; MULTIVIEW is P200-only
        within the P family (spec §9 item 4)."""
        for model in (
            LyngdorfModel.TDAI_1120,
            LyngdorfModel.TDAI_2170,
            LyngdorfModel.TDAI_2210,
            LyngdorfModel.TDAI_3400,
        ):
            assert build_remote(RecordingRio(model)) is None

        mp = build_remote(RecordingRio(LyngdorfModel.MP_60))
        p100 = build_remote(RecordingRio(LyngdorfModel.P_100))
        p200 = build_remote(RecordingRio(LyngdorfModel.P_200))
        assert mp is not None and p100 is not None and p200 is not None
        assert RemoteKey.MULTIVIEW in mp.keys
        assert RemoteKey.MULTIVIEW in p200.keys
        assert RemoteKey.MULTIVIEW not in p100.keys


class TestRemoteSend:
    def _remote(self, rio: RecordingRio) -> Remote:
        remote = build_remote(rio)
        assert remote is not None
        return remote

    @pytest.mark.asyncio
    async def test_strings_resolve_case_insensitively_and_enums_pass(self):
        rio = RecordingRio(LyngdorfModel.MP_60)
        remote = self._remote(rio)
        await remote.send(["up", "UP", "Up", RemoteKey.UP])
        assert rio.writes == ["DIRU", "DIRU", "DIRU", "DIRU"]

    @pytest.mark.asyncio
    async def test_whole_batch_validates_before_anything_is_sent(self):
        """A typo partway through a batch must raise BEFORE the first
        command reaches the device - never leave it half-navigated
        through a menu (1.x contract, relocated verbatim)."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        remote = self._remote(rio)
        with pytest.raises(LyngdorfUnsupportedError) as excinfo:
            await remote.send(["up", "down", "nope"])
        assert rio.writes == []
        assert "'nope'" in str(excinfo.value)
        assert "mp-60" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_num_repeats_repeats_the_whole_sequence_as_a_block(self):
        """123123, not 112233 (1.x contract; matches how broadlink and
        harmony interpret num_repeats). Do not swap the loop nesting."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        remote = self._remote(rio)
        await remote.send(["1", "2", "3"], num_repeats=2)
        assert rio.writes == [
            "NUM(1)",
            "NUM(2)",
            "NUM(3)",
            "NUM(1)",
            "NUM(2)",
            "NUM(3)",
        ]

    @pytest.mark.asyncio
    async def test_key_unsupported_on_this_model_raises(self):
        """MULTIVIEW on a P100 must raise even though the key exists on a
        sibling model - validation is against THIS model's table."""
        p100 = self._remote(RecordingRio(LyngdorfModel.P_100))
        with pytest.raises(LyngdorfUnsupportedError):
            await p100.send([RemoteKey.MULTIVIEW])
        p200_rio = RecordingRio(LyngdorfModel.P_200)
        await self._remote(p200_rio).send([RemoteKey.MULTIVIEW])
        assert p200_rio.writes == ["MULTIVIEW"]

    @pytest.mark.asyncio
    async def test_press_delegates_to_send(self):
        """press() delegates to send() so the two can never validate or
        dispatch differently (1.x contract)."""
        rio = RecordingRio(LyngdorfModel.MP_60)
        remote = self._remote(rio)
        await remote.press(RemoteKey.MENU)
        assert rio.writes == ["MENU"]
        with pytest.raises(LyngdorfUnsupportedError):
            await self._remote(RecordingRio(LyngdorfModel.P_100)).press(
                RemoteKey.MULTIVIEW
            )
