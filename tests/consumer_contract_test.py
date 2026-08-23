"""The consumer-contract test (spec §12 WP4): every category of the HA
integration's measured 1.x usage, asserted with per-category semantics -
plus the §7-row completeness check pinning the shim set itself.

The fixture is GENERATED (header records provenance); replace it
wholesale when the consumer sends a new inventory - never hand-edit.
"""

import asyncio
import contextlib
import inspect
import json
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

from lyngdorf import _compat
from lyngdorf.controls import Trim
from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver
from lyngdorf.remote import RemoteKey
from lyngdorf.states import Repeat

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "consumer_contract_ha.json").read_text()
)


@pytest.fixture()
def receiver() -> LyngdorfReceiver:
    r = LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)
    r._register_callbacks()
    return r


@pytest.fixture(
    params=[LyngdorfModel.MP_60, LyngdorfModel.TDAI_3400, LyngdorfModel.P_100]
)
def receiver_any_model(request) -> LyngdorfReceiver:
    r = LyngdorfReceiver("127.0.0.1", request.param)
    r._register_callbacks()
    return r


def test_absent_component_reads_match_1x(receiver_any_model):
    """1.x answered None/False rather than raising when a component was
    absent. The shims must too."""
    r = receiver_any_model
    with pytest.warns(DeprecationWarning):
        assert r.has_position == (r.player is not None)
    with pytest.warns(DeprecationWarning):
        assert r.has_remote_keys == (r.remote is not None)
    if r.player is None:
        with pytest.warns(DeprecationWarning):
            assert r.now_playing is None  # must not raise
    if r.zone_b is None:
        with pytest.warns(DeprecationWarning):
            assert r.zone_b_volume is None  # must not raise


# -- category 1: shimmed reads resolve and warn -----------------------------


@pytest.mark.parametrize("name", FIXTURE["shimmed_reads"])
def test_shimmed_read_resolves_and_warns(receiver, name):
    with pytest.warns(DeprecationWarning):
        getattr(receiver, name)


_DELEGATION: dict[str, Callable[[LyngdorfReceiver], object]] = {
    "mute_enabled": lambda r: r.muted,
    "volume_range": lambda r: r.volume.range,
    "available_sources": lambda r: r.sources,
    "available_sound_modes": lambda r: r.sound_modes,
    "available_room_perfect_positions": lambda r: r.room_perfect_positions,
    "available_voicings": lambda r: r.voicings,
    "available_audio_inputs": lambda r: r.audio_inputs,
    "available_video_inputs": lambda r: r.video_inputs,
    "available_stream_types": lambda r: r.stream_types,
    "trim_bass": lambda r: r.trims[Trim.BASS].value,
    "trim_treble": lambda r: r.trims[Trim.TREBLE].value,
    "trim_centre": lambda r: r.trims[Trim.CENTER].value,
    "trim_height": lambda r: r.trims[Trim.HEIGHT].value,
    "trim_lfe": lambda r: r.trims[Trim.LFE].value,
    "trim_surround": lambda r: r.trims[Trim.SURROUND].value,
    "trim_bass_range": lambda r: r.trims[Trim.BASS].range,
    "trim_treble_range": lambda r: r.trims[Trim.TREBLE].range,
    "trim_centre_range": lambda r: r.trims[Trim.CENTER].range,
    "trim_height_range": lambda r: r.trims[Trim.HEIGHT].range,
    "trim_lfe_range": lambda r: r.trims[Trim.LFE].range,
    "trim_surround_range": lambda r: r.trims[Trim.SURROUND].range,
    "lipsync_range": lambda r: r.lipsync.range if r.lipsync else None,
    "zone_b_power_on": lambda r: r.zone_b.power_on if r.zone_b else None,
    "zone_b_mute_enabled": lambda r: r.zone_b.muted if r.zone_b else None,
    "zone_b_source": lambda r: r.zone_b.source if r.zone_b else None,
    "zone_b_audio_input": lambda r: r.zone_b.audio_input if r.zone_b else None,
    "zone_b_streaming_source": (
        lambda r: r.zone_b.streaming_source if r.zone_b else None
    ),
    "zone_b_volume": lambda r: r.zone_b.volume.value if r.zone_b else None,
    "zone_b_volume_range": lambda r: r.zone_b.volume.range if r.zone_b else None,
    "zone_b_available_sources": lambda r: r.zone_b.sources if r.zone_b else [],
    "has_position": lambda r: r.player is not None,
    "has_remote_keys": lambda r: r.remote is not None,
    "available_remote_keys": (lambda r: r.remote.keys if r.remote else frozenset()),
    "now_playing": lambda r: r.player.now_playing if r.player else None,
    "position_ms": lambda r: r.player.position_ms if r.player else None,
    "position_updated_at": (
        lambda r: r.player.position_updated_at if r.player else None
    ),
    "position_percent": (lambda r: r.player.position_percent if r.player else None),
    "can_pause": lambda r: r.player.can_pause if r.player else False,
    "can_next": lambda r: r.player.can_next if r.player else False,
    "can_previous": lambda r: r.player.can_previous if r.player else False,
    "can_seek": lambda r: r.player.can_seek if r.player else False,
    "can_shuffle": lambda r: r.player.can_shuffle if r.player else False,
    "play_mode": lambda r: r.player.play_mode if r.player else None,
    "shuffle": lambda r: r.player.shuffle if r.player else None,
    "repeat": lambda r: r.player.repeat if r.player else None,
    "available_play_modes": (
        lambda r: r.player.play_modes if r.player else frozenset()
    ),
    "available_repeat_modes": (
        lambda r: r.player.repeat_modes if r.player else frozenset()
    ),
}


