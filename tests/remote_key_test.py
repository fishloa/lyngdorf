# ruff: noqa: F821
"""Tests for the remote-control key API (issue #46).

Before this, `Msg.CURSOR_UP`/`Msg.MENU`/etc. lived in the bidirectional
`Msg` registry with no callback ever registered and nothing that could
send them - dead code, checked only by lookup-only assertions
(`tests/basic_wiring_test.py`, before this issue) that verified the table
was right without verifying the feature was reachable at all. These tests
exercise the feature end-to-end: `Remote.send()`/
`press()` all the way down to what actually reaches the (mocked)
transport, not just a dict lookup.

Fixtures are local to this file rather than added to `tests/conftest.py`,
which another agent owns concurrently for issue #45.
"""

from unittest import mock

import pytest
from conftest import flush_write_queue

from lyngdorf.api import LyngdorfApi
from lyngdorf.exceptions import LyngdorfUnsupportedError
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver  # PORT-NOTE(WP4): old device import
from lyngdorf.remote import RemoteKey, RemoteKeyTable, resolve_remote_key

FAKE_IP = "0.0.0.0"

# Every MP model, plus the P200, have this full set. The MP manuals
# (docs/mp-40.md, docs/mp-50.md, docs/mp-60.md) omit `!BACK` and document
# only `!EXIT`, but that is a documentation error, not a hardware gap: a
# real MP-60 on firmware 5.4.2 echoes `#BACK` at `!VERB(2)` (which stays
# silent for anything it does not recognise) while rejecting deliberately
# malformed controls in the same session - see MP_REMOTE_KEYS in
# mp_series.py for the measurement. MULTIVIEW is included for MP (every
# MP manual documents it with no per-model restriction, confirmed
# accepted on that same real MP-60) and for the P200 specifically -
# docs/p-series.md:69 restricts `!MULTIVIEW` to the P200 explicitly
# ("P200 only"), so P100/P300 do NOT get it - see
# P100_AND_P300_EXPECTED_KEYS below and P_REMOTE_KEYS/P200_REMOTE_KEYS in
# p_series.py.
FULL_EXPECTED_KEYS = frozenset(
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

# P100 and P300 only - the manual restricts MULTIVIEW to the P200, and
# there is no hardware measurement or third-party mapping to overrule
# that restriction with (unlike BACK) - see the note above
# FULL_EXPECTED_KEYS and P_REMOTE_KEYS in p_series.py.
P100_AND_P300_EXPECTED_KEYS = FULL_EXPECTED_KEYS - {RemoteKey.MULTIVIEW}


def _sent(receiver: LyngdorfReceiver) -> list[str]:
    """Every command that actually reached the mocked transport, in order."""
    return [call.args[0] for call in receiver._api._protocol.write.call_args_list]


def _wire(receiver: LyngdorfReceiver) -> LyngdorfReceiver:
    """Attach a mocked transport, bypassing a real connection."""
    receiver._api._protocol = mock.Mock()
    return receiver


class TestPerModelCapability:
    """`available_remote_keys`/`has_remote_keys` are explicit per model,
    never inferred from anything else - see ModelConfig.remote_keys."""

    @pytest.mark.parametrize(
        "receiver_cls", [LyngdorfModel.MP_40, LyngdorfModel.MP_50, LyngdorfModel.MP_60]
    )
    @pytest.mark.asyncio
    async def test_mp_models_have_the_full_key_set_including_multiview(
        self, receiver_cls
    ):
        """Every MP manual documents `!MULTIVIEW` with no per-model
        restriction, and a real MP-60 accepted it - unlike the P series,
        where docs/p-series.md restricts it to the P200 (see
        test_p200_has_multiview_but_p100_and_p300_do_not below)."""
        receiver = LyngdorfReceiver(FAKE_IP, receiver_cls)
        assert receiver.remote.keys == FULL_EXPECTED_KEYS
        assert receiver.remote is not None

    @pytest.mark.asyncio
    async def test_p200_has_the_full_key_set_including_multiview(self):
        receiver = LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_200)
        assert receiver.remote.keys == FULL_EXPECTED_KEYS
        assert receiver.remote is not None

    @pytest.mark.parametrize("receiver_cls", [LyngdorfModel.P_100, LyngdorfModel.P_300])
    @pytest.mark.asyncio
    async def test_p100_and_p300_have_the_full_key_set_minus_multiview(
        self, receiver_cls
    ):
        """docs/p-series.md:69 restricts `!MULTIVIEW` to the P200
        explicitly ("P200 only") - a stated restriction, not an
        omission, and unlike BACK there is no hardware measurement or
        third-party mapping to overrule it with. P100/P300 must NOT
        advertise MULTIVIEW."""
        receiver = LyngdorfReceiver(FAKE_IP, receiver_cls)
        assert receiver.remote.keys == P100_AND_P300_EXPECTED_KEYS
        assert RemoteKey.MULTIVIEW not in receiver.remote.keys
        assert receiver.remote is not None

    @pytest.mark.asyncio
    async def test_p200_has_multiview_but_p100_and_p300_do_not(self):
        p200_keys = LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_200).remote.keys
        assert RemoteKey.MULTIVIEW in p200_keys
        assert (
            RemoteKey.MULTIVIEW
            not in LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_100).remote.keys
        )
        assert (
            RemoteKey.MULTIVIEW
            not in LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_300).remote.keys
        )
        # Otherwise identical - P100/P300 are the P200's set minus MULTIVIEW.
        assert p200_keys - {RemoteKey.MULTIVIEW} == (
            LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_100).remote.keys
        )

    @pytest.mark.asyncio
    async def test_mp_and_p200_key_sets_are_identical(self):
        """BACK was originally thought to be P-only, but a real MP-60
        accepts it too (see MP_REMOTE_KEYS in mp_series.py) - MP and the
        P200 specifically end up with identical key sets. P100/P300 are
        that same set minus MULTIVIEW (see
        test_p100_and_p300_have_the_full_key_set_minus_multiview)."""
        assert (
            LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60).remote.keys
            == LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_200).remote.keys
        )

    @pytest.mark.parametrize(
        "receiver_cls",
        [
            LyngdorfModel.TDAI_1120,
            LyngdorfModel.TDAI_2170,
            LyngdorfModel.TDAI_2210,
            LyngdorfModel.TDAI_3400,
        ],
    )
    @pytest.mark.asyncio
    async def test_tdai_models_have_no_remote_keys_at_all(self, receiver_cls):
        receiver = LyngdorfReceiver(FAKE_IP, receiver_cls)
        assert (
            receiver.remote is None
        )  # PORT-NOTE(WP4): no Remote component on TDAI; old API returned frozenset()

    @pytest.mark.asyncio
    async def test_mp_has_back(self):
        """No MP manual documents `!BACK`, but a real MP-60 on firmware
        5.4.2 accepts it (see MP_REMOTE_KEYS in mp_series.py for the
        `!VERB(2)` echo measurement) - the manual is wrong, not the
        table. Do not "fix" this back to excluding BACK."""
        receiver = LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60)
        assert RemoteKey.BACK in receiver.remote.keys

    @pytest.mark.asyncio
    async def test_mp_has_exit(self):
        """The other half of the same defect: MP models must have EXIT,
        which every MP manual documents and the old code never mapped."""
        receiver = LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60)
        assert RemoteKey.EXIT in receiver.remote.keys

    @pytest.mark.asyncio
    async def test_lyngdorf_model_enum_agrees_with_receiver(self):
        """The capability lives on ModelConfig/LyngdorfModel; Receiver
        just forwards it - assert the two never diverge."""
        assert (
            LyngdorfModel.MP_60.config.available_remote_keys()
            == LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60).remote.keys
        )
        assert LyngdorfModel.TDAI_1120.config.available_remote_keys() == frozenset()


