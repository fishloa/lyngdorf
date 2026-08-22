import inspect
from unittest import mock

import pytest

from lyngdorf.const import Msg
from lyngdorf.diagnostics import (
    SAFE_QUERY_MESSAGES,
    CapabilityProbeReport,
    ProbeResult,
    _all_candidate_tokens,
    probe_capabilities,
)
from lyngdorf.models import LyngdorfModel

FAKE_IP = "0.0.0.0"


class TestSafeQueryMessages:
    """The probe must never send an action-only command verbatim."""

    def test_excludes_power_and_mute_actions(self):
        for msg in (
            Msg.POWER_ON,
            Msg.POWER_OFF,
            Msg.MUTE_ON,
            Msg.MUTE_OFF,
            Msg.ZONE_B_POWER_ON,
            Msg.ZONE_B_POWER_OFF,
            Msg.ZONE_B_MUTE_ON,
            Msg.ZONE_B_MUTE_OFF,
        ):
            assert msg not in SAFE_QUERY_MESSAGES

    def test_includes_state_queries(self):
        for msg in (Msg.DEVICE, Msg.POWER, Msg.VOLUME, Msg.MUTE, Msg.SOURCE):
            assert msg in SAFE_QUERY_MESSAGES


class TestAllCandidateTokens:
    def test_returns_sorted_unique_tokens(self):
        tokens = _all_candidate_tokens()
        assert tokens == sorted(set(tokens))
        assert len(tokens) > 0

    def test_excludes_action_only_commands(self):
        tokens = _all_candidate_tokens()
        # These are action-only command strings for at least one model and
        # must never appear as a probe candidate.
        assert "MUTEON" not in tokens
        assert "MUTEOFF" not in tokens
        assert "POWERONMAIN" not in tokens
        assert "POWEROFFMAIN" not in tokens

    def test_includes_known_query_commands(self):
        tokens = _all_candidate_tokens()
        assert "DEVICE" in tokens
        assert "VOL" in tokens
        assert "PWR" in tokens


class TestProbeResult:
    def test_responded_true_when_response_present(self):
        assert ProbeResult(
            command="VOL", response="!VOL(0)", known_to_model=True
        ).responded

    def test_responded_false_when_no_response(self):
        assert not ProbeResult(
            command="VOL", response=None, known_to_model=True
        ).responded


class TestCapabilityProbeReport:
    def _report(self):
        return CapabilityProbeReport(
            host=FAKE_IP,
            model=LyngdorfModel.TDAI_3400,
            results=[
                ProbeResult(
                    command="DEVICE", response="!DEVICE(TDAI-3400)", known_to_model=True
                ),
                ProbeResult(command="VOL", response="!VOL(0)", known_to_model=True),
                ProbeResult(command="PWR", response=None, known_to_model=True),
                ProbeResult(
                    command="SPEAKER", response="!SPEAKER(0)", known_to_model=False
                ),
            ],
        )

    def test_working_commands(self):
        report = self._report()
        commands = {r.command for r in report.working_commands}
        assert commands == {"DEVICE", "VOL", "SPEAKER"}

    def test_undocumented_working_commands(self):
        report = self._report()
        commands = {r.command for r in report.undocumented_working_commands}
        assert commands == {"SPEAKER"}

    def test_documented_broken_commands(self):
        report = self._report()
        commands = {r.command for r in report.documented_broken_commands}
        assert commands == {"PWR"}

    def test_to_dict(self):
        d = self._report().to_dict()
        assert d["host"] == FAKE_IP
        assert d["model"] == "TDAI_3400"
        assert d["working_commands"]["VOL"] == "!VOL(0)"
        assert "SPEAKER" in d["undocumented_working_commands"]
        assert d["documented_broken_commands"] == ["PWR"]

    def test_to_text_includes_all_sections(self):
        text = self._report().to_text()
        assert "Working commands" in text
        assert "Undocumented working commands" in text
        assert "Documented but broken commands" in text
        assert "SPEAKER" in text