@pytest.mark.parametrize("name", sorted(_DELEGATION))
def test_shimmed_read_delegates_to_the_right_target(receiver, name):
    with pytest.warns(DeprecationWarning):
        via_shim = getattr(receiver, name)
    assert via_shim == _DELEGATION[name](receiver), (
        f"{name} warns and returns a value, but not the one the " "2.0 path gives"
    )


def test_every_shimmed_read_has_a_delegation_check():
    assert set(_DELEGATION) == _compat.SHIMMED_READS, (
        f"no delegation check for "
        f"{sorted(_compat.SHIMMED_READS - set(_DELEGATION))}"
    )


# -- categories 2+3: sync-bodied shape - warns even unawaited ---------------


@pytest.mark.parametrize(
    "name", FIXTURE["shimmed_write_methods"] + FIXTURE["shimmed_steppers"]
)
def test_sync_bodied_shim_warns_even_when_never_awaited(receiver, name):
    """D9's measured property: the DeprecationWarning fires on CALL, not
    on await - an async-def shim would emit zero here."""
    method = getattr(receiver, name)
    assert name in _ARGS, f"{name} has no argument row in _ARGS"
    args = _ARGS[name]
    with pytest.warns(DeprecationWarning):
        result = method(*args)
    if inspect.iscoroutine(result):
        result.close()


_ARGS: dict[str, tuple] = {
    "set_volume": (-30.0,),
    "set_zone_b_volume": (-30.0,),
    "set_lipsync": (20,),
    "set_trim_bass": (1.0,),
    "set_trim_treble": (1.0,),
    "set_trim_centre": (1.0,),
    "set_trim_height": (1.0,),
    "set_trim_lfe": (1.0,),
    "set_trim_surround": (1.0,),
    "send_remote_commands": (["up"],),
    "press": (RemoteKey.UP,),
    "volume_up": (),
    "volume_down": (),
    "zone_b_volume_up": (),
    "zone_b_volume_down": (),
    "trim_bass_up": (),
    "trim_bass_down": (),
    "trim_treble_up": (),
    "trim_treble_down": (),
    "trim_centre_up": (),
    "trim_centre_down": (),
    "trim_height_up": (),
    "trim_height_down": (),
    "trim_lfe_up": (),
    "trim_lfe_down": (),
    "trim_surround_up": (),
    "trim_surround_down": (),
}


# -- category 4: already-async renames - warn + coroutine, nothing more -----


@pytest.mark.parametrize("name", FIXTURE["shimmed_methods_already_async"])
def test_already_async_shim_warns_and_returns_coroutine(receiver, name):
    if name == "async_seek":
        args = (0,)
    elif name == "async_set_shuffle":
        args = (True,)
    elif name == "async_set_repeat":
        args = (Repeat.OFF,)
    elif name == "async_set_play_mode":
        from lyngdorf.states import PlayMode

        args = (PlayMode.NORMAL,)
    else:
        args = ()
    # These are real `async def` shims (see
    # test_already_async_shim_is_a_real_coroutine_function for why that
    # matters), so the body - and therefore the warning - runs on AWAIT,
    # not on call. Callers of this category always await, so warning at
    # await is the correct moment. Contrast the sync->async categories
    # above, which must warn on call because their callers may never
    # await at all.
    coro = getattr(receiver, name)(*args)
    assert inspect.iscoroutine(coro)
    with pytest.warns(DeprecationWarning):
        with contextlib.suppress(Exception):
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# -- category 5: callback renames --------------------------------------------


