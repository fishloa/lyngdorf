import asyncio
import logging
from unittest import mock

import pytest

from lyngdorf.api import LyngdorfApi, LyngdorfProtocol
from lyngdorf.const import (
    MP40_AUDIO_INPUTS,
    MP40_STREAM_TYPES,
    MP40_VIDEO_INPUTS,
    MP60_AUDIO_INPUTS,
    MP60_STREAM_TYPES,
    MP60_VIDEO_INPUTS,
    P100_VIDEO_INPUTS,
    P_AUDIO_INPUTS,
    P_VIDEO_INPUTS,
    LyngdorfModel,
    Msg,
    supported_models,
)
from lyngdorf.device import Receiver, async_create_receiver, lookup_receiver_model
from lyngdorf.exceptions import LyngdorfInvalidValueError

_LOGGER = logging.getLogger(__package__)

# =============================================================================
# Test Setup Data
# =============================================================================

FAKE_IP = "0.0.0.0"
SETUP_LAST_RESPONSE = "AUDTYPE"
SETUP_RESPONSES = [
    "!DEVICE(MP-60)",
    "!POWER(1)",
    "!POWERZONE2(0)",
    "!AUDIN(1)",
    '!AUDMODE(1)"Dolby Upmixer"',
    "!RPFOCCOUNT(2)",
    '!RPFOC(9)"Global"',
    '!RPFOC(1)"Focus 1"',
    '!RPFOC(1)"Focus 1"',
    "!RPVOICOUNT(2)",
    '!RPVOI(0)"Voice 0"',
    '!RPVOI(1)"Voice 1"',
    '!RPVOI(1)"Voice 1"',
    "!AUDMODECOUNT(10)",
    '!AUDMODE(0)"None"',
    '!AUDMODE(1)"Dolby Upmixer"',
    '!AUDMODE(2)"Neural:X"',
    '!AUDMODE(3)"Auro-3D"',
    '!AUDMODE(4)"Auro-2D"',
    '!AUDMODE(5)"Auro-Stereo"',
    '!AUDMODE(6)"Auro-Native"',
    '!AUDMODE(7)"Legacy"',
    '!AUDMODE(8)"Stereo"',
    '!AUDMODE(9)"Party"',
    '!ZSRC(0)"Apple TV"',
    "!ZSRCCOUNT(2)",
    '!ZSRC(0)"Apple TV"',
    '!ZSRC(1)"Wonk"',
    '!SRC(0)"Apple TV"',
    "!SRCCOUNT(24)",
    '!SRC(0)"Apple TV"',
    '!SRC(1)"Playstation"',
    '!SRC(2)"HDMI 3"',
    '!SRC(3)"HDMI 4"',
    '!SRC(4)"HDMI 5"',
    '!SRC(5)"TV"',
    '!SRC(6)"SPDIF 1 (Optical)"',
    '!SRC(7)"SPDIF 2 (Optical)"',
    '!SRC(8)"SPDIF 3 (Optical)"',
    '!SRC(9)"SPDIF 4 (Optical)"',
    '!SRC(10)"SPDIF 5 (AES/EBU)"',
    '!SRC(11)"SPDIF 6 (Coaxial)"',
    '!SRC(12)"SPDIF 7 (Coaxial)"',
    '!SRC(13)"SPDIF 8 (Coaxial)"',
    '!SRC(14)"USB Audio"',
    '!SRC(15)"Network Player"',
    '!SRC(16)"airable"',
    '!SRC(17)"vTuner"',
    '!SRC(18)"TIDAL"',
    '!SRC(19)"Spotify"',
    '!SRC(20)"AirPlay"',
    '!SRC(21)"Roon"',
    '!SRC(22)"DLNA"',
    '!SRC(23)"Storage"',
    "!VOL(-281)",
    "!ZVOL(-550)",
    "!VIDIN(2)",
    "!VIDTYPE(2160p50 RGB 4:4:4)",
    "!MUTEOFF",
    "!ZMUTEON",
    "!STREAMTYPE(2)",
    "!ZSTREAMTYPE(3)",
    "!AUDTYPE(PCM zero, 2.0.0)",
]


# =============================================================================
# Test Helpers
# =============================================================================


class AsyncMock(mock.MagicMock):
    """Mocking async methods compatible to python 3.7."""

    # pylint: disable=invalid-overridden-method,useless-super-delegation
    async def __call__(self, *args, **kwargs):
        """Call."""
        return super().__call__(*args, **kwargs)


# =============================================================================
# Unit Tests: Model Enums and Lookups
# =============================================================================


class TestSupportedModels:
    """Tests for the supported_models helper and lookup functions."""

    def test_supported_models_returns_all_enum_values(self):
        """Verify supported_models() returns all LyngdorfModel enum members."""
        models = supported_models()
        assert isinstance(models, list)
        assert len(models) == len(LyngdorfModel)
        for model in LyngdorfModel:
            assert model in models

    def test_supported_models_contains_mp60(self):
        """Verify MP-60 is in supported models."""
        models = supported_models()
        assert LyngdorfModel.MP_60 in models

    def test_supported_models_contains_tdai1120(self):
        """Verify TDAI-1120 is in supported models."""
        models = supported_models()
        assert LyngdorfModel.TDAI_1120 in models

    def test_supported_models_contains_mp40(self):
        """Verify MP-40 is in supported models."""
        models = supported_models()
        assert LyngdorfModel.MP_40 in models

    def test_supported_models_contains_mp50(self):
        """Verify MP-50 is in supported models."""
        models = supported_models()
        assert LyngdorfModel.MP_50 in models

    def test_supported_models_contains_tdai2170(self):
        """Verify TDAI-2170 is in supported models."""
        models = supported_models()
        assert LyngdorfModel.TDAI_2170 in models

    def test_supported_models_contains_tdai3400(self):
        """Verify TDAI-3400 is in supported models."""
        models = supported_models()
        assert LyngdorfModel.TDAI_3400 in models

    def test_lookup_receiver_model_mp60(self):
        """Test lookup_receiver_model finds MP-60."""
        model = lookup_receiver_model("mp-60")
        assert model == LyngdorfModel.MP_60

    def test_lookup_receiver_model_tdai1120(self):
        """Test lookup_receiver_model finds TDAI-1120."""
        model = lookup_receiver_model("tdai-1120")
        assert model == LyngdorfModel.TDAI_1120

    def test_lookup_receiver_model_case_insensitive(self):
        """Test lookup_receiver_model is case-insensitive."""
        assert lookup_receiver_model("MP-60") == LyngdorfModel.MP_60
        assert lookup_receiver_model("Mp-60") == LyngdorfModel.MP_60
        assert lookup_receiver_model("TDAI-1120") == LyngdorfModel.TDAI_1120

    def test_lookup_receiver_model_unknown(self):
        """Test lookup_receiver_model returns None for unknown models."""
        assert lookup_receiver_model("unknown-model") is None