class TestAsyncProbeDeviceCapabilities:
    @pytest.mark.asyncio
    async def test_probe_records_replies_and_timeouts(self):
        writer = mock.AsyncMock()
        writer.write = mock.Mock()
        writer.close = mock.Mock()
        writer.wait_closed = mock.AsyncMock()

        reader = mock.AsyncMock()
        device_served = False

        async def fake_read(_n):
            nonlocal device_served
            token = writer.write.call_args[0][0].decode()
            if "!DEVICE?" in token and not device_served:
                device_served = True
                return b"!DEVICE(TDAI-3400)\r"
            raise TimeoutError

        reader.read = fake_read

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            return_value=(reader, writer),
        ):
            report = await probe_capabilities(
                FAKE_IP,
                model=LyngdorfModel.TDAI_3400,
                per_command_timeout=0.01,
            )

        device_result = next(r for r in report.results if r.command == "DEVICE")
        assert device_result.response == "!DEVICE(TDAI-3400)"
        assert device_result.known_to_model is True

        pwr_result = next(r for r in report.results if r.command == "PWR")
        assert pwr_result.response is None
        assert pwr_result.known_to_model is True

        writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_probe_without_model_marks_nothing_as_known(self):
        writer = mock.AsyncMock()
        writer.write = mock.Mock()
        writer.close = mock.Mock()
        writer.wait_closed = mock.AsyncMock()

        reader = mock.AsyncMock()

        async def fake_read(_n):
            raise TimeoutError

        reader.read = fake_read

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            return_value=(reader, writer),
        ):
            report = await probe_capabilities(
                FAKE_IP, model=None, per_command_timeout=0.01
            )

        assert report.model is None
        assert all(not r.known_to_model for r in report.results)

    @pytest.mark.asyncio
    async def test_probe_drains_multiline_reply_before_next_command(self):
        """A burst reply delivered across two reads (e.g. a "?LIST" query's
        COUNT line then item lines) must be fully drained into the SAME
        command's result, not bleed into the next command's read."""
        writer = mock.AsyncMock()
        writer.write = mock.Mock()
        writer.close = mock.Mock()
        writer.wait_closed = mock.AsyncMock()

        reader = mock.AsyncMock()
        srclist_calls = {"n": 0}

        async def fake_read(_n):
            token = writer.write.call_args[0][0].decode()
            if "!SRCLIST?" in token:
                srclist_calls["n"] += 1
                if srclist_calls["n"] == 1:
                    return b"!SRCCOUNT(1)\r"
                if srclist_calls["n"] == 2:
                    return b'!SRC(0)"TV"\r'
            raise TimeoutError

        reader.read = fake_read

        with mock.patch(
            "asyncio.open_connection",
            new_callable=mock.AsyncMock,
            return_value=(reader, writer),
        ):
            report = await probe_capabilities(
                FAKE_IP,
                model=LyngdorfModel.TDAI_1120,
                per_command_timeout=0.05,
            )

        srclist_result = next(r for r in report.results if r.command == "SRCLIST")
        assert srclist_result.response == '!SRCCOUNT(1)\r!SRC(0)"TV"'
        assert srclist_result.reply_key == "SRCCOUNT"
        assert srclist_result.key_mismatch is True

        # The burst must not have bled into whatever command was probed next.
        next_index = report.results.index(srclist_result) + 1
        assert report.results[next_index].response is None


class TestReplyKeyMismatch:
    def test_detects_mismatched_reply_key(self):
        r = ProbeResult(
            command="TRIMTREB", response="!TRIMTREBLE(0)", known_to_model=True
        )
        assert r.reply_key == "TRIMTREBLE"
        assert r.key_mismatch is True

    def test_no_mismatch_when_reply_echoes_command(self):
        r = ProbeResult(command="VOL", response="!VOL(0)", known_to_model=True)
        assert r.reply_key == "VOL"
        assert r.key_mismatch is False

    def test_no_mismatch_when_no_response(self):
        r = ProbeResult(command="VOL", response=None, known_to_model=True)
        assert r.reply_key is None
        assert r.key_mismatch is False

    def test_report_collects_mismatches(self):
        report = CapabilityProbeReport(
            host=FAKE_IP,
            model=None,
            results=[
                ProbeResult(command="VOL", response="!VOL(0)", known_to_model=True),
                ProbeResult(
                    command="TRIMTREB", response="!TRIMTREBLE(0)", known_to_model=True
                ),
            ],
        )
        assert [r.command for r in report.reply_key_mismatches] == ["TRIMTREB"]
        assert report.to_dict()["reply_key_mismatches"] == {"TRIMTREB": "TRIMTREBLE"}
        assert "TRIMTREB" in report.to_text()


class TestModelCapabilities:
    def test_capabilities_dict_covers_every_msg(self):
        caps = LyngdorfModel.MP_60.capabilities
        assert set(caps.keys()) == set(Msg)

    def test_capabilities_matches_supports_message(self):
        for msg in Msg:
            assert LyngdorfModel.TDAI_2170.capabilities[
                msg
            ] == LyngdorfModel.TDAI_2170.supports_message(msg)

    def test_supports_message_true_for_zone_b_on_mp(self):
        assert LyngdorfModel.MP_60.supports_message(Msg.ZONE_B_VOLUME) is True

    def test_supports_message_false_for_zone_b_on_tdai(self):
        assert LyngdorfModel.TDAI_3400.supports_message(Msg.ZONE_B_VOLUME) is False


class TestDiagnosticsShim:
    def test_probe_capabilities_is_the_new_name(self):
        from lyngdorf import diagnostics

        assert inspect.iscoroutinefunction(diagnostics.probe_capabilities)

    def test_old_name_is_a_warning_shim(self):
        from lyngdorf import diagnostics

        with pytest.warns(DeprecationWarning, match="probe_capabilities"):
            fn = diagnostics.async_probe_device_capabilities
        assert fn is diagnostics.probe_capabilities