@pytest.mark.parametrize(
    "name",
    [n for n in FIXTURE["shimmed_callbacks"] if n.startswith("register_")],
)
def test_callback_shim_warns_and_returns_an_unsubscribe(receiver, name):
    """Only the REGISTRATION shims return an unsubscribe.
    un_register_notification_callback is in this category because it is
    callback-related, but it consumes a callback and returns None - it
    has its own test below."""
    with pytest.warns(DeprecationWarning):
        unsub = getattr(receiver, name)(lambda *a: None)
    unsub()
    unsub()  # idempotent


def test_position_jump_shim_noop_unsubscribe_without_player():
    p100 = LyngdorfReceiver("127.0.0.1", LyngdorfModel.P_100)
    with pytest.warns(DeprecationWarning):
        unsub = p100.register_position_jump_callback(lambda ms: None)
    unsub()  # no player, no error


# -- category 6: await_same_name - real surface, sync->async, NO warning ----


@pytest.mark.parametrize("name", FIXTURE["await_same_name"])
def test_await_same_name_is_a_coroutine_function_and_never_warns(receiver, name):
    method = getattr(type(receiver), name)
    assert asyncio.iscoroutinefunction(method)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        _ = getattr(receiver, name)


# -- category 7: the control group -------------------------------------------


@pytest.mark.parametrize("name", FIXTURE["kept_unchanged"])
def test_kept_unchanged_never_warns(receiver, name):
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        _ = getattr(receiver, name)


# -- category 8: the reused names have NO shim -------------------------------


@pytest.mark.parametrize("name", FIXTURE["no_shim_reused_names"])
def test_reused_names_are_the_new_types_with_no_shim(receiver, name):
    from lyngdorf.controls import NumericControl

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        value = getattr(receiver, name)
    assert value is None or isinstance(value, NumericControl)
    assert name not in _compat.SHIMMED_READS


# -- category 9: removals stay dead ------------------------------------------


def test_consumer_uses_no_removed_names(receiver):
    """This is the consumer's SLICE, and it is currently empty - the
    measured integration uses nothing that 2.0 removes outright. An empty
    parametrize silently skips, which reads like missing coverage rather
    than a clean result, so assert it directly instead.

    The spec's full removal list is covered by
    test_spec_removed_receiver_members_do_not_resolve; this one only ever
    answers "does a real consumer touch any of them".
    """
    for name in FIXTURE["no_shim_removed"]:
        with pytest.raises(AttributeError):
            getattr(receiver, name)


@pytest.mark.parametrize("name", ["lookup_command"])
def test_spec_removed_receiver_members_do_not_resolve(receiver, name):
    """un_register_notification_callback was here until a real consumer
    measured what removing it costs: one unadapted teardown produced 472
    test failures. It is now shimmed (see SPEC_SHIMMED_CALLBACKS), which
    is why this list is shorter than it looks."""
    with pytest.raises(AttributeError):
        getattr(receiver, name)


# -- category 10: the deliberate overlap - DO NOT DEDUPE ----------------------


def test_setter_carve_out_names_span_two_read_fates_and_one_write_fate(
    receiver,
):
    overlap = FIXTURE["also_written_by_production_setter_carve_out"]
    reads = set(FIXTURE["shimmed_reads"])
    kept = set(FIXTURE["kept_unchanged"])
    for name in overlap:
        assert (name in reads) != (name in kept), name  # exactly one fate
        if name in reads:
            with pytest.warns(DeprecationWarning):
                getattr(receiver, name)
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                getattr(receiver, name)
        for klass in type(receiver).__mro__:
            member = vars(klass).get(name)
            if isinstance(member, property):
                assert member.fset is None, name
                break


# -- the §7-row completeness test ---------------------------------------------
# Hand-transcribed from spec §7's migration table. NOT generated from
# _compat or from FIXTURE. Do not build this from either.