class TestLyngdorfModel:
    """Tests for LyngdorfModel enum and configuration."""

    def test_lyngdorf_model_mp60_properties(self):
        """Test MP-60 model has correct properties."""
        model = LyngdorfModel.MP_60
        assert model.model_name == "mp-60"
        assert model.manufacturer == "Lyngdorf"
        assert model.name == "MP_60"
        assert len(model.setup_commands) > 0

    def test_lyngdorf_model_tdai1120_properties(self):
        """Test TDAI-1120 model has correct properties."""
        model = LyngdorfModel.TDAI_1120
        assert model.model_name == "tdai-1120"
        assert model.manufacturer == "Lyngdorf"
        assert model.name == "TDAI_1120"
        assert len(model.setup_commands) > 0

    def test_mp60_messages_complete(self):
        """Test MP60 messages mapping is complete."""
        from lyngdorf.const import MP60_MESSAGES

        assert MP60_MESSAGES[Msg.POWER] == "POWER"
        assert MP60_MESSAGES[Msg.VOLUME] == "VOL"
        assert MP60_MESSAGES[Msg.SOURCE] == "SRC"
        assert MP60_MESSAGES[Msg.AUDIO_MODE] == "AUDMODE"

    def test_tdai1120_messages_mapping(self):
        """Test TDAI-1120 messages mapping."""
        from lyngdorf.const import TDAI1120_MESSAGES

        assert TDAI1120_MESSAGES[Msg.POWER] == "PWR"
        assert TDAI1120_MESSAGES[Msg.VOLUME] == "VOL"
        assert TDAI1120_MESSAGES[Msg.SOURCE] == "SRC"

    def test_model_lookup_command(self):
        """Test lookup_command method on model enum."""
        mp60: LyngdorfModel = LyngdorfModel.MP_60
        pong_command = f"{mp60.lookup_command(Msg.PONG)}"
        assert pong_command == "PONG"

    def test_mp_series_has_zone_b_feature(self):
        """Test MP series models have Zone B support."""
        assert LyngdorfModel.MP_40.has_zone_b_feature() is True
        assert LyngdorfModel.MP_50.has_zone_b_feature() is True
        assert LyngdorfModel.MP_60.has_zone_b_feature() is True

    def test_tdai_series_no_zone_b_feature(self):
        """Test TDAI series models do not have Zone B support."""
        assert LyngdorfModel.TDAI_1120.has_zone_b_feature() is False
        assert LyngdorfModel.TDAI_2170.has_zone_b_feature() is False
        assert LyngdorfModel.TDAI_3400.has_zone_b_feature() is False

    def test_mp_series_has_video_feature(self):
        """Test MP series models have video capability."""
        assert LyngdorfModel.MP_40.has_video_feature() is True
        assert LyngdorfModel.MP_50.has_video_feature() is True
        assert LyngdorfModel.MP_60.has_video_feature() is True

    def test_tdai_series_no_video_feature(self):
        """Test TDAI series models do not have video capability."""
        assert LyngdorfModel.TDAI_1120.has_video_feature() is False
        assert LyngdorfModel.TDAI_2170.has_video_feature() is False
        assert LyngdorfModel.TDAI_3400.has_video_feature() is False

    def test_mp_series_has_surround_feature(self):
        """Test MP series models have surround/multichannel capability."""
        assert LyngdorfModel.MP_40.has_surround_feature() is True
        assert LyngdorfModel.MP_50.has_surround_feature() is True
        assert LyngdorfModel.MP_60.has_surround_feature() is True

    def test_tdai_series_no_surround_feature(self):
        """Test TDAI series models do not have surround/multichannel capability."""
        assert LyngdorfModel.TDAI_1120.has_surround_feature() is False
        assert LyngdorfModel.TDAI_2170.has_surround_feature() is False
        assert LyngdorfModel.TDAI_3400.has_surround_feature() is False

    def test_p_series_has_zone_b_feature(self):
        """Test P series models have Zone B support."""
        assert LyngdorfModel.P_100.has_zone_b_feature() is True
        assert LyngdorfModel.P_200.has_zone_b_feature() is True
        assert LyngdorfModel.P_300.has_zone_b_feature() is True

    def test_p_series_has_video_feature(self):
        """Test P series models have video capability."""
        assert LyngdorfModel.P_100.has_video_feature() is True
        assert LyngdorfModel.P_200.has_video_feature() is True
        assert LyngdorfModel.P_300.has_video_feature() is True

    def test_p_series_no_surround_feature(self):
        """P series models have no discrete channel trims (no TRIMCENTER/
        TRIMHEIGHT/TRIMLFE/TRIMSURRS in the spec)."""
        assert LyngdorfModel.P_100.has_surround_feature() is False
        assert LyngdorfModel.P_200.has_surround_feature() is False
        assert LyngdorfModel.P_300.has_surround_feature() is False

    def test_p_series_has_audio_modes_and_lipsync_despite_no_surround_flag(self):
        """P series lacks TRIM* commands entirely but still supports audio
        mode selection and lip sync - these must not be gated by
        has_surround_feature (see device.py's unconditional registration
        of Msg.AUDIO_MODE/AUDIO_TYPE/LIP_SYNC)."""
        for model in (LyngdorfModel.P_100, LyngdorfModel.P_200, LyngdorfModel.P_300):
            assert model.supports_message(Msg.AUDIO_MODE) is True
            assert model.supports_message(Msg.AUDIO_TYPE) is True
            assert model.supports_message(Msg.LIP_SYNC) is True
            assert model.supports_message(Msg.TRIM_CENTRE) is False
            assert model.supports_message(Msg.TRIM_BASS) is False
            assert model.supports_message(Msg.STREAM_TYPE) is False


# =============================================================================
# Unit Tests: Utilities
# =============================================================================


class TestConvertDecibel:
    """Tests for the convert_decibel utility function."""

    def test_convert_decibel_positive(self):
        """Test convert_decibel with positive values."""
        from lyngdorf.device import convert_decibel

        assert convert_decibel("100") == 10.0
        assert convert_decibel("50") == 5.0
        assert convert_decibel("0") == 0.0

    def test_convert_decibel_negative(self):
        """Test convert_decibel with negative values."""
        from lyngdorf.device import convert_decibel

        assert convert_decibel("-100") == -10.0
        assert convert_decibel("-50") == -5.0
        assert convert_decibel("-281") == -28.1

    def test_convert_decibel_float(self):
        """Test convert_decibel with float string input."""
        from lyngdorf.device import convert_decibel

        assert convert_decibel("10.5") == 1.05


class TestBaseAndUtilities:
    """Tests for base utilities and helper functions."""

    def test_counting_dict_add_and_lookup(self):
        """Test CountingNumberDict add and lookup."""
        from lyngdorf.base import CountingNumberDict

        cd = CountingNumberDict(2)
        cd.add(0, "first")
        cd.add(1, "second")
        assert cd.lookupIndex("first") == 0
        assert cd.lookupIndex("second") == 1
        assert cd.lookupIndex("nonexistent") == -1

    def test_counting_dict_is_full(self):
        """Test CountingNumberDict is_full method."""
        from lyngdorf.base import CountingNumberDict

        cd = CountingNumberDict(1)
        assert not cd.is_full()
        cd.add(0, "first")
        assert cd.is_full()

    def test_counting_dict_values(self):
        """Test CountingNumberDict values method."""
        from lyngdorf.base import CountingNumberDict

        cd = CountingNumberDict(2)
        cd.add(0, "first")
        cd.add(1, "second")
        values = list(cd.values())
        assert values == ["first", "second"]

    def test_package_version_matches_pyproject(self):
        """Regression test: lyngdorf.__version__ used to be a separate
        hardcoded string that drifted out of sync with pyproject.toml
        (0.7.0 vs 1.3.3). It must now be derived from installed package
        metadata, which itself comes from pyproject.toml's version field."""
        import tomllib
        from pathlib import Path

        import lyngdorf

        pyproject = tomllib.loads(
            (Path(__file__).parent.parent / "pyproject.toml").read_text()
        )
        assert lyngdorf.__version__ == pyproject["tool"]["poetry"]["version"]


# =============================================================================
# Model-Specific Configuration Tests: MP Series
# =============================================================================


class TestMP40Receiver:
    """Tests for MP40Receiver specific functionality."""

    @pytest.mark.asyncio
    async def test_mp40_receiver_initialization(self):
        """Test MP40Receiver initialization sets correct constants."""
        from lyngdorf.device import MP40Receiver

        receiver = MP40Receiver("192.168.1.1")

        # Check that MP40-specific constants are set
        assert receiver._audio_inputs == MP40_AUDIO_INPUTS
        assert receiver._video_inputs == MP40_VIDEO_INPUTS
        assert receiver._stream_types == MP40_STREAM_TYPES
        assert receiver.model == LyngdorfModel.MP_40

    def test_mp40_has_three_hdmi_inputs(self):
        """Test MP40 has exactly 3 HDMI video inputs."""
        from lyngdorf.device import MP40Receiver

        receiver = MP40Receiver("192.168.1.1")
        hdmi_inputs = [k for k, v in receiver._video_inputs.items() if "HDMI" in v]
        assert len(hdmi_inputs) == 3
        assert 1 in hdmi_inputs  # HDMI 1
        assert 2 in hdmi_inputs  # HDMI 2
        assert 3 in hdmi_inputs  # HDMI 3

    def test_mp40_audio_inputs_constants(self):
        """Test MP40 audio inputs constants are complete."""
        from lyngdorf.const import MP40_AUDIO_INPUTS

        # Test key audio inputs for MP-40
        assert MP40_AUDIO_INPUTS[1] == "HDMI"
        assert MP40_AUDIO_INPUTS[11] == "Internal Player"
        assert MP40_AUDIO_INPUTS[12] == "USB"
        assert MP40_AUDIO_INPUTS[24] == "Audio Return Channel"

    def test_mp40_video_inputs_constants(self):
        """Test MP40 video inputs constants are complete."""
        from lyngdorf.const import MP40_VIDEO_INPUTS

        assert MP40_VIDEO_INPUTS[1] == "HDMI 1"
        assert MP40_VIDEO_INPUTS[2] == "HDMI 2"
        assert MP40_VIDEO_INPUTS[3] == "HDMI 3"
        assert MP40_VIDEO_INPUTS[9] == "Internal"

    def test_mp40_stream_types_constants(self):
        """Test MP40 stream types constants."""
        from lyngdorf.const import MP40_STREAM_TYPES

        assert MP40_STREAM_TYPES[0] == "None"
        assert MP40_STREAM_TYPES[2] == "Spotify"
        assert MP40_STREAM_TYPES[6] == "Roon ready"

    @pytest.mark.asyncio
    async def test_mp40_shared_commands_with_mp60(self):
        """Test that MP40 shares command protocol with MP60."""
        from lyngdorf.device import MP40Receiver, MP60Receiver

        mp40 = MP40Receiver("192.168.1.1")
        mp60 = MP60Receiver("192.168.1.1")

        # Both should use identical command mappings
        assert mp40._model.lookup_command(Msg.POWER) == mp60._model.lookup_command(
            Msg.POWER
        )
        assert mp40._model.lookup_command(Msg.VOLUME) == mp60._model.lookup_command(
            Msg.VOLUME
        )
        assert mp40._model.lookup_command(Msg.SOURCE) == mp60._model.lookup_command(
            Msg.SOURCE
        )
        assert mp40._model.lookup_command(
            Msg.ROOM_PERFECT_POSITION
        ) == mp60._model.lookup_command(Msg.ROOM_PERFECT_POSITION)


