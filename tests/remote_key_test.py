"""Tests for the remote-control key API (issue #46).

Before this, `Msg.CURSOR_UP`/`Msg.MENU`/etc. lived in the bidirectional
`Msg` registry with no callback ever registered and nothing that could
send them - dead code, checked only by lookup-only assertions
(`tests/basic_wiring_test.py`, before this issue) that verified the table
was right without verifying the feature was reachable at all. These tests
exercise the feature end-to-end: `Receiver.send_remote_commands()`/
`press()` all the way down to what actually reaches the (mocked)
transport, not just a dict lookup.

Fixtures are local to this file rather than added to `tests/conftest.py`,
which another agent owns concurrently for issue #45.
"""

from unittest import mock

import pytest
from conftest import flush_write_queue

from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel
from lyngdorf.device import (
    MP40Receiver,
    MP50Receiver,
    MP60Receiver,
    P100Receiver,
    P200Receiver,
    P300Receiver,
    Receiver,
    TDAI1120Receiver,
    TDAI2170Receiver,
    TDAI2210Receiver,
    TDAI3400Receiver,
)
from lyngdorf.exceptions import LyngdorfUnsupportedError
from lyngdorf.remote import RemoteKey, RemoteKeyTable, resolve_remote_key

FAKE_IP = "0.0.0.0"

# Every key both the MP and P families have. The MP manuals
# (docs/mp-40.md, docs/mp-50.md, docs/mp-60.md) omit `!BACK` and document
# only `!EXIT`, but that is a documentation error, not a hardware gap: a
# real MP-60 on firmware 5.4.2 echoes `#BACK` at `!VERB(2)` (which stays
# silent for anything it does not recognise) while rejecting deliberately
# malformed controls in the same session - see MP_REMOTE_KEYS in
# mp_series.py for the measurement. The MP and P key sets are therefore
# identical, not differentiated by BACK as originally assumed.
EXPECTED_KEYS = frozenset(
    {
        RemoteKey.UP,
        RemoteKey.DOWN,
        RemoteKey.LEFT,
        RemoteKey.RIGHT,
        RemoteKey.ENTER,
        RemoteKey.BACK,
        RemoteKey.MENU,
        RemoteKey.INFO,
        RemoteKey.SETTINGS,
        RemoteKey.EXIT,
        RemoteKey.MULTIVIEW,
        RemoteKey.DIGIT_0,
        RemoteKey.DIGIT_1,
        RemoteKey.DIGIT_2,
        RemoteKey.DIGIT_3,
        RemoteKey.DIGIT_4,
        RemoteKey.DIGIT_5,
        RemoteKey.DIGIT_6,
        RemoteKey.DIGIT_7,
        RemoteKey.DIGIT_8,
        RemoteKey.DIGIT_9,
    }
)


def _sent(receiver: Receiver) -> list[str]:
    """Every command that actually reached the mocked transport, in order."""
    return [call.args[0] for call in receiver._api._protocol.write.call_args_list]


def _wire(receiver: Receiver) -> Receiver:
    """Attach a mocked transport, bypassing a real connection."""
    receiver._api._protocol = mock.Mock()
    return receiver