SPEC_SHIMMED_READS: frozenset[str] = frozenset(
    {
        "mute_enabled",
        "volume_range",
        "available_sources",
        "available_sound_modes",
        "available_room_perfect_positions",
        "available_voicings",
        "available_audio_inputs",
        "available_video_inputs",
        "available_stream_types",
        "trim_bass",
        "trim_treble",
        "trim_centre",
        "trim_height",
        "trim_lfe",
        "trim_surround",
        "trim_bass_range",
        "trim_treble_range",
        "trim_centre_range",
        "trim_height_range",
        "trim_lfe_range",
        "trim_surround_range",
        "lipsync_range",
        "zone_b_power_on",
        "zone_b_mute_enabled",
        "zone_b_source",
        "zone_b_audio_input",
        "zone_b_streaming_source",
        "zone_b_volume",
        "zone_b_volume_range",
        "zone_b_available_sources",
        "has_position",
        "has_remote_keys",
        "available_remote_keys",
        "now_playing",
        "position_ms",
        "position_updated_at",
        "position_percent",
        "can_pause",
        "can_next",
        "can_previous",
        "can_seek",
        "can_shuffle",
        "play_mode",
        "shuffle",
        "repeat",
        "available_play_modes",
        "available_repeat_modes",
    }
)
SPEC_SHIMMED_WRITE_METHODS: frozenset[str] = frozenset(
    {
        "set_volume",
        "set_zone_b_volume",
        "set_lipsync",
        "set_trim_bass",
        "set_trim_treble",
        "set_trim_centre",
        "set_trim_height",
        "set_trim_lfe",
        "set_trim_surround",
        "send_remote_commands",
        "press",
    }
)
SPEC_SHIMMED_STEPPERS: frozenset[str] = frozenset(
    {
        "volume_up",
        "volume_down",
        "zone_b_volume_up",
        "zone_b_volume_down",
        "trim_bass_up",
        "trim_bass_down",
        "trim_treble_up",
        "trim_treble_down",
        "trim_centre_up",
        "trim_centre_down",
        "trim_height_up",
        "trim_height_down",
        "trim_lfe_up",
        "trim_lfe_down",
        "trim_surround_up",
        "trim_surround_down",
    }
)
SPEC_SHIMMED_ALREADY_ASYNC: frozenset[str] = frozenset(
    {
        "async_connect",
        "async_disconnect",
        "async_pause",
        "async_next",
        "async_previous",
        "async_seek",
        "async_set_play_mode",
        "async_set_shuffle",
        "async_set_repeat",
    }
)
SPEC_SHIMMED_CALLBACKS: frozenset[str] = frozenset(
    {
        "un_register_notification_callback",
        "register_notification_callback",
        "register_position_callback",
        "register_position_jump_callback",
    }
)
SPEC_SHIMMED_MODEL_FEATURE_CHECKS: frozenset[str] = frozenset(
    {
        "has_zone_b_feature",
        "has_video_feature",
        "has_surround_feature",
        "has_streaming_feature",
        "has_lipsync_feature",
        "has_remote_keys_feature",
        "has_bass_trim_feature",
        "has_treble_trim_feature",
        "has_bass_trim_step_feature",
        "has_treble_trim_step_feature",
        "has_mute_state_in_parameter",
    }
)