class TestResolveRemoteKey:
    """Unit coverage for `resolve_remote_key` itself, independent of any
    model/capability check."""

    @pytest.mark.parametrize("text", ["up", "UP", "Up", " up ", "uP"])
    @pytest.mark.asyncio
    async def test_case_and_whitespace_insensitive(self, text):
        assert resolve_remote_key(text) is RemoteKey.UP

    @pytest.mark.asyncio
    async def test_digit_strings_resolve(self):
        assert resolve_remote_key("5") is RemoteKey.DIGIT_5

    @pytest.mark.asyncio
    async def test_remote_key_passed_through_unchanged(self):
        assert resolve_remote_key(RemoteKey.ENTER) is RemoteKey.ENTER

    @pytest.mark.asyncio
    async def test_unknown_string_resolves_to_none(self):
        assert resolve_remote_key("bogus") is None

    @pytest.mark.asyncio
    async def test_empty_string_resolves_to_none(self):
        assert resolve_remote_key("") is None


class TestRemoteKeyTable:
    """Unit coverage for `RemoteKeyTable` - the digit-formatter shape in
    particular, since `!NUM(X)` must be one parameterised command, not
    ten literal dict entries."""

    @pytest.mark.asyncio
    async def test_empty_table_has_no_keys(self):
        table = RemoteKeyTable()
        assert table.available_keys() == frozenset()

    @pytest.mark.asyncio
    async def test_digit_format_expands_to_all_ten_digits(self):
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

    @pytest.mark.asyncio
    async def test_command_for_unsupported_key_raises_keyerror(self):
        table = RemoteKeyTable(commands={RemoteKey.UP: "DIRU"})
        with pytest.raises(KeyError):
            table.command_for(RemoteKey.DOWN)

    @pytest.mark.asyncio
    async def test_command_for_digit_without_format_raises_keyerror(self):
        table = RemoteKeyTable()
        with pytest.raises(KeyError):
            table.command_for(RemoteKey.DIGIT_0)