class TestMP50Receiver:
    """Tests for MP50Receiver specific functionality."""

    @pytest.mark.asyncio
    async def test_mp50_receiver_initialization(self):
        """Test MP50Receiver initialization sets correct constants."""
        from lyngdorf.const import (
            MP50_AUDIO_INPUTS,
            MP50_STREAM_TYPES,
            MP50_VIDEO_INPUTS,
        )
        from lyngdorf.device import MP50Receiver

        receiver = MP50Receiver("192.168.1.1")

        # Check that MP50-specific constants are set
        assert receiver._audio_inputs == MP50_AUDIO_INPUTS
        assert receiver._video_inputs == MP50_VIDEO_INPUTS
        assert receiver._stream_types == MP50_STREAM_TYPES
        assert receiver.model == LyngdorfModel.MP_50

    def test_mp50_has_eight_hdmi_inputs(self):
        """Test MP50 has 8 HDMI video inputs (same as MP60)."""
        from lyngdorf.device import MP50Receiver

        receiver = MP50Receiver("192.168.1.1")
        hdmi_inputs = [k for k, v in receiver._video_inputs.items() if "HDMI" in v]
        assert len(hdmi_inputs) == 8
        for i in range(1, 9):
            assert i in hdmi_inputs  # HDMI 1-8

    def test_mp50_audio_inputs_constants(self):
        """Test MP50 audio inputs constants are complete."""
        from lyngdorf.const import MP50_AUDIO_INPUTS

        # Test key audio inputs for MP-50
        assert MP50_AUDIO_INPUTS[1] == "HDMI"
        assert MP50_AUDIO_INPUTS[11] == "Internal Player"
        assert MP50_AUDIO_INPUTS[12] == "USB"
        assert MP50_AUDIO_INPUTS[24] == "Audio Return Channel"
        assert MP50_AUDIO_INPUTS[36] == "TIDAL"

    def test_mp50_video_inputs_constants(self):
        """Test MP50 video inputs constants are complete."""
        from lyngdorf.const import MP50_VIDEO_INPUTS

        assert MP50_VIDEO_INPUTS[1] == "HDMI 1"
        assert MP50_VIDEO_INPUTS[8] == "HDMI 8"
        assert MP50_VIDEO_INPUTS[9] == "Internal"

    def test_mp50_video_outputs_constants(self):
        """Test MP50 video outputs constants."""
        from lyngdorf.const import MP50_VIDEO_OUTPUTS

        assert MP50_VIDEO_OUTPUTS[1] == "HDMI Out 1"
        assert MP50_VIDEO_OUTPUTS[2] == "HDMI Out 2"
        assert MP50_VIDEO_OUTPUTS[3] == "HDBT Out"

    def test_mp50_stream_types_constants(self):
        """Test MP50 stream types constants."""
        from lyngdorf.const import MP50_STREAM_TYPES

        assert MP50_STREAM_TYPES[0] == "None"
        assert MP50_STREAM_TYPES[2] == "Spotify"
        assert MP50_STREAM_TYPES[6] == "Roon ready"

    @pytest.mark.asyncio
    async def test_mp50_shared_commands_with_mp60(self):
        """Test that MP50 shares command protocol with MP60."""
        from lyngdorf.device import MP50Receiver, MP60Receiver

        mp50 = MP50Receiver("192.168.1.1")
        mp60 = MP60Receiver("192.168.1.1")

        # Both should use identical command mappings
        assert mp50._model.lookup_command(Msg.POWER) == mp60._model.lookup_command(
            Msg.POWER
        )
        assert mp50._model.lookup_command(Msg.VOLUME) == mp60._model.lookup_command(
            Msg.VOLUME
        )
        assert mp50._model.lookup_command(Msg.SOURCE) == mp60._model.lookup_command(
            Msg.SOURCE
        )
        assert mp50._model.lookup_command(
            Msg.ROOM_PERFECT_POSITION
        ) == mp60._model.lookup_command(Msg.ROOM_PERFECT_POSITION)


class TestMP60Receiver:
    """Tests for MP60Receiver specific functionality."""

    @pytest.mark.asyncio
    async def test_mp60_receiver_initialization(self):
        """Test MP60Receiver initialization sets correct constants."""
        from lyngdorf.device import MP60Receiver

        receiver = MP60Receiver("192.168.1.1")

        # Check that MP60-specific constants are set
        assert receiver._audio_inputs == MP60_AUDIO_INPUTS
        assert receiver._video_inputs == MP60_VIDEO_INPUTS
        assert receiver._stream_types == MP60_STREAM_TYPES
        assert receiver.model == LyngdorfModel.MP_60

    def test_mp60_audio_inputs_constants(self):
        """Test MP60 audio inputs constants are complete."""
        from lyngdorf.const import MP60_AUDIO_INPUTS

        # Test some key audio inputs
        assert MP60_AUDIO_INPUTS[1] == "HDMI"
        assert MP60_AUDIO_INPUTS[35] == "vTuner"
        assert MP60_AUDIO_INPUTS[36] == "TIDAL"
        assert MP60_AUDIO_INPUTS[37] == "Spotify"
        assert MP60_AUDIO_INPUTS[39] == "Roon"

    def test_mp60_video_inputs_constants(self):
        """Test MP60 video inputs constants are complete."""
        from lyngdorf.const import MP60_VIDEO_INPUTS

        assert MP60_VIDEO_INPUTS[1] == "HDMI 1"
        assert MP60_VIDEO_INPUTS[8] == "HDMI 8"
        assert MP60_VIDEO_INPUTS[9] == "Internal"

    def test_mp60_room_perfect_positions_constants(self):
        """Test MP60 Room Perfect positions constants."""
        from lyngdorf.const import MP60_ROOM_PERFECT_POSITIONS

        assert MP60_ROOM_PERFECT_POSITIONS[0] == "Bypass"
        assert MP60_ROOM_PERFECT_POSITIONS[9] == "Global"

    def test_mp60_stream_types_constants(self):
        """Test MP60 stream types constants."""
        from lyngdorf.const import MP60_STREAM_TYPES

        assert MP60_STREAM_TYPES[0] == "None"
        assert MP60_STREAM_TYPES[2] == "Spotify"
        assert MP60_STREAM_TYPES[6] == "Roon ready"


# =============================================================================
# Model-Specific Configuration Tests: TDAI Series
# =============================================================================


class TestTDAI1120Receiver:
    """Tests for TDAI-1120 specific functionality."""

    def test_tdai1120_receiver_initialization(self):
        """Test TDAI1120Receiver initialization sets correct constants."""
        from lyngdorf.device import TDAI1120Receiver

        receiver = TDAI1120Receiver("192.168.1.1")

        # TDAI-1120 should have empty audio inputs and video inputs
        assert receiver._audio_inputs == {}
        assert receiver._video_inputs == {}
        assert receiver.model == LyngdorfModel.TDAI_1120

    def test_tdai1120_stream_types(self):
        """Test TDAI-1120 stream types constants."""
        from lyngdorf.const import TDAI1120_STREAM_TYPES

        assert TDAI1120_STREAM_TYPES[0] == "None"
        assert TDAI1120_STREAM_TYPES[1] == "vTuner"
        assert TDAI1120_STREAM_TYPES[7] == "Bluetooth"


class TestTDAI2170Receiver:
    """Tests for TDAI-2170 specific functionality."""

    def test_tdai2170_receiver_initialization(self):
        """Test TDAI2170Receiver initialization sets correct constants."""
        from lyngdorf.device import TDAI2170Receiver

        receiver = TDAI2170Receiver("192.168.1.1")

        # TDAI-2170 should have empty audio/video inputs (dynamic)
        assert receiver._audio_inputs == {}
        assert receiver._video_inputs == {}
        assert receiver.model == LyngdorfModel.TDAI_2170

    def test_tdai2170_stream_types(self):
        """Test TDAI-2170 stream types constants."""
        from lyngdorf.const import TDAI2170_STREAM_TYPES

        assert TDAI2170_STREAM_TYPES[0] == "None"
        assert TDAI2170_STREAM_TYPES[1] == "vTuner"
        assert TDAI2170_STREAM_TYPES[2] == "Spotify"
        assert TDAI2170_STREAM_TYPES[6] == "Roon Ready"

    def test_tdai2170_shares_basic_commands_with_tdai1120(self):
        """TDAI-2170 shares its basic power/volume commands with TDAI-1120."""
        from lyngdorf.device import TDAI1120Receiver, TDAI2170Receiver

        tdai1120 = TDAI1120Receiver("192.168.1.1")
        tdai2170 = TDAI2170Receiver("192.168.1.1")

        assert tdai2170._model.lookup_command(
            Msg.POWER
        ) == tdai1120._model.lookup_command(Msg.POWER)
        assert tdai2170._model.lookup_command(
            Msg.VOLUME
        ) == tdai1120._model.lookup_command(Msg.VOLUME)

    def test_tdai2170_lacks_commands_tdai1120_has(self):
        """TDAI-2170 uses an older, more limited protocol than TDAI-1120.

        Regression test: TDAI-2170 was previously modeled by sharing
        TDAI-1120's full message dict, which claimed commands (VERBOSE,
        SOURCES_COUNT, STREAM_TYPE, TRIM_BASS, TRIM_TREBLE, BALANCE, ...)
        that do not exist in the TDAI-2170 vendor spec.
        """
        from lyngdorf.device import TDAI2170Receiver

        tdai2170 = TDAI2170Receiver("192.168.1.1")

        for msg in (
            Msg.VERBOSE,
            Msg.SOURCES_COUNT,
            Msg.SOURCE_LIST,
            Msg.STREAM_TYPE,
            Msg.ROOM_PERFECT_POSITIONS_COUNT,
            Msg.ROOM_PERFECT_VOICINGS_COUNT,
            Msg.TRIM_BASS,
            Msg.TRIM_TREBLE,
            Msg.BALANCE,
        ):
            with pytest.raises(KeyError):
                tdai2170._model.lookup_command(msg)


