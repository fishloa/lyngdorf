"""Shape tests for the D9 shim layer: each category's load-bearing
property, proven on a representative member. Completeness over the whole
§7 row set is tests/consumer_contract_test.py's job (Task 3)."""

import pytest

from lyngdorf._compat import DIAGNOSTICS_SHIMS, MODULE_SHIMS
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver

FAKE_IP = "127.0.0.1"


def _receiver(model: LyngdorfModel = LyngdorfModel.MP_60) -> LyngdorfReceiver:
    r = LyngdorfReceiver(FAKE_IP, model)
    r._register_callbacks()
    return r


def _dispatch_sync(r: LyngdorfReceiver, event: str) -> None:
    """Parse and dispatch a wire event synchronously, bypassing
    asyncio.create_task so tests with no event loop still work."""
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
        api = r._api
        if cmd in api._callbacks:
            for cb in api._callbacks[cmd]:
                cb(first, second)
        for cb in api._notification_callbacks:
            cb()


def _capture_writes(r: LyngdorfReceiver) -> list[str]:
    writes: list[str] = []
    r._api._writeCommand = writes.append  # type: ignore[method-assign]
    return writes


class TestReadShims:
    def test_read_shim_warns_and_delegates(self):
        r = _receiver()
        _dispatch_sync(r, "!VOL(-281)")
        with pytest.warns(DeprecationWarning, match="volume_range"):
            assert r.volume_range == r.volume.range
        with pytest.warns(DeprecationWarning, match="mute_enabled"):
            _ = r.mute_enabled

    def test_dual_duty_range_shims_keep_returning_none_for_absent_controls(self):
        """The 1.x *_range members did double duty as capability flags
        (§7 HAZARD rows): the shims preserve None-means-absent exactly."""
        tdai = _receiver(LyngdorfModel.TDAI_2170)
        with pytest.warns(DeprecationWarning):
            assert tdai.lipsync_range is None
        with pytest.warns(DeprecationWarning):
            assert tdai.trim_bass_range is None
        with pytest.warns(DeprecationWarning):
            assert tdai.zone_b_volume_range is None
        mp = _receiver()
        with pytest.warns(DeprecationWarning):
            assert mp.lipsync_range is not None

    def test_zone_b_read_shims_mirror_1x_on_a_model_without_zone_b(self):
        tdai = _receiver(LyngdorfModel.TDAI_1120)
        with pytest.warns(DeprecationWarning):
            assert tdai.zone_b_volume is None
        with pytest.warns(DeprecationWarning):
            assert tdai.zone_b_available_sources == []

    def test_read_shims_are_read_only(self):
        """D9 measured ruling: settability would buy fixtures nothing and
        would BE a property setter. AttributeError on assignment."""
        r = _receiver()
        with pytest.raises(AttributeError):
            r.mute_enabled = True  # type: ignore[misc]
        with pytest.raises(AttributeError):
            r.trim_bass = 3.0  # type: ignore[misc]


class TestSyncBodiedWriteShims:
    @pytest.mark.asyncio
    async def test_awaited_call_performs_the_action(self):
        r = _receiver()
        writes = _capture_writes(r)
        with pytest.warns(DeprecationWarning, match="set_volume"):
            await r.set_volume(-30.0)
        assert writes == ["VOL(-300)"]

    def test_unawaited_call_still_warns_and_performs_nothing(self):
        """D9's measured shape: the warning fires even when the caller
        forgets to await (an async-def shim would be a SILENT no-op
        here), and nothing is enqueued until awaited."""
        r = _receiver()
        writes = _capture_writes(r)
        with pytest.warns(DeprecationWarning, match="set_volume"):
            coro = r.set_volume(-30.0)
        assert writes == []  # returning a coroutine executes nothing
        coro.close()  # silence the never-awaited RuntimeWarning

    def test_write_shim_raises_the_1x_capability_error_on_a_wrong_model(self):
        """Zone B / trim write shims mirror 1.x on a model without the
        feature (spec §7's Zone B note): raise, do not no-op."""
        from lyngdorf.exceptions import LyngdorfInvalidValueError

        tdai = _receiver(LyngdorfModel.TDAI_2170)
        with pytest.warns(DeprecationWarning):
            with pytest.raises(LyngdorfInvalidValueError):
                tdai.set_trim_bass(3.0)


