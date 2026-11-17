"""Reading, Selector and Switch, their factories, and the receiver/ZoneB
objects built from them (structural capability, asserted against
ModelConfig.messages)."""

import warnings

import pytest
from conftest import RecordingRio

from lyngdorf.base import CountingNumberDict
from lyngdorf.components import build_zone_b
from lyngdorf.const import Msg
from lyngdorf.exceptions import LyngdorfInvalidValueError
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver
from lyngdorf.values import Reading, Selector, Switch, build_reading, build_selector

FAKE_IP = "127.0.0.1"


class TestSwitch:
    @pytest.mark.asyncio
    async def test_set_sends_and_value_follows_update(self):
        sent: list[bool] = []
        sw = Switch(sent.append)
        assert sw.value is None
        await sw.set(True)
        await sw.set(False)
        assert sent == [True, False]
        assert sw.value is None
        sw._update(True)
        assert sw.value is True


class TestReading:
    def test_value_follows_update_and_options_default_empty(self):
        r = Reading()
        assert r.value is None
        assert r.options == []
        r._update("PCM")
        assert r.value == "PCM"

    def test_options_come_from_the_vocabulary(self):
        assert Reading({0: "a", 1: "b"}).options == ["a", "b"]


class TestSelector:
    @pytest.mark.asyncio
    async def test_select_sends_index_and_unknown_raises_sending_nothing(self):
        sent: list[int] = []
        options = CountingNumberDict()
        sel = Selector(options, sent.append)
        options.add(0, "Apple TV")
        options.add(3, "Wonk")
        await sel.select("Wonk")
        assert sent == [3]
        with pytest.raises(LyngdorfInvalidValueError):
            await sel.select("Nope")
        assert sent == [3]

    def test_options_follow_the_counting_dict_as_it_fills(self):
        options = CountingNumberDict()
        sel = Selector(options, lambda i: None)
        assert sel.options == []
        options.count_callback("2", "")
        options.add(0, "a")
        assert sel.options == ["a"]
        options.add(1, "b")
        assert sel.options == ["a", "b"]


RECEIVER_ROWS = [
    ("source_selector", Msg.SOURCES_COUNT),
    ("sound_mode_selector", Msg.AUDIO_MODE),
    ("room_perfect_position_selector", Msg.ROOM_PERFECT_POSITION),
    ("voicing_selector", Msg.ROOM_PERFECT_VOICING),
    ("audio_information_reading", Msg.AUDIO_TYPE),
    ("video_information_reading", Msg.VIDEO_TYPE),
    ("audio_input_reading", Msg.AUDIO_IN),
    ("video_input_reading", Msg.VIDEO_IN),
    ("streaming_source_reading", Msg.STREAM_TYPE),
]
ZONE_B_ROWS = [
    ("audio_input_reading", Msg.ZONE_B_AUDIO_IN),
    ("streaming_source_reading", Msg.ZONE_B_STREAM_TYPE),
]


class TestFactories:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    @pytest.mark.parametrize("msg", [m for _, m in RECEIVER_ROWS + ZONE_B_ROWS])
    def test_build_is_none_iff_message_missing(self, model, msg):
        rio = RecordingRio(model)
        absent = msg not in model.config.messages
        assert (build_reading(rio, msg) is None) is absent
        assert (build_selector(rio, msg, lambda i: None) is None) is absent

    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_receiver_objects_match_model_config(self, model):
        r = LyngdorfReceiver(FAKE_IP, model)
        for attr, msg in RECEIVER_ROWS:
            assert (getattr(r, attr) is None) is (
                msg not in model.config.messages
            ), attr
        assert isinstance(r.power, Switch)
        assert isinstance(r.mute, Switch)

    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_zone_b_objects_match_model_config(self, model):
        zb = build_zone_b(RecordingRio(model))
        if zb is None:
            assert not model.config.has_zone_b
            return
        for attr, msg in ZONE_B_ROWS:
            assert (getattr(zb, attr) is None) is (msg not in model.config.messages)
        assert isinstance(zb.source_selector, Selector)
        assert isinstance(zb.power, Switch)
        assert isinstance(zb.mute, Switch)

    def test_anchors(self):
        mp = LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60)
        for attr, _ in RECEIVER_ROWS:
            assert getattr(mp, attr) is not None
        tdai = LyngdorfReceiver(FAKE_IP, LyngdorfModel.TDAI_1120)
        assert tdai.sound_mode_selector is None
        assert tdai.audio_information_reading is None
        assert tdai.video_input_reading is None
        assert tdai.voicing_selector is not None
        assert (
            LyngdorfReceiver(FAKE_IP, LyngdorfModel.TDAI_2170).source_selector is None
        )

    def test_reading_options_are_the_model_vocabularies(self):
        config = LyngdorfModel.MP_60.config
        r = LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60)
        assert r.audio_input_reading.options == list(config.audio_inputs.values())
        assert r.video_input_reading.options == list(config.video_inputs.values())
        assert r.streaming_source_reading.options == list(config.stream_types.values())
        assert r.audio_information_reading.options == []
        assert r.video_information_reading.options == []


def _prepared(model):
    r = LyngdorfReceiver(FAKE_IP, model)
    r._register_callbacks()
    writes: list[str] = []
    r._api._writeCommand = writes.append  # type: ignore[method-assign]
    return r, writes


def _event(r, event):
    from receiver_test import _process_event

    _process_event(r, event)