class TestTDAI3400Receiver:
    """Tests for TDAI-3400 specific functionality."""

    def test_tdai3400_receiver_initialization(self):
        """Test TDAI3400Receiver initialization sets correct constants."""
        from lyngdorf.device import TDAI3400Receiver

        receiver = TDAI3400Receiver("192.168.1.1")

        # TDAI-3400 should have empty audio/video inputs (dynamic)
        assert receiver._audio_inputs == {}
        assert receiver._video_inputs == {}
        assert receiver.model == LyngdorfModel.TDAI_3400

    def test_tdai3400_stream_types(self):
        """Test TDAI-3400 stream types constants."""
        from lyngdorf.const import TDAI3400_STREAM_TYPES

        assert TDAI3400_STREAM_TYPES[0] == "None"
        assert TDAI3400_STREAM_TYPES[1] == "vTuner"
        assert TDAI3400_STREAM_TYPES[2] == "Spotify"
        assert TDAI3400_STREAM_TYPES[7] == "Bluetooth"
        assert TDAI3400_STREAM_TYPES[8] == "TIDAL"

    def test_tdai3400_shares_tdai1120_protocol(self):
        """TDAI-3400 uses the same unprefixed protocol as TDAI-1120.

        Regression test: this was previously (incorrectly) modeled with a
        fabricated "I"-prefixed command set (IPWR, IVOL, etc.) that does not
        exist in the vendor spec - see issue #16 follow-up.
        """
        from lyngdorf.device import TDAI1120Receiver, TDAI3400Receiver

        tdai1120 = TDAI1120Receiver("192.168.1.1")
        tdai3400 = TDAI3400Receiver("192.168.1.1")

        assert tdai3400._model.lookup_command(Msg.POWER) == "PWR"
        assert tdai1120._model.lookup_command(Msg.POWER) == "PWR"
        assert tdai3400._model.lookup_command(Msg.VOLUME) == "VOL"
        assert tdai1120._model.lookup_command(Msg.VOLUME) == "VOL"
        assert tdai3400._model.config.messages == tdai1120._model.config.messages


class TestP100Receiver:
    """Tests for P100Receiver specific functionality."""

    @pytest.mark.asyncio
    async def test_p100_receiver_initialization(self):
        """Test P100Receiver initialization sets correct constants."""
        from lyngdorf.device import P100Receiver

        receiver = P100Receiver("192.168.1.1")

        assert receiver._audio_inputs == P_AUDIO_INPUTS
        assert receiver._video_inputs == P100_VIDEO_INPUTS
        assert receiver.model == LyngdorfModel.P_100

    def test_p100_has_four_hdmi_inputs(self):
        """Test P100 has exactly 4 HDMI video inputs (no Internal input)."""
        from lyngdorf.device import P100Receiver

        receiver = P100Receiver("192.168.1.1")
        hdmi_inputs = [k for k, v in receiver._video_inputs.items() if "HDMI" in v]
        assert len(hdmi_inputs) == 4
        assert 9 not in receiver._video_inputs


class TestP200Receiver:
    """Tests for P200Receiver specific functionality."""

    @pytest.mark.asyncio
    async def test_p200_receiver_initialization(self):
        """Test P200Receiver initialization sets correct constants."""
        from lyngdorf.device import P200Receiver

        receiver = P200Receiver("192.168.1.1")

        assert receiver._audio_inputs == P_AUDIO_INPUTS
        assert receiver._video_inputs == P_VIDEO_INPUTS
        assert receiver.model == LyngdorfModel.P_200

    def test_p200_has_nine_video_inputs(self):
        """Test P200 has 8 HDMI inputs plus Internal."""
        from lyngdorf.device import P200Receiver

        receiver = P200Receiver("192.168.1.1")
        assert len(receiver._video_inputs) == 10  # None + 8 HDMI + Internal
        assert receiver._video_inputs[9] == "Internal"


class TestP300Receiver:
    """Tests for P300Receiver specific functionality."""

    @pytest.mark.asyncio
    async def test_p300_receiver_initialization(self):
        """Test P300Receiver initialization sets correct constants."""
        from lyngdorf.device import P300Receiver

        receiver = P300Receiver("192.168.1.1")

        assert receiver._audio_inputs == P_AUDIO_INPUTS
        assert receiver._video_inputs == P_VIDEO_INPUTS
        assert receiver.model == LyngdorfModel.P_300

    @pytest.mark.asyncio
    async def test_p300_shares_commands_with_p200(self):
        """Test that P300 shares command protocol with P200."""
        from lyngdorf.device import P200Receiver, P300Receiver

        p200 = P200Receiver("192.168.1.1")
        p300 = P300Receiver("192.168.1.1")

        assert p300._model.config.messages == p200._model.config.messages

    def test_p_series_lacks_trim_and_stream_type_commands(self):
        """Regression test: P series has no channel trims, no bass/treble
        trim, and no built-in streaming source at all - unlike MP series."""
        from lyngdorf.device import P300Receiver

        p300 = P300Receiver("192.168.1.1")

        for msg in (
            Msg.TRIM_BASS,
            Msg.TRIM_TREBLE,
            Msg.TRIM_CENTRE,
            Msg.TRIM_HEIGHT,
            Msg.TRIM_LFE,
            Msg.TRIM_SURROUND,
            Msg.BALANCE,
            Msg.STREAM_TYPE,
            Msg.ZONE_B_STREAM_TYPE,
        ):
            with pytest.raises(KeyError):
                p300._model.lookup_command(msg)


# =============================================================================
# Factory Functions and Auto-Detection Tests
# =============================================================================