def test_shim_set_matches_spec_rows_exactly():
    """Nothing missing, nothing extra (spec §12 WP4)."""
    for label, spec_set, registry in (
        ("reads", SPEC_SHIMMED_READS, _compat.SHIMMED_READS),
        (
            "write_methods",
            SPEC_SHIMMED_WRITE_METHODS,
            _compat.SHIMMED_WRITE_METHODS,
        ),
        ("steppers", SPEC_SHIMMED_STEPPERS, _compat.SHIMMED_STEPPERS),
        (
            "already_async",
            SPEC_SHIMMED_ALREADY_ASYNC,
            _compat.SHIMMED_ALREADY_ASYNC,
        ),
        ("callbacks", SPEC_SHIMMED_CALLBACKS, _compat.SHIMMED_CALLBACKS),
    ):
        assert registry == spec_set, (
            f"{label}: missing from implementation "
            f"{sorted(spec_set - registry)}; "
            f"not in spec {sorted(registry - spec_set)}"
        )
    all_shims = (
        _compat.SHIMMED_READS
        | _compat.SHIMMED_WRITE_METHODS
        | _compat.SHIMMED_STEPPERS
        | _compat.SHIMMED_ALREADY_ASYNC
        | _compat.SHIMMED_CALLBACKS
    )
    for name in all_shims:
        assert hasattr(LyngdorfReceiver, name), name
    assert {"volume", "lipsync"}.isdisjoint(all_shims)
    assert {"set_source", "set_sound_mode"}.isdisjoint(all_shims)
    for category, registry in (
        ("shimmed_reads", _compat.SHIMMED_READS),
        ("shimmed_write_methods", _compat.SHIMMED_WRITE_METHODS),
        ("shimmed_steppers", _compat.SHIMMED_STEPPERS),
        ("shimmed_methods_already_async", _compat.SHIMMED_ALREADY_ASYNC),
        ("shimmed_callbacks", _compat.SHIMMED_CALLBACKS),
    ):
        assert set(FIXTURE[category]) <= registry, category
    assert _compat.SHIMMED_MODEL_FEATURE_CHECKS == SPEC_SHIMMED_MODEL_FEATURE_CHECKS, (
        f"missing {sorted(SPEC_SHIMMED_MODEL_FEATURE_CHECKS - _compat.SHIMMED_MODEL_FEATURE_CHECKS)}; "
        f"not in spec {sorted(_compat.SHIMMED_MODEL_FEATURE_CHECKS - SPEC_SHIMMED_MODEL_FEATURE_CHECKS)}"
    )
    for name in _compat.SHIMMED_MODEL_FEATURE_CHECKS:
        assert hasattr(LyngdorfModel.MP_60, name), name


# ---------------------------------------------------------------------------
# The two shim shapes must not drift into each other. Both directions are
# pinned because each failure mode is silent in a different way.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURE["shimmed_methods_already_async"])
def test_already_async_shim_is_a_real_coroutine_function(name):
    """Not merely "returns a coroutine" - a genuine `async def`.

    MagicMock(spec=Cls) picks AsyncMock vs MagicMock by asking
    inspect.iscoroutinefunction of the CLASS attribute. A sync-bodied
    shim returning a coroutine is not one, so a spec'd mock hands the
    consumer a plain MagicMock and every `await receiver.async_connect()`
    raises "MagicMock can't be awaited". Measured at 120 failures in a
    real integration suite; invisible on hardware and invisible to the
    rest of this file, which calls the real object.
    """
    assert inspect.iscoroutinefunction(getattr(LyngdorfReceiver, name)), (
        f"{name} was already async in 1.x, so its shim must be a real "
        f"async def or spec'd consumer mocks cannot await it"
    )


@pytest.mark.parametrize(
    "name", FIXTURE["shimmed_write_methods"] + FIXTURE["shimmed_steppers"]
)
def test_sync_to_async_shim_is_not_a_coroutine_function(name):
    """The inverse, and equally load-bearing.

    These were sync in 1.x, so an unmigrated caller does not await them.
    An `async def` here would never run its body - a silent, warningless
    no-op. Sync-bodied means the DeprecationWarning fires on call.
    """
    assert not inspect.iscoroutinefunction(getattr(LyngdorfReceiver, name)), (
        f"{name} was sync in 1.x; an async def shim would be a silent "
        f"no-op for any caller that does not await it"
    )


def test_un_register_shim_calls_the_stashed_unsubscribe(receiver):
    """Different shape to the register_* shims: consumes a callback,
    returns None. Keyed on the callback object, which matters because
    consumers pass BOUND METHODS - fresh objects on each attribute
    access that nonetheless compare and hash equal, so the dict finds
    the right unsubscribe. If that were not true this would fail
    silently, unregistering nothing."""
    hits: list[int] = []

    class Consumer:
        def handle(self) -> None:
            hits.append(1)

    c = Consumer()
    assert c.handle is not c.handle  # fresh object each access
    with pytest.warns(DeprecationWarning):
        receiver.register_notification_callback(c.handle)
    receiver._notify_notification_callbacks()
    assert hits == [1]

    with pytest.warns(DeprecationWarning):
        receiver.un_register_notification_callback(c.handle)
    receiver._notify_notification_callbacks()
    assert hits == [1], "callback still fired after un_register"

    # tolerated, as in 1.x
    with pytest.warns(DeprecationWarning):
        receiver.un_register_notification_callback(c.handle)