class TestPerModelCapability:
    """`available_remote_keys`/`has_remote_keys` are explicit per model,
    never inferred from anything else - see ModelConfig.remote_keys."""

    @pytest.mark.parametrize("receiver_cls", [MP40Receiver, MP50Receiver, MP60Receiver])
    def test_mp_models_have_the_full_key_set(self, receiver_cls):
        receiver = receiver_cls(FAKE_IP)
        assert receiver.available_remote_keys == EXPECTED_KEYS
        assert receiver.has_remote_keys is True

    @pytest.mark.parametrize("receiver_cls", [P100Receiver, P200Receiver, P300Receiver])
    def test_p_models_have_the_full_key_set(self, receiver_cls):
        receiver = receiver_cls(FAKE_IP)
        assert receiver.available_remote_keys == EXPECTED_KEYS
        assert receiver.has_remote_keys is True

    def test_mp_and_p_key_sets_are_identical(self):
        """BACK was originally thought to be P-only, but a real MP-60
        accepts it too (see MP_REMOTE_KEYS in mp_series.py) - the two
        families' key sets do not actually differ at all."""
        assert (
            MP60Receiver(FAKE_IP).available_remote_keys
            == P100Receiver(FAKE_IP).available_remote_keys
        )

    @pytest.mark.parametrize(
        "receiver_cls",
        [TDAI1120Receiver, TDAI2170Receiver, TDAI2210Receiver, TDAI3400Receiver],
    )
    def test_tdai_models_have_no_remote_keys_at_all(self, receiver_cls):
        receiver = receiver_cls(FAKE_IP)
        assert receiver.available_remote_keys == frozenset()
        assert receiver.has_remote_keys is False

    def test_mp_has_back(self):
        """No MP manual documents `!BACK`, but a real MP-60 on firmware
        5.4.2 accepts it (see MP_REMOTE_KEYS in mp_series.py for the
        `!VERB(2)` echo measurement) - the manual is wrong, not the
        table. Do not "fix" this back to excluding BACK."""
        receiver = MP60Receiver(FAKE_IP)
        assert RemoteKey.BACK in receiver.available_remote_keys

    def test_mp_has_exit(self):
        """The other half of the same defect: MP models must have EXIT,
        which every MP manual documents and the old code never mapped."""
        receiver = MP60Receiver(FAKE_IP)
        assert RemoteKey.EXIT in receiver.available_remote_keys

    def test_lyngdorf_model_enum_agrees_with_receiver(self):
        """The capability lives on ModelConfig/LyngdorfModel; Receiver
        just forwards it - assert the two never diverge."""
        assert (
            LyngdorfModel.MP_60.available_remote_keys()
            == MP60Receiver(FAKE_IP).available_remote_keys
        )
        assert LyngdorfModel.TDAI_1120.has_remote_keys_feature() is False


class TestResolveRemoteKey:
    """Unit coverage for `resolve_remote_key` itself, independent of any
    model/capability check."""

    @pytest.mark.parametrize("text", ["up", "UP", "Up", " up ", "uP"])
    def test_case_and_whitespace_insensitive(self, text):
        assert resolve_remote_key(text) is RemoteKey.UP

    def test_digit_strings_resolve(self):
        assert resolve_remote_key("5") is RemoteKey.DIGIT_5

    def test_remote_key_passed_through_unchanged(self):
        assert resolve_remote_key(RemoteKey.ENTER) is RemoteKey.ENTER

    def test_unknown_string_resolves_to_none(self):
        assert resolve_remote_key("bogus") is None

    def test_empty_string_resolves_to_none(self):
        assert resolve_remote_key("") is None


class TestRemoteKeyTable:
    """Unit coverage for `RemoteKeyTable` - the digit-formatter shape in
    particular, since `!NUM(X)` must be one parameterised command, not
    ten literal dict entries."""

    def test_empty_table_has_no_keys(self):
        table = RemoteKeyTable()
        assert table.available_keys() == frozenset()

    def test_digit_format_expands_to_all_ten_digits(self):
        table = RemoteKeyTable(digit_format="NUM({})")
        assert table.available_keys() == frozenset(
            {
                RemoteKey.DIGIT_0,
                RemoteKey.DIGIT_1,
                RemoteKey.DIGIT_2,
                RemoteKey.DIGIT_3,
                RemoteKey.DIGIT_4,
                RemoteKey.DIGIT_5,
                RemoteKey.DIGIT_6,
                RemoteKey.DIGIT_7,
                RemoteKey.DIGIT_8,
                RemoteKey.DIGIT_9,
            }
        )
        assert table.command_for(RemoteKey.DIGIT_7) == "NUM(7)"

    def test_command_for_unsupported_key_raises_keyerror(self):
        table = RemoteKeyTable(commands={RemoteKey.UP: "DIRU"})
        with pytest.raises(KeyError):
            table.command_for(RemoteKey.DOWN)

    def test_command_for_digit_without_format_raises_keyerror(self):
        table = RemoteKeyTable()
        with pytest.raises(KeyError):
            table.command_for(RemoteKey.DIGIT_0)