class TestReceiverCreation:
    """Tests for receiver creation and factory functions."""

    @pytest.mark.asyncio
    async def test_async_create_receiver_mp60(self):
        """Test async_create_receiver with MP-60 model."""
        from lyngdorf.device import MP60Receiver, async_create_receiver

        receiver = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        assert isinstance(receiver, MP60Receiver)
        assert receiver.model == LyngdorfModel.MP_60

    @pytest.mark.asyncio
    async def test_async_create_receiver_tdai1120(self):
        """Test async_create_receiver with TDAI-1120 model."""
        from lyngdorf.device import TDAI1120Receiver, async_create_receiver

        receiver = await async_create_receiver(FAKE_IP, LyngdorfModel.TDAI_1120)
        assert isinstance(receiver, TDAI1120Receiver)
        assert receiver.model == LyngdorfModel.TDAI_1120

    @pytest.mark.asyncio
    async def test_async_create_receiver_auto_detect_mp60(self):
        """Test async_create_receiver with auto-detection of MP-60."""
        from lyngdorf.device import MP60Receiver, async_create_receiver

        async def mock_connection(*args, **kwargs):
            reader = mock.AsyncMock()
            writer = mock.AsyncMock()
            reader.read = mock.AsyncMock(return_value=b"!DEVICE(MP-60)")
            writer.write = mock.Mock()
            writer.close = mock.Mock()
            writer.wait_closed = mock.AsyncMock()
            return reader, writer

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection,
        ):
            receiver = await async_create_receiver(FAKE_IP)
            assert isinstance(receiver, MP60Receiver)
            assert receiver.model == LyngdorfModel.MP_60

    @pytest.mark.asyncio
    async def test_async_create_receiver_auto_detect_exception(self):
        """Test async_create_receiver when auto-detection raises exception."""
        from lyngdorf.device import async_create_receiver

        async def mock_connection_error(*args, **kwargs):
            raise OSError("Connection error")

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection_error,
        ):
            with pytest.raises(NotImplementedError):
                await async_create_receiver(FAKE_IP)

    @pytest.mark.asyncio
    async def test_async_create_receiver_unknown_model_auto_detect(self):
        """Test async_create_receiver with unknown model from auto-detection."""
        from lyngdorf.device import async_create_receiver

        async def mock_connection(*args, **kwargs):
            reader = mock.AsyncMock()
            writer = mock.AsyncMock()
            reader.read = mock.AsyncMock(return_value=b"!DEVICE(unknown-model)")
            writer.write = mock.Mock()
            writer.close = mock.Mock()
            writer.wait_closed = mock.AsyncMock()
            return reader, writer

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection,
        ):
            with pytest.raises(NotImplementedError):
                await async_create_receiver(FAKE_IP)

    @pytest.mark.asyncio
    async def test_async_find_receiver_model_mp60(self):
        """Test async_find_receiver_model finds MP-60."""
        from lyngdorf.device import async_find_receiver_model

        # Mock the connection and response
        async def mock_connection(*args, **kwargs):
            reader = mock.AsyncMock()
            writer = mock.AsyncMock()
            reader.read = mock.AsyncMock(return_value=b"!DEVICE(MP-60)")
            writer.write = mock.Mock()
            writer.drain = mock.AsyncMock()
            writer.close = mock.Mock()
            writer.wait_closed = mock.AsyncMock()
            return reader, writer

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection,
        ):
            model = await async_find_receiver_model("192.168.1.1", timeout=5.0)
            assert model == LyngdorfModel.MP_60

    @pytest.mark.asyncio
    async def test_async_find_receiver_model_unknown(self):
        """Test async_find_receiver_model with unknown model."""
        from lyngdorf.device import async_find_receiver_model

        # Mock the connection and response with unknown model
        async def mock_connection(*args, **kwargs):
            reader = mock.AsyncMock()
            writer = mock.AsyncMock()
            reader.read = mock.AsyncMock(return_value=b"!DEVICE(unknown-model)")
            writer.write = mock.Mock()
            writer.drain = mock.AsyncMock()
            writer.close = mock.Mock()
            writer.wait_closed = mock.AsyncMock()
            return reader, writer

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection,
        ):
            model = await async_find_receiver_model("192.168.1.1", timeout=5.0)
            assert model is None

    @pytest.mark.asyncio
    async def test_async_find_receiver_model_timeout(self):
        """Test async_find_receiver_model with timeout."""
        from lyngdorf.device import async_find_receiver_model

        async def mock_connection_timeout(*args, **kwargs):
            await asyncio.sleep(10)

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection_timeout,
        ):
            model = await async_find_receiver_model("192.168.1.1", timeout=0.01)
            assert model is None

    @pytest.mark.asyncio
    async def test_async_find_receiver_model_connection_error(self):
        """Test async_find_receiver_model with connection error."""
        from lyngdorf.device import async_find_receiver_model

        async def mock_connection_error(*args, **kwargs):
            raise OSError("Connection refused")

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection_error,
        ):
            model = await async_find_receiver_model("192.168.1.1", timeout=5.0)
            assert model is None

    @pytest.mark.asyncio
    async def test_async_find_receiver_model_malformed_response(self):
        """Test async_find_receiver_model with malformed response."""
        from lyngdorf.device import async_find_receiver_model

        async def mock_connection(*args, **kwargs):
            reader = mock.AsyncMock()
            writer = mock.AsyncMock()
            reader.read = mock.AsyncMock(return_value=b"!DEVICE_MALFORMED")
            writer.write = mock.Mock()
            writer.drain = mock.AsyncMock()
            writer.close = mock.Mock()
            writer.wait_closed = mock.AsyncMock()
            return reader, writer

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection,
        ):
            model = await async_find_receiver_model("192.168.1.1", timeout=5.0)
            assert model is None

    @pytest.mark.asyncio
    async def test_async_find_receiver_model_writer_close_exception(self):
        """Test async_find_receiver_model with exception in writer.wait_closed."""
        from lyngdorf.device import async_find_receiver_model

        async def mock_connection(*args, **kwargs):
            reader = mock.AsyncMock()
            writer = mock.AsyncMock()
            reader.read = mock.AsyncMock(return_value=b"!DEVICE(MP-60)")
            writer.write = mock.Mock()
            writer.drain = mock.AsyncMock()
            writer.close = mock.Mock()
            writer.wait_closed = mock.AsyncMock(
                side_effect=RuntimeError("Close failed")
            )
            return reader, writer

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            side_effect=mock_connection,
        ):
            model = await async_find_receiver_model("192.168.1.1", timeout=5.0)
            assert (
                model == LyngdorfModel.MP_60
            )  # Should still succeed despite close error


# =============================================================================
# Integration Tests: Receiver Functionality
# =============================================================================