class TestWireCommandPerModel:
    """`press()` all the way down to the mocked transport - the actual
    wire token sent, not just what `lookup_remote_key` returns."""

    @pytest.mark.asyncio
    async def test_mp60_exit_sends_exit(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.EXIT)
        assert _sent(receiver) == ["!EXIT\r"]
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.EXIT)
        assert _sent(receiver) == ["!EXIT\r"]

    @pytest.mark.asyncio
    async def test_mp60_back_sends_back(self):
        """A real MP-60 accepts `!BACK` despite no MP manual documenting
        it - see MP_REMOTE_KEYS in mp_series.py for the measurement."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.BACK)
        assert _sent(receiver) == ["!BACK\r"]
        """A real MP-60 accepts `!BACK` despite no MP manual documenting
        it - see MP_REMOTE_KEYS in mp_series.py for the measurement."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.BACK)
        assert _sent(receiver) == ["!BACK\r"]

    @pytest.mark.asyncio
    async def test_p100_back_sends_back(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_100))
        await receiver.remote.press(RemoteKey.BACK)
        assert _sent(receiver) == ["!BACK\r"]
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_100))
        await receiver.remote.press(RemoteKey.BACK)
        assert _sent(receiver) == ["!BACK\r"]

    @pytest.mark.asyncio
    async def test_p100_exit_sends_exit(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_100))
        await receiver.remote.press(RemoteKey.EXIT)
        assert _sent(receiver) == ["!EXIT\r"]
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.P_100))
        await receiver.remote.press(RemoteKey.EXIT)
        assert _sent(receiver) == ["!EXIT\r"]

    @pytest.mark.parametrize(
        "receiver_cls", [LyngdorfModel.MP_60, LyngdorfModel.P_200], ids=["mp60", "p200"]
    )
    @pytest.mark.asyncio
    async def test_multiview_sends_multiview(self, receiver_cls):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, receiver_cls))
        await receiver.remote.press(RemoteKey.MULTIVIEW)
        assert _sent(receiver) == ["!MULTIVIEW\r"]
        receiver = _wire(LyngdorfReceiver(FAKE_IP, receiver_cls))
        await receiver.remote.press(RemoteKey.MULTIVIEW)
        assert _sent(receiver) == ["!MULTIVIEW\r"]

    @pytest.mark.parametrize(
        "receiver_cls", [LyngdorfModel.P_100, LyngdorfModel.P_300], ids=["p100", "p300"]
    )
    @pytest.mark.asyncio
    async def test_multiview_is_unsupported_on_p100_and_p300(self, receiver_cls):
        """docs/p-series.md:69 restricts `!MULTIVIEW` to the P200 - the
        P100/P300 must raise rather than silently send a command their
        manual says does not exist on that hardware."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, receiver_cls))
        with pytest.raises(LyngdorfUnsupportedError):
            await receiver.remote.press(RemoteKey.MULTIVIEW)
        assert _sent(receiver) == []
        """docs/p-series.md:69 restricts `!MULTIVIEW` to the P200 - the
        P100/P300 must raise rather than silently send a command their
        manual says does not exist on that hardware."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, receiver_cls))
        with pytest.raises(LyngdorfUnsupportedError):
            await receiver.remote.press(RemoteKey.MULTIVIEW)
        assert _sent(receiver) == []

    @pytest.mark.asyncio
    async def test_digit_sends_parameterised_num_command(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.DIGIT_7)
        assert _sent(receiver) == ["!NUM(7)\r"]
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.DIGIT_7)
        assert _sent(receiver) == ["!NUM(7)\r"]

    @pytest.mark.asyncio
    async def test_settings_maps_to_setup_token(self):
        """RemoteKey.SETTINGS -> "SETUP" on the wire, matching Msg.SETTINGS'
        old mapping, not a literal "SETTINGS" token."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.SETTINGS)
        assert _sent(receiver) == ["!SETUP\r"]
        """RemoteKey.SETTINGS -> "SETUP" on the wire, matching Msg.SETTINGS'
        old mapping, not a literal "SETTINGS" token."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.SETTINGS)
        assert _sent(receiver) == ["!SETUP\r"]

    @pytest.mark.asyncio
    async def test_cursor_keys_map_to_dir_tokens(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send(
            [RemoteKey.UP, RemoteKey.DOWN, RemoteKey.LEFT, RemoteKey.RIGHT]
        )
        assert _sent(receiver) == ["!DIRU\r", "!DIRD\r", "!DIRL\r", "!DIRR\r"]

    @pytest.mark.asyncio
    async def test_tdai_has_no_wire_command_for_anything(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.TDAI_1120))
        # 2.1: the TDAI family has no remote keys, so it has no Remote
        # component - the 1.x raise-at-call-time became absence.
        assert receiver.remote is None
        assert _sent(receiver) == []
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.TDAI_1120))
        # 2.1: the TDAI family has no remote keys, so it has no Remote
        # component - the 1.x raise-at-call-time became absence.
        assert receiver.remote is None
        assert _sent(receiver) == []