class TestWireCommandPerModel:
    """`press()` all the way down to the mocked transport - the actual
    wire token sent, not just what `lookup_remote_key` returns."""

    def test_mp60_exit_sends_exit(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.press(RemoteKey.EXIT)
        assert _sent(receiver) == ["!EXIT\r"]

    def test_mp60_back_sends_back(self):
        """A real MP-60 accepts `!BACK` despite no MP manual documenting
        it - see MP_REMOTE_KEYS in mp_series.py for the measurement."""
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.press(RemoteKey.BACK)
        assert _sent(receiver) == ["!BACK\r"]

    def test_p100_back_sends_back(self):
        receiver = _wire(P100Receiver(FAKE_IP))
        receiver.press(RemoteKey.BACK)
        assert _sent(receiver) == ["!BACK\r"]

    def test_p100_exit_sends_exit(self):
        receiver = _wire(P100Receiver(FAKE_IP))
        receiver.press(RemoteKey.EXIT)
        assert _sent(receiver) == ["!EXIT\r"]

    @pytest.mark.parametrize(
        "receiver_cls", [MP60Receiver, P200Receiver], ids=["mp60", "p200"]
    )
    def test_multiview_sends_multiview(self, receiver_cls):
        receiver = _wire(receiver_cls(FAKE_IP))
        receiver.press(RemoteKey.MULTIVIEW)
        assert _sent(receiver) == ["!MULTIVIEW\r"]

    def test_digit_sends_parameterised_num_command(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.press(RemoteKey.DIGIT_7)
        assert _sent(receiver) == ["!NUM(7)\r"]

    def test_settings_maps_to_setup_token(self):
        """RemoteKey.SETTINGS -> "SETUP" on the wire, matching Msg.SETTINGS'
        old mapping, not a literal "SETTINGS" token."""
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.press(RemoteKey.SETTINGS)
        assert _sent(receiver) == ["!SETUP\r"]

    def test_cursor_keys_map_to_dir_tokens(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands(
            [RemoteKey.UP, RemoteKey.DOWN, RemoteKey.LEFT, RemoteKey.RIGHT]
        )
        assert _sent(receiver) == ["!DIRU\r", "!DIRD\r", "!DIRL\r", "!DIRR\r"]

    def test_tdai_has_no_wire_command_for_anything(self):
        receiver = _wire(TDAI1120Receiver(FAKE_IP))
        with pytest.raises(LyngdorfUnsupportedError):
            receiver.press(RemoteKey.UP)
        assert _sent(receiver) == []


class TestSendRemoteCommandsStrings:
    """`send_remote_commands` is the HA-shaped entry point - it must
    accept plain strings, case-insensitively, exactly like
    `RemoteEntity.async_send_command` is handed."""

    @pytest.mark.parametrize("text", ["up", "UP", "Up"])
    def test_case_insensitive_string_resolves_and_sends(self, text):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands([text])
        assert _sent(receiver) == ["!DIRU\r"]

    def test_mixed_strings_and_enum_members(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands(["up", RemoteKey.DOWN, "enter"])
        assert _sent(receiver) == ["!DIRU\r", "!DIRD\r", "!ENTER\r"]

    def test_digit_strings_send_num_commands_in_order(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands([str(d) for d in range(10)])
        assert _sent(receiver) == [f"!NUM({d})\r" for d in range(10)]


class TestBatchValidatesBeforeSending:
    """A typo (or an unsupported key) anywhere in the batch must raise
    before ANY of the batch reaches the device - a caller navigating a
    six-command sequence must never get the device halfway through a
    menu because item 5 was misspelled."""

    def test_unknown_command_raises_and_sends_nothing(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        with pytest.raises(LyngdorfUnsupportedError):
            receiver.send_remote_commands(["up", "bogus", "down"])
        assert _sent(receiver) == []

    def test_bad_item_late_in_batch_still_sends_nothing(self):
        """The bad item is 5th of 6 - even the four good ones before it
        must not have gone out."""
        receiver = _wire(MP60Receiver(FAKE_IP))
        with pytest.raises(LyngdorfUnsupportedError):
            receiver.send_remote_commands(
                ["up", "up", "down", "enter", "bogus", "menu"]
            )
        assert _sent(receiver) == []

    def test_unsupported_key_for_this_model_raises_and_sends_nothing(self):
        """UP resolves to a real RemoteKey, but this TDAI model has no
        remote keys at all - still must raise before sending, same as an
        unresolvable string."""
        receiver = _wire(TDAI1120Receiver(FAKE_IP))
        with pytest.raises(LyngdorfUnsupportedError):
            receiver.send_remote_commands(["up"])
        assert _sent(receiver) == []

    def test_error_message_names_the_bad_value_and_available_keys(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        with pytest.raises(LyngdorfUnsupportedError) as exc_info:
            receiver.send_remote_commands(["bogus"])
        message = str(exc_info.value)
        assert "bogus" in message
        assert "exit" in message  # something MP60 does support


class TestNumRepeats:
    """`num_repeats` repeats the WHOLE resolved sequence as a block, not
    each individual command - matching Home Assistant's own
    interpretation (see `broadlink`'s `remote.py` and `harmony`'s
    `data.py`, both of which repeat the sequence rather than each
    command) - see `Receiver.send_remote_commands`."""

    def test_num_repeats_enqueues_that_many_presses(self):
        """A single-key batch cannot distinguish "repeat the sequence"
        from "repeat each key" - both nestings produce the same output
        here. See test_multi_key_batch_repeats_the_whole_sequence below
        for the test that actually pins the nesting down."""
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands(["up"], num_repeats=3)
        assert _sent(receiver) == ["!DIRU\r"] * 3

    def test_multi_key_batch_repeats_the_whole_sequence(self):
        """The defect this pins down: `num_repeats=2` over `["up",
        "down"]` must send `up down up down` (the sequence repeated as a
        block), never `up up down down` (each key repeated in place) -
        the digit-entry equivalent is `["1","2","3"]` reaching the
        device as `123123`, not `112233`."""
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands(["up", "down"], num_repeats=2)
        assert _sent(receiver) == ["!DIRU\r", "!DIRD\r", "!DIRU\r", "!DIRD\r"]

    def test_digit_sequence_repeats_as_a_block_not_per_digit(self):
        """The exact scenario from the issue: entering "123" twice must
        produce "123123" on the wire, not "112233"."""
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands(["1", "2", "3"], num_repeats=2)
        assert _sent(receiver) == [
            "!NUM(1)\r",
            "!NUM(2)\r",
            "!NUM(3)\r",
            "!NUM(1)\r",
            "!NUM(2)\r",
            "!NUM(3)\r",
        ]

    def test_num_repeats_zero_sends_nothing(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands(["up"], num_repeats=0)
        assert _sent(receiver) == []

    def test_default_num_repeats_is_one(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.send_remote_commands(["up"])
        assert _sent(receiver) == ["!DIRU\r"]


class TestPressDelegatesToSendRemoteCommands:
    def test_press_sends_one_command(self):
        receiver = _wire(MP60Receiver(FAKE_IP))
        receiver.press(RemoteKey.ENTER)
        assert _sent(receiver) == ["!ENTER\r"]

    def test_press_raises_for_unsupported_key(self):
        receiver = _wire(TDAI1120Receiver(FAKE_IP))
        with pytest.raises(LyngdorfUnsupportedError):
            receiver.press(RemoteKey.UP)


class TestRemoteKeysNeverCoalesce:
    """Remote keys are sequential - order and count are the whole
    meaning - so the outbound queue must never coalesce them, even under
    real pacing/draining, not just when writes land immediately
    synchronously (see the other tests in this file, which all rely on
    the no-drain-task synchronous-flush fallback in `LyngdorfApi._writeCommand`).
    """

    @pytest.mark.asyncio
    async def test_ten_rapid_digit_presses_arrive_as_ten_commands_in_order(self):
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            receiver = MP60Receiver(FAKE_IP)
            receiver._api = api
            receiver.send_remote_commands([str(d) for d in range(10)])
            await flush_write_queue(api)
            sent = [call.args[0] for call in api._protocol.write.call_args_list]
            assert sent == [f"!NUM({d})\r" for d in range(10)]
        finally:
            api._stop_write_queue()

    @pytest.mark.asyncio
    async def test_ten_rapid_identical_presses_do_not_coalesce(self):
        """Unlike an absolute setter (VOL(x)), the SAME key pressed
        repeatedly must still produce one write per press - each press
        means "one more step" in a menu, not "the final value"."""
        api = LyngdorfApi(FAKE_IP, LyngdorfModel.MP_60)
        api._protocol = mock.Mock()
        api._start_write_queue()
        try:
            receiver = MP60Receiver(FAKE_IP)
            receiver._api = api
            receiver.send_remote_commands(["down"], num_repeats=10)
            await flush_write_queue(api)
            sent = [call.args[0] for call in api._protocol.write.call_args_list]
            assert sent == ["!DIRD\r"] * 10
        finally:
            api._stop_write_queue()