class TestReceiverBasicFunctionality:
    """Integration tests for basic receiver functionality."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_receiver_instantiate(self):
        """Test basic receiver instantiation."""
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        assert client.model.model_name == "mp-60"
        assert client.model.manufacturer == "Lyngdorf"
        assert client.model.name == "MP_60"

    @pytest.mark.asyncio
    async def test_receiver_host_and_model_properties(self):
        """Test receiver host and model properties."""
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        assert client.host == FAKE_IP
        assert client.model == LyngdorfModel.MP_60

    @pytest.mark.asyncio
    async def test_receiver_name_property(self):
        """Test receiver name property."""

        def test_function(client: Receiver):
            assert client.name == "MP-60"

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_logging(self):
        """Test logging configuration."""
        _LOGGER.debug("Hello from debug logging")

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test receiving commands from receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()


class TestPowerControl:
    """Tests for power control functionality."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_power_state_reading(self):
        """Test reading power state from receiver."""

        def test_function(client: Receiver):
            assert client.power_on
            assert not client.zone_b_power_on

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_power_off(self):
        """Test POWER(0) turns the API off."""

        def test_function(client: Receiver):
            assert not client.power_on

        await self._test_receiving_commands(["!POWER(0)"], "POWER", test_function)

    @pytest.mark.asyncio
    async def test_power_on(self):
        """Test POWER(1) turns the API on."""

        def test_function(client: Receiver):
            assert client.power_on

        await self._test_receiving_commands(["!POWER(1)"], "POWER", test_function)

    @pytest.mark.asyncio
    async def test_power_control_commands(self):
        """Test power control commands are sent correctly."""

        def client_functions(client: Receiver):
            client.power_on = True
            client.power_on = False
            client.zone_b_power_on = True
            client.zone_b_power_on = False

        def assertion_function(client: Receiver, commandsSent: list):
            assert [
                "!POWERONMAIN",
                "!POWEROFFMAIN",
                "!POWERONZONE2",
                "!POWEROFFZONE2",
            ] == commandsSent

        await self._test_sending_commands(
            ["!AUDTYPE(PCM zero, 2.0.0)"],
            "AUDTYPE",
            client_functions,
            assertion_function,
        )

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test receiving commands from receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()

    async def _test_sending_commands(
        self,
        commands_received,
        wait_for_command,
        client_functions,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test sending commands to receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            with mock.patch(
                "lyngdorf.api.LyngdorfProtocol.write", new_callable=mock.Mock
            ) as write_mock:
                debug_mock.return_value.create_connection = AsyncMock(
                    side_effect=create_conn
                )
                await client.async_connect()
                self.future = asyncio.Future()
                client._api.register_callback(wait_for_command, self._callback)
                protocol.data_received(
                    bytes("\r".join(commands_received) + "\r", "utf-8")
                )
                await self.future

                before_length = len(write_mock.call_args_list)
                client_functions(client)
                after_list = [
                    call.args[0].replace("\r", "")
                    for call in write_mock.call_args_list[before_length:]
                ]
                test_function(client, after_list)
                await client.async_disconnect()


class TestVolumeAndMute:
    """Tests for volume and mute functionality."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_volume_and_mute_reading(self):
        """Test reading volume and mute state from receiver."""

        def test_function(client: Receiver):
            assert client.name == "MP-60"
            assert client.volume == -28.1
            assert client.zone_b_volume == -55.0
            assert not client.mute_enabled
            assert client.zone_b_mute_enabled

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_volume_and_mute_commands(self):
        """Test volume and mute commands are sent correctly."""

        def client_functions(client: Receiver):
            client.volume = -22
            client.volume_up()
            client.volume_down()
            client.zone_b_volume_up()
            client.zone_b_volume_down()
            client.mute_enabled = True
            client.mute_enabled = False
            client.zone_b_mute_enabled = True
            client.zone_b_mute_enabled = False
            client.lipsync = 10
            client.room_perfect_position = "Focus 1"
            client.voicing = "Voice 1"

        def assertion_function(client: Receiver, commandsSent: list):
            assert [
                "!VOL(-220)",
                "!VOL+",
                "!VOL-",
                "!ZVOL+",
                "!ZVOL-",
                "!MUTEON",
                "!MUTEOFF",
                "!ZMUTEON",
                "!ZMUTEOFF",
                "!LIPSYNC(10)",
                "!RPFOC(1)",
                "!RPVOI(1)",
            ] == commandsSent

        await self._test_sending_commands(
            [
                "!RPFOCCOUNT(2)",
                '!RPFOC(0)"Global"',
                '!RPFOC(1)"Focus 1"',
                "!RPVOICOUNT(2)",
                '!RPVOI(0)"Voice 0"',
                '!RPVOI(1)"Voice 1"',
                "!AUDTYPE(PCM zero, 2.0.0)",
            ],
            "AUDTYPE",
            client_functions,
            assertion_function,
        )

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test receiving commands from receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()

    async def _test_sending_commands(
        self,
        commands_received,
        wait_for_command,
        client_functions,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test sending commands to receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            with mock.patch(
                "lyngdorf.api.LyngdorfProtocol.write", new_callable=mock.Mock
            ) as write_mock:
                debug_mock.return_value.create_connection = AsyncMock(
                    side_effect=create_conn
                )
                await client.async_connect()
                self.future = asyncio.Future()
                client._api.register_callback(wait_for_command, self._callback)
                protocol.data_received(
                    bytes("\r".join(commands_received) + "\r", "utf-8")
                )
                await self.future

                before_length = len(write_mock.call_args_list)
                client_functions(client)
                after_list = [
                    call.args[0].replace("\r", "")
                    for call in write_mock.call_args_list[before_length:]
                ]
                test_function(client, after_list)
                await client.async_disconnect()


class TestTrimControls:
    """Tests for trim control functionality."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_trim_commands(self):
        """Test trim commands are sent correctly."""

        def client_functions(client: Receiver):
            client.trim_bass = 1.0
            client.trim_centre = -5.0
            client.trim_height = -3.0
            client.trim_lfe = -2.0
            client.trim_surround = 5.0
            client.trim_treble = 6.0

            client.trim_bass_up()
            client.trim_bass_down()
            client.trim_centre_up()
            client.trim_centre_down()
            client.trim_height_up()
            client.trim_height_down()
            client.trim_lfe_up()
            client.trim_lfe_down()
            client.trim_surround_up()
            client.trim_surround_down()
            client.trim_treble_up()
            client.trim_treble_down()

        def assertion_function(client: Receiver, commandsSent: list):
            assert [
                "!TRIMBASS(10)",
                "!TRIMCENTER(-50)",
                "!TRIMHEIGHT(-30)",
                "!TRIMLFE(-20)",
                "!TRIMSURRS(50)",
                "!TRIMTREB(60)",
                "!TRIMBASS+",
                "!TRIMBASS-",
                "!TRIMCENTER+",
                "!TRIMCENTER-",
                "!TRIMHEIGHT+",
                "!TRIMHEIGHT-",
                "!TRIMLFE+",
                "!TRIMLFE-",
                "!TRIMSURRS+",
                "!TRIMSURRS-",
                "!TRIMTREB+",
                "!TRIMTREB-",
            ] == commandsSent

        await self._test_sending_commands(
            ["!AUDTYPE(PCM zero, 2.0.0)"],
            "AUDTYPE",
            client_functions,
            assertion_function,
        )

    async def _test_sending_commands(
        self,
        commands_received,
        wait_for_command,
        client_functions,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test sending commands to receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            with mock.patch(
                "lyngdorf.api.LyngdorfProtocol.write", new_callable=mock.Mock
            ) as write_mock:
                debug_mock.return_value.create_connection = AsyncMock(
                    side_effect=create_conn
                )
                await client.async_connect()
                self.future = asyncio.Future()
                client._api.register_callback(wait_for_command, self._callback)
                protocol.data_received(
                    bytes("\r".join(commands_received) + "\r", "utf-8")
                )
                await self.future

                before_length = len(write_mock.call_args_list)
                client_functions(client)
                after_list = [
                    call.args[0].replace("\r", "")
                    for call in write_mock.call_args_list[before_length:]
                ]
                test_function(client, after_list)
                await client.async_disconnect()


class TestSourcesAndSoundModes:
    """Tests for source selection and sound mode functionality."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_sources_and_sound_modes_reading(self):
        """Test reading sources and sound modes from receiver."""

        def test_function(client: Receiver):
            assert len(client.available_sources) == 24
            assert "Playstation" in client.available_sources
            assert len(client.available_sound_modes) == 10
            assert "Party" in client.available_sound_modes
            assert client.sound_mode == "Dolby Upmixer"
            assert client.source == "Apple TV"
            assert client.audio_input == "HDMI"
            assert client.video_input == "HDMI 2"
            assert client.video_information == "2160p50 RGB 4:4:4"
            assert client.audio_information == "PCM zero, 2.0.0"
            assert isinstance(client.available_sound_modes, list)
            assert isinstance(client.available_sources, list)
            assert isinstance(client.zone_b_available_sources, list)
            assert client.zone_b_available_sources == ["Apple TV", "Wonk"]
            assert client.zone_b_source == "Apple TV"
            assert client.available_room_perfect_positions == ["Global", "Focus 1"]

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_source_and_sound_mode_commands(self):
        """Test source and sound mode selection commands."""

        def test_function(client: Receiver, commandsSent: list):
            assert "!SRC(1)" in commandsSent
            assert "!AUDMODE(9)" in commandsSent
            assert "!ZSRC(1)" in commandsSent

        def client_functions(client: Receiver):
            client.source = "Playstation"
            client.sound_mode = "Party"
            client.zone_b_source = "Wonk"

        await self._test_sending_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, client_functions, test_function
        )

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test receiving commands from receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()

    async def _test_sending_commands(
        self,
        commands_received,
        wait_for_command,
        client_functions,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test sending commands to receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            with mock.patch(
                "lyngdorf.api.LyngdorfProtocol.write", new_callable=mock.Mock
            ) as write_mock:
                debug_mock.return_value.create_connection = AsyncMock(
                    side_effect=create_conn
                )
                await client.async_connect()
                self.future = asyncio.Future()
                client._api.register_callback(wait_for_command, self._callback)
                protocol.data_received(
                    bytes("\r".join(commands_received) + "\r", "utf-8")
                )
                await self.future

                before_length = len(write_mock.call_args_list)
                client_functions(client)
                after_list = [
                    call.args[0].replace("\r", "")
                    for call in write_mock.call_args_list[before_length:]
                ]
                test_function(client, after_list)
                await client.async_disconnect()


class TestZoneBFunctionality:
    """Tests for Zone B functionality."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_zone_b_source_selection(self):
        """Test Zone B source selection and commands."""

        def client_functions(client: Receiver):
            client.zone_b_source = "Wonk"

        def assertion_function(client: Receiver, commandsSent: list):
            assert "!ZSRC(1)" in commandsSent

        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            with mock.patch(
                "lyngdorf.api.LyngdorfProtocol.write", new_callable=mock.Mock
            ) as write_mock:
                debug_mock.return_value.create_connection = AsyncMock(
                    side_effect=create_conn
                )
                await client.async_connect()
                self.future = asyncio.Future()
                client._api.register_callback("AUDTYPE", self._callback)
                protocol.data_received(
                    bytes("\r".join(SETUP_RESPONSES) + "\r", "utf-8")
                )
                await self.future

                before_length = len(write_mock.call_args_list)
                client_functions(client)
                after_list = [
                    call.args[0].replace("\r", "")
                    for call in write_mock.call_args_list[before_length:]
                ]
                assertion_function(client, after_list)
                await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_zone_b_source_invalid(self):
        """Test Zone B source with invalid source name raises error."""
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        with pytest.raises(LyngdorfInvalidValueError):
            client.zone_b_source = "NonExistentSource"


class TestAudioVideoInputs:
    """Tests for audio and video input handling."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_audio_input_known_values(self):
        """Test audio input with known values."""

        def test_function(client: Receiver):
            assert client.audio_input == "HDMI"

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_audio_input_unknown_values(self):
        """Test audio input with unknown audio input code."""

        def test_function(client: Receiver):
            assert client.audio_input == "audio-999"

        responses = SETUP_RESPONSES.copy()
        for i, resp in enumerate(responses):
            if resp.startswith("!AUDIN"):
                responses[i] = "!AUDIN(999)"

        await self._test_receiving_commands(
            responses, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_video_input_known_values(self):
        """Test video input with known values."""

        def test_function(client: Receiver):
            assert client.video_input == "HDMI 2"

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_video_input_unknown_values(self):
        """Test video input with unknown video input code."""

        def test_function(client: Receiver):
            assert client.video_input == "video-99"

        responses = SETUP_RESPONSES.copy()
        for i, resp in enumerate(responses):
            if resp.startswith("!VIDIN"):
                responses[i] = "!VIDIN(99)"

        await self._test_receiving_commands(
            responses, SETUP_LAST_RESPONSE, test_function
        )

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test receiving commands from receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()


class TestStreamingAndVideoInfo:
    """Tests for streaming source and video information."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_streaming_source(self):
        """Test streaming source information."""

        def test_function(client: Receiver):
            assert client.streaming_source == "Spotify"
            assert client.zone_b_streaming_source == "AirPlay"

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_streaming_source_unknown(self):
        """Test streaming source with unknown stream type code."""

        def test_function(client: Receiver):
            assert client.streaming_source == "video-99"

        responses = SETUP_RESPONSES.copy()
        for i, resp in enumerate(responses):
            if resp.startswith("!STREAMTYPE"):
                responses[i] = "!STREAMTYPE(99)"

        await self._test_receiving_commands(
            responses, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_video_information(self):
        """Test video information property."""

        def test_function(client: Receiver):
            assert client.video_information == "2160p50 RGB 4:4:4"
            assert client.audio_information == "PCM zero, 2.0.0"

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test receiving commands from receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()


class TestRoomPerfectAndVoicing:
    """Tests for Room Perfect and Voicing features."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_room_perfect_positions_and_voicing(self):
        """Test Room Perfect positions and voicing settings."""

        def test_function(client: Receiver):
            assert len(client.available_room_perfect_positions) == 2
            assert "Global" in client.available_room_perfect_positions
            assert "Focus 1" in client.available_room_perfect_positions
            assert client.room_perfect_position == "Focus 1"
            assert len(client.available_voicings) == 2
            assert "Voice 0" in client.available_voicings
            assert client.voicing == "Voice 1"

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

    @pytest.mark.asyncio
    async def test_room_perfect_invalid_position(self):
        """Test invalid Room Perfect position raises error."""
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        with pytest.raises(LyngdorfInvalidValueError):
            client.room_perfect_position = "InvalidPosition"

    @pytest.mark.asyncio
    async def test_voicing_invalid(self):
        """Test invalid voicing raises error."""
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        with pytest.raises(LyngdorfInvalidValueError):
            client.voicing = "InvalidVoicing"

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
    ):
        """Helper to test receiving commands from receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()


class TestNotificationCallbacks:
    """Tests for notification callback behavior."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_notification_callbacks(self):
        """Test notification callbacks are triggered."""

        def notify_me():
            notify_me.counter += 1

        notify_me.counter = 0

        def test_function(client: Receiver):
            assert notify_me.counter == 17

        def before_connect_function(client: Receiver):
            client.register_notification_callback(notify_me)

        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(SETUP_LAST_RESPONSE, self._callback)
            protocol.data_received(bytes("\r".join(SETUP_RESPONSES) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_unregister_notification_callback(self):
        """Test unregistering a notification callback."""
        callback_called = []

        def test_callback():
            callback_called.append(True)

        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        client.register_notification_callback(test_callback)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback("AUDTYPE", self._callback)

            protocol.data_received(
                bytes("\r".join(["!AUDTYPE(PCM zero, 2.0.0)"]) + "\r", "utf-8")
            )
            await self.future

            # Unregister the callback
            client.un_register_notification_callback(test_callback)

            # Trigger another event - callback should not be called
            callback_called.clear()
            self.future = asyncio.Future()
            protocol.data_received(bytes("!POWER(1)\r", "utf-8"))

            # Wait a bit for any potential callbacks
            await asyncio.sleep(0.05)
            assert len(callback_called) == 0

            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_notification_callback_exception_handling(self):
        """Test exception handling in notification callbacks."""

        def bad_callback():
            raise ValueError("Test error in callback")

        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        client.register_notification_callback(bad_callback)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback("AUDTYPE", self._callback)

            # Sending a command that will trigger callbacks with an exception
            protocol.data_received(bytes("\r".join(SETUP_RESPONSES) + "\r", "utf-8"))
            await self.future

            await client.async_disconnect()


class TestConnectionManagement:
    """Tests for connection and disconnection."""

    future = None

    def _callback(self, param1, param2):
        self.future.set_result(True)

    @pytest.mark.asyncio
    async def test_async_disconnect(self):
        """Test async_disconnect properly closes connection."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback("AUDTYPE", self._callback)
            protocol.data_received(bytes("\r".join(SETUP_RESPONSES) + "\r", "utf-8"))
            await self.future

            # Now disconnect
            await client.async_disconnect()

            # Verify disconnect was called
            assert not client._api.connected


class TestZoneBGating:
    """Regression tests for issue #16: async_connect must not crash on
    models missing a capability (Zone B, video, or surround), and must not
    register callbacks for messages the connected model doesn't support.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", supported_models(), ids=lambda m: m.name)
    async def test_async_connect_does_not_crash_for_any_supported_model(self, model):
        """Every supported model must connect without raising KeyError."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, model)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_async_connect_skips_zone_b_callbacks_for_tdai(self):
        """TDAI models have no Zone B - their command set has no Zone B
        commands, so no Zone B callbacks should be registered."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.TDAI_3400)
        assert client.model.has_zone_b_feature() is False

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            registered = client._api._callbacks.keys()
            assert not any(cmd.startswith("Z") or "ZONE" in cmd for cmd in registered)
            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_async_connect_registers_zone_b_callbacks_for_mp(self):
        """MP series models have Zone B - their Zone B callbacks must still
        be registered."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        assert client.model.has_zone_b_feature() is True

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            registered = client._api._callbacks.keys()
            assert client.lookup_command(Msg.ZONE_B_VOLUME) in registered
            assert client.lookup_command(Msg.ZONE_B_POWER) in registered
            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_async_connect_skips_video_callbacks_for_tdai(self):
        """TDAI models have no video I/O - VIDIN/VIDTYPE/AUDIN are not in
        their command set, so those callbacks should not be registered."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.TDAI_3400)
        assert client.model.has_video_feature() is False

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            registered = client._api._callbacks.keys()
            assert "IVIDIN" not in registered and "VIDIN" not in registered
            assert "IVIDTYPE" not in registered and "VIDTYPE" not in registered
            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_async_connect_registers_video_callbacks_for_mp(self):
        """MP series models have video I/O - their video callbacks must
        still be registered."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        assert client.model.has_video_feature() is True

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            registered = client._api._callbacks.keys()
            assert client.lookup_command(Msg.VIDEO_IN) in registered
            assert client.lookup_command(Msg.VIDEO_TYPE) in registered
            assert client.lookup_command(Msg.AUDIO_IN) in registered
            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_async_connect_skips_surround_callbacks_for_tdai(self):
        """TDAI models are stereo-only - AUDMODE/LIPSYNC/TRIMCENTER etc are
        not in their command set, so those callbacks should not be
        registered (via the defensive catch in _register_callback, since
        these are attempted unconditionally for every model)."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.TDAI_3400)
        assert client.model.has_surround_feature() is False

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            registered = client._api._callbacks.keys()
            for token in ("AUDMODE", "AUDMODECOUNT", "LIPSYNC", "TRIMCENTER"):
                assert token not in registered and f"I{token}" not in registered
            await client.async_disconnect()

    @pytest.mark.asyncio
    async def test_async_connect_registers_surround_callbacks_for_mp(self):
        """MP series models support surround decoding - their surround
        callbacks must still be registered."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        assert client.model.has_surround_feature() is True

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            registered = client._api._callbacks.keys()
            assert client.lookup_command(Msg.AUDIO_MODE) in registered
            assert client.lookup_command(Msg.LIP_SYNC) in registered
            assert client.lookup_command(Msg.TRIM_CENTRE) in registered
            await client.async_disconnect()


class TestSetupCommandPacing:
    """Regression tests: writing all setup commands back-to-back with no
    pacing caused a real MP-60 to silently stop replying partway through
    the burst (verified on real hardware - volume/mute/trim never
    populated). _writeSetup must pace writes with setup_command_delay.
    """

    @pytest.mark.asyncio
    async def test_writesetup_sleeps_between_each_command(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api.setup_command_delay = 0.05
        api._protocol = mock.Mock()

        with mock.patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await api._writeSetup()

        # One sleep between each pair of commands, none before the first
        # or after the last.
        assert sleep_mock.call_count == len(api._model.setup_commands) - 1
        for call in sleep_mock.call_args_list:
            assert call.args[0] == 0.05

    @pytest.mark.asyncio
    async def test_writesetup_sends_every_command(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api.setup_command_delay = 0
        api._protocol = mock.Mock()

        await api._writeSetup()

        sent = [call.args[0] for call in api._protocol.write.call_args_list]
        assert len(sent) == len(api._model.setup_commands)


class TestPongDetectionDefensive:
    """Regression test: _process_event used to unconditionally look up
    Msg.PONG on every incoming message. TDAI models have no PONG command
    (see models/tdai_series.py), so every message received from a TDAI
    device would raise KeyError. Must degrade to "not a pong" instead of
    crashing message processing.
    """

    @pytest.mark.asyncio
    async def test_process_event_does_not_crash_for_model_without_pong(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.TDAI_3400)
        assert Msg.PONG not in api._model.config.messages

        api._process_event("!DEVICE(TDAI-3400)")  # must not raise
        await asyncio.sleep(0)  # let the created task run


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestExceptionHandling:
    """Tests for exception handling in the device module."""

    def test_lyngdorf_invalid_value_error(self):
        """Test LyngdorfInvalidValueError exception."""
        from lyngdorf.exceptions import LyngdorfInvalidValueError

        error = LyngdorfInvalidValueError("test message")
        assert isinstance(error, Exception)

    @pytest.mark.asyncio
    async def test_source_invalid_error(self):
        """Test invalid source selection raises error."""
        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        with pytest.raises(LyngdorfInvalidValueError):
            client.source = "NonExistentSource"


# =============================================================================
# TDAI State Encoding
#
# The TDAI family spells power and mute states as words where the MP and P
# families use digits or distinct messages:
#
#   TDAI-1120/2170/3400   !PWR(ON)      !MUTE(ON)
#   MP-40/50/60, P-series !POWER(1)     !MUTEON
#
# Both encodings are in the vendor manuals under spec/ and transcribed in
# docs/. Verified against a real TDAI-1120 over TCP 84: `!PWR?` answers
# `!PWR(OFF)` and `!MUTE?` answers `!MUTE(OFF)` -- at feedback level 0 and
# at VERB(1) alike.
# =============================================================================


class TestTdaiStateEncoding:
    """The TDAI power/mute encodings must survive the round trip."""

    future = None

    def _callback(self, param1, param2):
        if self.future is not None and not self.future.done():
            self.future.set_result(True)

    def test_tdai_power_state_on_value(self):
        """TDAI models report power as ON, not 1."""
        assert LyngdorfModel.TDAI_1120.power_state_on_value() == "ON"
        assert LyngdorfModel.TDAI_2170.power_state_on_value() == "ON"
        assert LyngdorfModel.TDAI_3400.power_state_on_value() == "ON"

    def test_mp_and_p_power_state_on_value(self):
        """MP and P models keep the numeric encoding."""
        assert LyngdorfModel.MP_40.power_state_on_value() == "1"
        assert LyngdorfModel.MP_50.power_state_on_value() == "1"
        assert LyngdorfModel.MP_60.power_state_on_value() == "1"
        assert LyngdorfModel.P_100.power_state_on_value() == "1"

    def test_tdai_mute_state_in_parameter(self):
        """TDAI models carry mute state as a MUTE parameter."""
        assert LyngdorfModel.TDAI_1120.has_mute_state_in_parameter() is True
        assert LyngdorfModel.TDAI_2170.has_mute_state_in_parameter() is True
        assert LyngdorfModel.TDAI_3400.has_mute_state_in_parameter() is True

    def test_mp_and_p_mute_state_not_in_parameter(self):
        """MP and P models use distinct MUTEON/MUTEOFF messages."""
        assert LyngdorfModel.MP_40.has_mute_state_in_parameter() is False
        assert LyngdorfModel.MP_50.has_mute_state_in_parameter() is False
        assert LyngdorfModel.MP_60.has_mute_state_in_parameter() is False
        assert LyngdorfModel.P_100.has_mute_state_in_parameter() is False

    @pytest.mark.asyncio
    async def test_tdai_reports_power_on(self):
        """`!PWR(ON)` must read as powered on, not off."""

        def test_function(client: Receiver):
            assert client.power_on is True

        await self._receive(["!PWR(ON)", "!BAL(0)"], test_function)

    @pytest.mark.asyncio
    async def test_tdai_reports_power_off(self):
        """`!PWR(OFF)` must read as powered off."""

        def test_function(client: Receiver):
            assert client.power_on is False

        await self._receive(["!PWR(OFF)", "!BAL(0)"], test_function)

    @pytest.mark.asyncio
    async def test_tdai_reports_mute_on(self):
        """`!MUTE(ON)` must reach mute_enabled."""

        def test_function(client: Receiver):
            assert client.mute_enabled is True

        await self._receive(["!MUTE(ON)", "!BAL(0)"], test_function)

    @pytest.mark.asyncio
    async def test_tdai_reports_mute_off(self):
        """`!MUTE(OFF)` must reach mute_enabled."""

        def test_function(client: Receiver):
            assert client.mute_enabled is False

        await self._receive(["!MUTE(ON)", "!MUTE(OFF)", "!BAL(0)"], test_function)

    async def _receive(self, commands_received, test_function):
        """Feed raw TDAI-shaped messages to a TDAI-1120 receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.TDAI_1120)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback("BAL", self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()


# =============================================================================
# TDAI Source Names
#
# !SRC? on a TDAI replies with a bare index (!SRC(n)) - no name. The
# name-bearing replies are keyed under a different message, SRCNAME, and
# pack index and name comma-separated inside one set of parens -
# !SRCNAME(a,"Name") - rather than MP's !SRC(a)"Name" (name trailing,
# outside the parens). Both the SRCLIST? list-population burst and the
# current-source query use this SRCNAME shape. See docs/tdai-1120.md.
# =============================================================================


class TestTdaiSourceName:
    """TDAI source names must populate despite the differently-shaped reply."""

    future = None

    def _callback(self, param1, param2):
        if self.future is not None and not self.future.done():
            self.future.set_result(True)

    def test_tdai_1120_and_3400_support_source_name(self):
        """TDAI-1120/3400 have a SOURCE_NAME message mapped."""
        assert LyngdorfModel.TDAI_1120.supports_message(Msg.SOURCE_NAME) is True
        assert LyngdorfModel.TDAI_3400.supports_message(Msg.SOURCE_NAME) is True

    def test_tdai_2170_and_others_have_no_source_name(self):
        """TDAI-2170 has no bulk/no-arg SRCNAME query, only per-index
        SRCNAME(n)? - out of scope for this fix. MP and P never needed one
        since their SRC reply already carries a name."""
        assert LyngdorfModel.TDAI_2170.supports_message(Msg.SOURCE_NAME) is False
        assert LyngdorfModel.MP_60.supports_message(Msg.SOURCE_NAME) is False
        assert LyngdorfModel.P_100.supports_message(Msg.SOURCE_NAME) is False

    @pytest.mark.asyncio
    async def test_tdai_source_list_populates_names(self):
        """The SRCLIST? burst (SRCCOUNT then repeated SRCNAME(a,"Name"))
        must populate available_sources with real names, not stay empty."""

        def test_function(client: Receiver):
            assert client.available_sources == ["HDMI", "Optical"]

        await self._receive(
            ["!SRCCOUNT(2)", '!SRCNAME(0,"HDMI")', '!SRCNAME(1,"Optical")'],
            test_function,
        )

    @pytest.mark.asyncio
    async def test_tdai_current_source_resolves_after_list_is_full(self):
        """Once the source list is full, a further SRCNAME reply must be
        treated as "current source changed", not another list entry -
        this used to stay None forever because !SRC? carries no name at
        all to fall back on."""

        def test_function(client: Receiver):
            assert client.source == "Optical"

        await self._receive(
            [
                "!SRCCOUNT(2)",
                '!SRCNAME(0,"HDMI")',
                '!SRCNAME(1,"Optical")',
                '!SRCNAME(1,"Optical")',
            ],
            test_function,
        )

    async def _receive(self, commands_received, test_function):
        """Feed raw TDAI-shaped messages to a TDAI-1120 receiver."""
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            protocol._on_connection_lost = proto._on_connection_lost
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.TDAI_1120)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback("BAL", self._callback)
            protocol.data_received(
                bytes("\r".join([*commands_received, "!BAL(0)"]) + "\r", "utf-8")
            )
            await self.future
            test_function(client)
            await client.async_disconnect()


# =============================================================================
# Message Framing
#
# Messages end with CR, but the TDAI family sends CR LF. Splitting on CR
# alone leaves the LF heading the next message, which then fails the
# leading-"!" test in LyngdorfApi._process_event and is dropped without a
# trace. Observed against a real TDAI-1120: only the first reply of the
# setup burst survived, so power, mute, volume and source all stayed None.
# =============================================================================


class TestMessageFraming:
    """Every message must survive framing, whichever terminator is used."""

    @staticmethod
    def _collect(data: bytes) -> list[str]:
        received: list[str] = []
        protocol = LyngdorfProtocol(received.append, lambda: None)
        protocol.data_received(data)
        return received

    def test_crlf_terminated_messages_all_delivered(self):
        """TDAI family: CR LF must not strand an LF on the next message."""
        assert self._collect(
            b"!DEVICE(TDAI-1120)\r\n!PWR(ON)\r\n!MUTE(OFF)\r\n!VOL(-350)\r\n"
        ) == ["!DEVICE(TDAI-1120)", "!PWR(ON)", "!MUTE(OFF)", "!VOL(-350)"]

    def test_cr_terminated_messages_all_delivered(self):
        """MP and P families: plain CR keeps working."""
        assert self._collect(b"!DEVICE(MP-60)\r!POWER(1)\r!MUTEON\r") == [
            "!DEVICE(MP-60)",
            "!POWER(1)",
            "!MUTEON",
        ]

    def test_message_split_across_packets(self):
        """A message arriving in pieces is still assembled."""
        received: list[str] = []
        protocol = LyngdorfProtocol(received.append, lambda: None)
        protocol.data_received(b"!PWR(")
        assert received == []
        protocol.data_received(b"ON)\r\n!MUTE(ON)\r\n")
        assert received == ["!PWR(ON)", "!MUTE(ON)"]

    def test_quoted_payload_is_preserved(self):
        """Stripping framing must not touch the message body."""
        assert self._collect(b'!SRCNAME(6,"A2 HT Bypass Adam")\r\n') == [
            '!SRCNAME(6,"A2 HT Bypass Adam")'
        ]