class TestSendRemoteCommandsStrings:
    """`send_remote_commands` is the HA-shaped entry point - it must
    accept plain strings, case-insensitively, exactly like
    `RemoteEntity.async_send_command` is handed."""

    @pytest.mark.parametrize("text", ["up", "UP", "Up"])
    @pytest.mark.asyncio
    async def test_case_insensitive_string_resolves_and_sends(self, text):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send([text])
        assert _sent(receiver) == ["!DIRU\r"]

    @pytest.mark.asyncio
    async def test_mixed_strings_and_enum_members(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send(["up", RemoteKey.DOWN, "enter"])
        assert _sent(receiver) == ["!DIRU\r", "!DIRD\r", "!ENTER\r"]

    @pytest.mark.asyncio
    async def test_digit_strings_send_num_commands_in_order(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send([str(d) for d in range(10)])
        assert _sent(receiver) == [f"!NUM({d})\r" for d in range(10)]


class TestBatchValidatesBeforeSending:
    """A typo (or an unsupported key) anywhere in the batch must raise
    before ANY of the batch reaches the device - a caller navigating a
    six-command sequence must never get the device halfway through a
    menu because item 5 was misspelled."""

    @pytest.mark.asyncio
    async def test_unknown_command_raises_and_sends_nothing(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        with pytest.raises(LyngdorfUnsupportedError):
            await receiver.remote.send(["up", "bogus", "down"])
        assert _sent(receiver) == []

    @pytest.mark.asyncio
    async def test_bad_item_late_in_batch_still_sends_nothing(self):
        """The bad item is 5th of 6 - even the four good ones before it
        must not have gone out."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        with pytest.raises(LyngdorfUnsupportedError):
            await receiver.remote.send(["up", "up", "down", "enter", "bogus", "menu"])
        assert _sent(receiver) == []

    @pytest.mark.asyncio
    async def test_unsupported_key_for_this_model_raises_and_sends_nothing(self):
        """UP resolves to a real RemoteKey, but this TDAI model has no
        remote keys at all - still must raise before sending, same as an
        unresolvable string."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.TDAI_1120))
        # 2.1: no remote keys means no Remote component, so the 1.x
        # raise-before-sending became there being nothing to call.
        assert receiver.remote is None
        assert _sent(receiver) == []

    @pytest.mark.asyncio
    async def test_error_message_names_the_bad_value_and_available_keys(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        with pytest.raises(LyngdorfUnsupportedError) as exc_info:
            await receiver.remote.send(["bogus"])
        message = str(exc_info.value)
        assert "bogus" in message
        assert "exit" in message  # something MP60 does support


class TestNumRepeats:
    """`num_repeats` repeats the WHOLE resolved sequence as a block, not
    each individual command - matching Home Assistant's own
    interpretation (see `broadlink`'s `remote.py` and `harmony`'s
    `data.py`, both of which repeat the sequence rather than each
    command) - see `Receiver.send_remote_commands`."""

    @pytest.mark.asyncio
    async def test_num_repeats_enqueues_that_many_presses(self):
        """A single-key batch cannot distinguish "repeat the sequence"
        from "repeat each key" - both nestings produce the same output
        here. See test_multi_key_batch_repeats_the_whole_sequence below
        for the test that actually pins the nesting down."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send(["up"], num_repeats=3)
        assert _sent(receiver) == ["!DIRU\r"] * 3

    @pytest.mark.asyncio
    async def test_multi_key_batch_repeats_the_whole_sequence(self):
        """The defect this pins down: `num_repeats=2` over `["up",
        "down"]` must send `up down up down` (the sequence repeated as a
        block), never `up up down down` (each key repeated in place) -
        the digit-entry equivalent is `["1","2","3"]` reaching the
        device as `123123`, not `112233`."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send(["up", "down"], num_repeats=2)
        assert _sent(receiver) == ["!DIRU\r", "!DIRD\r", "!DIRU\r", "!DIRD\r"]

    @pytest.mark.asyncio
    async def test_digit_sequence_repeats_as_a_block_not_per_digit(self):
        """The exact scenario from the issue: entering "123" twice must
        produce "123123" on the wire, not "112233"."""
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send(["1", "2", "3"], num_repeats=2)
        assert _sent(receiver) == [
            "!NUM(1)\r",
            "!NUM(2)\r",
            "!NUM(3)\r",
            "!NUM(1)\r",
            "!NUM(2)\r",
            "!NUM(3)\r",
        ]

    @pytest.mark.asyncio
    async def test_num_repeats_zero_sends_nothing(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send(["up"], num_repeats=0)
        assert _sent(receiver) == []

    @pytest.mark.asyncio
    async def test_default_num_repeats_is_one(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.send(["up"])
        assert _sent(receiver) == ["!DIRU\r"]


class TestPressDelegatesToSendRemoteCommands:
    @pytest.mark.asyncio
    async def test_press_sends_one_command(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.ENTER)
        assert _sent(receiver) == ["!ENTER\r"]
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60))
        await receiver.remote.press(RemoteKey.ENTER)
        assert _sent(receiver) == ["!ENTER\r"]

    @pytest.mark.asyncio
    async def test_press_raises_for_unsupported_key(self):
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.TDAI_1120))
        # 2.1: the TDAI family has no remote keys, so it has no Remote
        # component - the 1.x raise-at-call-time became absence.
        assert receiver.remote is None
        assert _sent(receiver) == []
        receiver = _wire(LyngdorfReceiver(FAKE_IP, LyngdorfModel.TDAI_1120))
        # 2.1: the TDAI family has no remote keys, so it has no Remote
        # component - the 1.x raise-at-call-time became absence.
        assert receiver.remote is None
        assert _sent(receiver) == []


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
            receiver = LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60)
            receiver._api = api
            # PORT-NOTE(WP4): .remote.send uses original api; api.send_remote_key directly tests no-coalesce
            for d in range(10):
                api.send_remote_key(resolve_remote_key(str(d)))
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
            receiver = LyngdorfReceiver(FAKE_IP, LyngdorfModel.MP_60)
            receiver._api = api
            # PORT-NOTE(WP4): .remote.send uses original api; api.send_remote_key directly tests no-coalesce
            for _ in range(10):
                api.send_remote_key(RemoteKey.DOWN)
            await flush_write_queue(api)
            sent = [call.args[0] for call in api._protocol.write.call_args_list]
            assert sent == ["!DIRD\r"] * 10
        finally:
            api._stop_write_queue()
