"""Assembly tests for LyngdorfReceiver (spec §2.2): per-model structural
capability, wire-event routing into components, write round-trips, and
the on_change contract. The full behavioural suite arrives in Task 4's
port; these pin the assembly itself."""

import pytest

from lyngdorf.const import Msg
from lyngdorf.controls import SteppableControl, Trim
from lyngdorf.exceptions import LyngdorfInvalidValueError
from lyngdorf.models import LyngdorfModel, NumericRange
from lyngdorf.receiver import LyngdorfReceiver

FAKE_IP = "127.0.0.1"


def _prepared(model: LyngdorfModel) -> tuple[LyngdorfReceiver, list[str]]:
    """A receiver with callbacks registered and wire writes captured -
    no socket anywhere."""
    receiver = LyngdorfReceiver(FAKE_IP, model)
    receiver._register_callbacks()
    writes: list[str] = []
    receiver._api._writeCommand = writes.append  # type: ignore[method-assign]
    return receiver, writes


def _process_event(receiver: LyngdorfReceiver, event: str) -> None:
    """Parse and dispatch a wire event synchronously for testing.

    WP2's RioClient._process_event dispatches via asyncio.create_task;
    this helper extracts the parsing and dispatches callbacks directly
    so tests with no event loop still pass."""
    message = event
    if message.startswith("!"):
        message = message[1:]
        cmd = ""
        first = ""
        second = ""
        open_index = message.find("(")
        close_index = message.find(")", open_index + 1) if open_index > 1 else -1
        if close_index > open_index:
            cmd = message[:open_index]
            first = message[open_index + 1 : close_index]
            second = message[close_index + 1 :]
        else:
            cmd = message
        if len(second) > 0 and second.startswith('"') and second.endswith('"'):
            second = second[1:-1]
        # Skip PONG
        try:
            pong_cmd = receiver._model.config.lookup_command(Msg.PONG)
        except KeyError:
            pong_cmd = None
        if cmd == pong_cmd:
            return
        # Run callbacks synchronously
        api = receiver._api
        if cmd in api._callbacks:
            for cb in api._callbacks[cmd]:
                cb(first, second)
        # Run notification callbacks synchronously
        for cb in api._notification_callbacks:
            cb()


class TestStructuralCapability:
    @pytest.mark.parametrize("model", list(LyngdorfModel))
    def test_components_match_model_config(self, model):
        """spec §5 tier 1, regenerated from ModelConfig for all ten
        models: a missing feature is a None attribute or an absent
        mapping key, never a method that raises."""
        r = LyngdorfReceiver(FAKE_IP, model)
        config = model.config
        assert isinstance(r.volume, SteppableControl)
        assert (r.zone_b is not None) is config.has_zone_b
        assert (r.player is not None) is config.has_streaming
        assert (r.remote is not None) is bool(config.available_remote_keys())
        assert (r.lipsync is not None) is (config.lipsync_default_range is not None)
        expected_bands = {
            band
            for band, field_name in (
                (Trim.BASS, "trim_bass_range"),
                (Trim.TREBLE, "trim_treble_range"),
                (Trim.CENTER, "trim_centre_range"),
                (Trim.HEIGHT, "trim_height_range"),
                (Trim.LFE, "trim_lfe_range"),
                (Trim.SURROUND, "trim_surround_range"),
            )
            if getattr(config, field_name) is not None
        }
        assert set(r.trims) == expected_bands

    def test_host_is_str_and_informational_tables_come_from_config(self):
        r = LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60)
        assert r.host == FAKE_IP  # str, not str | None (spec §2.2)
        assert r.stream_types == list(LyngdorfModel.MP_60.config.stream_types.values())
        assert r.audio_inputs == list(LyngdorfModel.MP_60.config.audio_inputs.values())
        assert r.video_inputs == list(LyngdorfModel.MP_60.config.video_inputs.values())


