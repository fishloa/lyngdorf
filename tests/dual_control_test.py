"""1.11-only: the dual float/control types and the legacy-setter guard.

Deleted with the compat layer. These cover the two things 1.11 adds that
neither 1.10 nor 2.0.0 has, so nothing else in the suite touches them.
"""

import asyncio

import pytest

from lyngdorf.controls import (
    FloatNumericControl,
    FloatSteppableControl,
    NumericControl,
    SteppableControl,
)
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver

FAKE_IP = "127.0.0.1"


def _prepared(model: LyngdorfModel = LyngdorfModel.MP_60):
    receiver = LyngdorfReceiver(FAKE_IP, model)
    receiver._register_callbacks()
    writes: list[str] = []
    receiver._api._writeCommand = writes.append  # type: ignore[method-assign]
    return receiver, writes


def _report(receiver: LyngdorfReceiver, db: float) -> None:
    """Feed a device volume report without a socket."""
    receiver._volume._update_value(db)


class TestDualNature:
    def test_volume_is_simultaneously_a_float_and_a_control(self):
        """The whole reason 1.11 exists: one name, both types, so a
        consumer's 1.x and 2.0 call sites compile against one pin."""
        r, _ = _prepared()
        _report(r, -25.0)
        volume = r.volume
        assert isinstance(volume, float)
        assert isinstance(volume, SteppableControl)
        assert isinstance(volume, NumericControl)

    def test_it_behaves_as_an_ordinary_float(self):
        """Not a look-alike with a __float__ - a real float subclass, so
        arithmetic, comparison, formatting and dict keying all work. 1.x
        consumers do all four."""
        r, _ = _prepared()
        _report(r, -25.0)
        volume = r.volume
        assert volume == -25.0
        assert volume + 5 == -20.0
        assert volume < 0
        assert f"{volume:.1f}" == "-25.0"
        assert {volume: "x"}[-25.0] == "x"

    def test_it_behaves_as_an_ordinary_control(self):
        r, writes = _prepared()
        _report(r, -25.0)
        volume = r.volume
        assert volume is not None
        assert volume.value == -25.0
        assert volume.range == r._volume.range
        asyncio.run(volume.set(-30.0))
        asyncio.run(volume.up())
        assert writes[-2:] == ["VOL(-300)", "VOL+"]

    def test_lipsync_is_dual_but_not_steppable(self):
        """Steppability stays structural. The dual type must not quietly
        widen the surface by handing lipsync an up() the device has no
        command for."""
        r, _ = _prepared()
        assert r._lipsync is not None
        r._lipsync._update_value(80.0)
        lipsync = r.lipsync
        assert isinstance(lipsync, FloatNumericControl)
        assert not isinstance(lipsync, FloatSteppableControl)
        assert not hasattr(lipsync, "up")


class TestSnapshotSemantics:
    def test_each_access_reflects_the_current_value(self):
        """A float cannot be mutated after construction, so a single
        long-lived instance would freeze at the first reported value and
        report it forever. Each property access builds a new snapshot;
        this is the test that fails if that is ever "optimised" into a
        cached attribute."""
        r, _ = _prepared()
        _report(r, -25.0)
        first = r.volume
        _report(r, -30.0)
        second = r.volume
        assert first == -25.0
        assert second == -30.0

    def test_a_snapshot_still_writes_to_the_live_device(self):
        """Snapshots share the live control's sender, so a reference held
        across a value change still commands the device rather than
        writing into a detached copy."""
        r, writes = _prepared()
        _report(r, -25.0)
        held = r.volume
        assert held is not None
        _report(r, -30.0)
        asyncio.run(held.set(-40.0))
        assert writes[-1] == "VOL(-400)"

    def test_none_until_the_device_reports(self):
        r, _ = _prepared()
        assert r.volume is None
        _report(r, -25.0)
        assert r.volume is not None


class TestLegacySetterGuard:
    """`asyncio.Event.set()` is not thread-safe (issue #51). 1.x raced
    silently when a sync-looking setter was called off the loop; 1.11
    raises instead."""

    class _LiveTask:
        def done(self) -> bool:
            return False

    def test_raises_when_a_drain_task_is_live_and_this_thread_has_no_loop(self):
        r, _ = _prepared()
        r._api._write_queue_task = self._LiveTask()  # type: ignore[assignment]
        with pytest.warns(DeprecationWarning):
            with pytest.raises(RuntimeError, match="not thread-safe"):
                r.power_on = True

    def test_allows_the_loopless_path_the_client_documents(self):
        """Deliberately narrow. With no drain task there is no Event to
        set - _writeCommand flushes synchronously by its own documented
        fallback - so a loopless caller must NOT be blocked, or the
        guard would break the tests and callers that already rely on it.
        """
        r, writes = _prepared()
        assert r._api._write_queue_task is None
        with pytest.warns(DeprecationWarning):
            r.power_on = True
        assert writes[-1] == "POWERONMAIN"

    def test_allows_a_setter_called_from_the_loop_thread(self):
        async def main() -> list[str]:
            r, writes = _prepared()
            r._api._write_queue_task = self._LiveTask()  # type: ignore[assignment]
            with pytest.warns(DeprecationWarning):
                r.power_on = True
            return writes

        assert asyncio.run(main())[-1] == "POWERONMAIN"


class TestRestoredSetterCoverage:
    def test_every_restored_setter_reaches_the_wire(self):
        """A setter that warns and drops the value would pass a
        "does it warn" test while doing nothing - the silent-no-op
        failure mode. Each is checked to produce a command."""
        cases = [
            ("power_on", True),
            ("mute_enabled", True),
            ("volume", -25.0),
            ("lipsync", 80.0),
            ("trim_bass", 3.0),
            ("zone_b_volume", -30.0),
            ("zone_b_power_on", True),
            ("zone_b_mute_enabled", True),
        ]
        for name, value in cases:
            r, writes = _prepared()
            with pytest.warns(DeprecationWarning):
                setattr(r, name, value)
            assert writes, f"{name} warned but wrote nothing"

    def test_selection_setters_validate_like_their_async_twins(self):
        """Same exception type and the same rejection, so a consumer's
        error handling behaves identically on either surface."""
        from lyngdorf.exceptions import LyngdorfInvalidValueError

        r, _ = _prepared()
        r._sources.count_callback("1", "")
        r._sources.add(0, "Apple TV")
        with pytest.warns(DeprecationWarning):
            with pytest.raises(LyngdorfInvalidValueError):
                r.source = "Nope"

    def test_unsupported_trim_raises_rather_than_silently_dropping(self):
        from lyngdorf.exceptions import LyngdorfInvalidValueError

        r, _ = _prepared(LyngdorfModel.TDAI_1120)
        from lyngdorf.controls import Trim

        assert Trim.CENTER not in r.trims
        with pytest.warns(DeprecationWarning):
            with pytest.raises(LyngdorfInvalidValueError):
                r.trim_centre = 3.0