class TestStepperShims:
    @pytest.mark.asyncio
    async def test_stepper_shim_steps(self):
        r = _receiver()
        writes = _capture_writes(r)
        with pytest.warns(DeprecationWarning, match="volume_up"):
            await r.volume_up()
        assert writes == ["VOL+"]

    @pytest.mark.asyncio
    async def test_stepper_shim_preserves_warn_and_ignore_on_non_steppable(self):
        """1.x warned-and-ignored a TDAI bass step; the shim preserves
        exactly that (spec §7's trim_bass_up row): no exception, nothing
        sent."""
        tdai = _receiver(LyngdorfModel.TDAI_3400)
        writes = _capture_writes(tdai)
        with pytest.warns(DeprecationWarning, match="trim_bass_up"):
            await tdai.trim_bass_up()
        assert writes == []


class TestAlreadyAsyncAndCallbackShims:
    def test_already_async_shim_warns_and_returns_a_coroutine(self):
        """Category: shimmed_methods_already_async. These were async in
        1.x, so they are plain renames - assert resolve-and-warn and a
        coroutine back. Do NOT assert the unawaited-warning shape's
        rationale against these; it does not apply (they never had a
        sync body to lose)."""
        import inspect

        r = _receiver()
        with pytest.warns(DeprecationWarning, match="async_connect"):
            coro = r.async_connect()
        assert inspect.iscoroutine(coro)
        coro.close()

    def test_callback_shim_returns_the_unsubscribe(self):
        r = _receiver()
        calls: list[int] = []
        with pytest.warns(DeprecationWarning, match="register_notification_callback"):
            unsub = r.register_notification_callback(lambda: calls.append(1))
        _dispatch_sync(r, "!VOL(-100)")
        assert calls == [1]
        unsub()
        unsub()  # idempotent

    def test_position_callback_shim_is_a_noop_unsubscribe_without_a_player(self):
        """spec §7: no-op unsubscribe when player is None, matching 1.x
        on non-streaming models."""
        p100 = _receiver(LyngdorfModel.P_100)
        with pytest.warns(DeprecationWarning):
            unsub = p100.register_position_jump_callback(lambda ms: None)
        unsub()  # must not raise


class TestModelFeatureShims:
    def test_has_feature_methods_warn_and_delegate_to_config(self):
        with pytest.warns(DeprecationWarning, match="has_zone_b_feature"):
            assert LyngdorfModel.MP_60.has_zone_b_feature() is True
        with pytest.warns(DeprecationWarning):
            assert LyngdorfModel.TDAI_1120.has_zone_b_feature() is False


class TestModuleShimCompleteness:
    """§7-row completeness: every module-level shim in the spec appears
    in _compat, and nothing extra ships."""

    # §7's module-level shim rows, encoded as a literal set.
    # Cited from the design spec §7 (commit 20c3b9c).
    SPEC_MODULE_SHIMS = frozenset(
        {
            "Receiver",
            "async_create_receiver",
            "async_find_receiver_model",
            "async_get_device_serial",
        }
    )

    # §7's diagnostics shim row.
    SPEC_DIAGNOSTICS_SHIMS = frozenset({"async_probe_device_capabilities"})

    def test_module_shims_match_spec_exactly(self):
        """Nothing missing, nothing extra."""
        assert set(MODULE_SHIMS.keys()) == self.SPEC_MODULE_SHIMS

    def test_diagnostics_shims_match_spec_exactly(self):
        assert set(DIAGNOSTICS_SHIMS.keys()) == self.SPEC_DIAGNOSTICS_SHIMS