class TestWireEventRouting:
    def test_volume_event_updates_the_control(self):
        r, _ = _prepared(LyngdorfModel.MP_60)
        _process_event(r, "!VOL(-281)")
        assert r.volume.value == -28.1

    def test_trim_events_update_the_mapping_with_the_model_scale(self):
        """#41 end to end at the receiver: the same +3 dB arrives as
        TRIMBASS(30) on MP (tenths) and BASS(3) on TDAI (whole dB)."""
        mp, _ = _prepared(LyngdorfModel.MP_60)
        _process_event(mp, "!TRIMBASS(30)")
        assert mp.trims[Trim.BASS].value == 3.0

        tdai, _ = _prepared(LyngdorfModel.TDAI_3400)
        _process_event(tdai, "!BASS(3)")
        assert tdai.trims[Trim.BASS].value == 3.0

    def test_lipsync_range_is_overwritten_by_the_live_reply(self):
        """The wire half of Plan 3's live-range contract: the seeded
        documented default is overwritten by !LIPSYNCRANGE(min,max)
        (comma-packed in one field - spec §9 item 7)."""
        r, _ = _prepared(LyngdorfModel.MP_60)
        assert r.lipsync is not None
        assert r.lipsync.range == NumericRange(min=0.0, max=500.0, step=1.0)
        _process_event(r, "!LIPSYNCRANGE(0,450)")
        assert r.lipsync.range == NumericRange(min=0.0, max=450.0, step=1.0)

    def test_zone_b_events_route_into_the_component(self):
        r, _ = _prepared(LyngdorfModel.MP_60)
        assert r.zone_b is not None
        _process_event(r, "!ZVOL(-550)")
        _process_event(r, "!ZMUTEON")
        assert r.zone_b.volume.value == -55.0
        assert r.zone_b.muted is True

    def test_power_on_requeries_mute(self):
        """#26: power cycling can silently clear mute; the power-on
        callback re-queries it (a query - never coalesced away)."""
        r, writes = _prepared(LyngdorfModel.MP_60)
        _process_event(r, "!POWER(1)")
        assert r.power_on is True
        assert "MUTE?" in writes


class TestWrites:
    @pytest.mark.asyncio
    async def test_write_round_trips(self):
        r, writes = _prepared(LyngdorfModel.MP_60)
        await r.set_power(True)
        await r.set_muted(True)
        await r.volume.set(-25.0)
        assert writes[-3:] == ["POWERONMAIN", "MUTEON", "VOL(-250)"]

    @pytest.mark.asyncio
    async def test_set_source_validates_name_and_sends_index(self):
        r, writes = _prepared(LyngdorfModel.MP_60)
        r._sources.count_callback("2", "")
        r._sources.add(0, "Apple TV")
        r._sources.add(1, "Playstation")
        await r.set_source("Playstation")
        assert writes[-1] == "SRC(1)"
        with pytest.raises(LyngdorfInvalidValueError):
            await r.set_source("Nope")

    def test_no_property_setter_exists_anywhere_on_the_class(self):
        """spec §3/D9: zero writable properties - the async rule's
        self-enforcing half. Checked over every property on the class
        (including, after Task 2, the shim mixin's)."""
        for klass in type(LyngdorfReceiver("x", LyngdorfModel.MP_60)).__mro__:
            for name, member in vars(klass).items():
                if isinstance(member, property):
                    assert member.fset is None, f"{name} has a setter"


class TestOnChange:
    def test_on_change_fires_dedupes_and_unsubscribes_idempotently(self):
        """spec §2.2/§9 item 10: duplicate registration collapses to one
        entry; the returned unsubscribe is idempotent."""
        r, _ = _prepared(LyngdorfModel.MP_60)
        calls: list[int] = []

        def cb() -> None:
            calls.append(1)

        unsub = r.on_change(cb)
        again = r.on_change(cb)  # duplicate: collapses to one entry
        _process_event(r, "!VOL(-100)")
        assert calls == [1]  # fired once, not twice
        unsub()
        again()  # second unsubscribe of the same cb: no-op, no error
        unsub()  # and repeat: still a no-op
        _process_event(r, "!VOL(-110)")
        assert calls == [1]