MP60_EVENTS = [
    ('!SRC(0)"Apple TV"', "source_selector", "source"),
    ('!AUDMODE(1)"Dolby"', "sound_mode_selector", "sound_mode"),
    ('!RPFOC(1)"Focus 1"', "room_perfect_position_selector", "room_perfect_position"),
    ('!RPVOI(1)"Voicing 1"', "voicing_selector", "voicing"),
    ('!AUDTYPE("PCM 2.0")', "audio_information_reading", "audio_information"),
    ('!VIDTYPE("4K")', "video_information_reading", "video_information"),
    ("!AUDIN(1)", "audio_input_reading", "audio_input"),
    ("!VIDIN(1)", "video_input_reading", "video_input"),
    ("!STREAMTYPE(1)", "streaming_source_reading", "streaming_source"),
]


class TestBehaviourMP60:
    @pytest.mark.parametrize("event,attr,old", MP60_EVENTS)
    def test_object_value_equals_flat_property(self, event, attr, old):
        r, _ = _prepared(LyngdorfModel.MP_60)
        counts = {
            "source_selector": ("SRCCOUNT", r._sources),
            "sound_mode_selector": ("AUDMODECOUNT", r._sound_modes),
            "room_perfect_position_selector": ("RPFOCCOUNT", r._room_perfect_positions),
            "voicing_selector": ("RPVOICOUNT", r._voicings),
        }
        if attr in counts:
            d = counts[attr][1]
            d.count = 2
            d.add(0, "x")
            d.add(1, "y")
        _event(r, event)
        value = getattr(r, attr).value
        assert value is not None
        with pytest.warns(DeprecationWarning):
            assert getattr(r, old) == value

    def test_zone_b_events(self):
        r, _ = _prepared(LyngdorfModel.MP_60)
        zb = r.zone_b
        zb._sources.count = 1
        zb._sources.add(0, "x")
        _event(r, '!ZSRC(0)"Apple TV"')
        _event(r, "!ZAUDIN(1)")
        _event(r, "!ZSTREAMTYPE(1)")
        _event(r, "!ZMUTEON")
        _event(r, "!POWERZONE2(1)")
        assert zb.source_selector.value == "Apple TV"
        assert zb.audio_input_reading.value is not None
        assert zb.streaming_source_reading.value is not None
        assert zb.mute.value is True
        assert zb.power.value is True

    def test_mute_switch_on_every_family(self):
        for model, on, off in (
            (LyngdorfModel.MP_60, "!MUTEON", "!MUTEOFF"),
            (LyngdorfModel.TDAI_3400, "!MUTE(ON)", "!MUTE(OFF)"),
        ):
            r, _ = _prepared(model)
            _event(r, on)
            assert r.mute.value is True
            _event(r, off)
            assert r.mute.value is False

    def test_2170_keeps_fixed_source_without_selector(self):
        r, _ = _prepared(LyngdorfModel.TDAI_2170)
        _event(r, "!SRCENABLED(0011)")
        _event(r, "!SRC(0)")
        assert r.source_selector is None
        with pytest.warns(DeprecationWarning):
            assert r.source == r._sources[0]


class TestDeprecations:
    def test_each_old_name_warns_once_with_replacement(self):
        r, _ = _prepared(LyngdorfModel.MP_60)
        zb = r.zone_b
        reads = [
            (r, "power_on", "power"),
            (r, "muted", "mute"),
            (r, "source", "source_selector"),
            (r, "sources", "source_selector"),
            (r, "sound_mode", "sound_mode_selector"),
            (r, "sound_modes", "sound_mode_selector"),
            (r, "room_perfect_position", "room_perfect_position_selector"),
            (r, "room_perfect_positions", "room_perfect_position_selector"),
            (r, "voicing", "voicing_selector"),
            (r, "voicings", "voicing_selector"),
            (r, "audio_information", "audio_information_reading"),
            (r, "video_information", "video_information_reading"),
            (r, "audio_input", "audio_input_reading"),
            (r, "audio_inputs", "audio_input_reading"),
            (r, "video_input", "video_input_reading"),
            (r, "video_inputs", "video_input_reading"),
            (r, "streaming_source", "streaming_source_reading"),
            (r, "stream_types", "streaming_source_reading"),
            (zb, "power_on", "power"),
            (zb, "muted", "mute"),
            (zb, "source", "source_selector"),
            (zb, "sources", "source_selector"),
            (zb, "audio_input", "audio_input_reading"),
            (zb, "streaming_source", "streaming_source_reading"),
        ]
        for owner, name, new in reads:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                getattr(owner, name)
            assert len(w) == 1, name
            assert issubclass(w[0].category, DeprecationWarning)
            assert new in str(w[0].message) and "3.0" in str(w[0].message), name

    @pytest.mark.asyncio
    async def test_old_setters_warn_and_still_send(self):
        r, writes = _prepared(LyngdorfModel.MP_60)
        r._sources.add(0, "A")
        r._sound_modes.add(0, "S")
        r._room_perfect_positions.add(0, "P")
        r._voicings.add(0, "V")
        zb = r.zone_b
        zb._sources.add(0, "Z")
        calls = [
            (r.set_power(True), "POWERONMAIN"),
            (r.set_muted(True), "MUTEON"),
            (r.set_source("A"), "SRC(0)"),
            (r.set_sound_mode("S"), "AUDMODE(0)"),
            (r.set_room_perfect_position("P"), "RPFOC(0)"),
            (r.set_voicing("V"), "RPVOI(0)"),
            (zb.set_power(True), "POWERONZONE2"),
            (zb.set_muted(True), "ZMUTEON"),
            (zb.set_source("Z"), "ZSRC(0)"),
        ]
        for coro, wire in calls:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                await coro
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert writes[-1] == wire

    def test_tdai_1120_flat_names_still_answer_without_objects(self):
        r, _ = _prepared(LyngdorfModel.TDAI_1120)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert r.sound_mode is None
            assert r.sound_modes == []
            assert r.audio_information is None
            assert r.video_inputs == list(
                LyngdorfModel.TDAI_1120.config.video_inputs.values()
            )
