"""1.11-only: every 1.10 signature, pinned.

The bug this exists to prevent shipped once. 1.11.0's first build reused
2.0's shim shape, where a 1.x write method is sync-bodied but returns a
coroutine so an unawaited legacy call still warns. That is right for
2.0, where those names are being removed and loudness is the point. In
1.11 nothing is being removed, so nothing may change shape - and
changing a method's return type from None to Coroutine is a breaking
change: the consumer's unawaited call sites became `unused-coroutine`
errors and its `Callable[..., None]` entity descriptions became
`arg-type` errors. A release whose entire purpose is a no-op version
bump had broken the version bump.

It was found by a consumer running its CI, which reported the 16 sites
its own code touched. Measuring the library against 1.10 directly found
27. The difference is the reason this file exists: "a consumer noticed"
is not coverage, because it only ever finds the subset that consumer
uses.

The fixture is generated from git tag v1.10.0 and checked in, so this
runs without git and cannot drift. Deleted with the compat layer.
"""

import inspect
import json
import pathlib

import pytest

from lyngdorf.models import LyngdorfModel
from lyngdorf.receiver import LyngdorfReceiver

FIXTURE = json.loads(
    (
        pathlib.Path(__file__).parent / "fixtures" / "api_1_10_signatures.json"
    ).read_text()
)

# Names 2.0 removes outright, which 1.11 therefore need not carry. Each
# needs a reason, because the easy way to make this file pass is to add
# to this list.
DELIBERATELY_ABSENT = {
    # An internal protocol-table lookup that was never consumer API: it
    # returns a wire token for a Msg enum. No consumer can use it without
    # already depending on the wire format the library exists to hide.
    "lookup_command",
}


def _receiver() -> LyngdorfReceiver:
    return LyngdorfReceiver("127.0.0.1", LyngdorfModel.MP_60)


def _returns_awaitable(annotation: object) -> bool:
    text = str(annotation)
    return "Coroutine" in text or "Awaitable" in text


@pytest.mark.parametrize("name", sorted(FIXTURE["properties"]))
def test_every_1_10_property_still_exists(name):
    member = inspect.getattr_static(type(_receiver()), name, None)
    assert isinstance(member, property), f"{name} is no longer a property"


@pytest.mark.parametrize(
    "name",
    sorted(n for n, v in FIXTURE["properties"].items() if v["settable"]),
)
def test_every_1_10_settable_property_is_still_settable(name):
    """The 18. Assignment must not be a static error on this pin."""
    member = inspect.getattr_static(type(_receiver()), name, None)
    assert isinstance(member, property)
    assert member.fset is not None, f"{name} lost its 1.10 setter"


@pytest.mark.parametrize("name", sorted(FIXTURE["methods"]))
def test_every_1_10_method_keeps_its_1_10_shape(name):
    """The regression that shipped.

    Two things are checked, and the second is the one that was missed:
    a method that was sync in 1.10 must still be sync, AND a method that
    returned a value in 1.10 must not now return something awaitable.
    The first alone passes for a sync-bodied shim that returns a
    coroutine, which is exactly what broke.
    """
    if name in DELIBERATELY_ABSENT:
        pytest.skip(f"{name} is removed in 2.0 - see DELIBERATELY_ABSENT")
    expected = FIXTURE["methods"][name]
    member = inspect.getattr_static(type(_receiver()), name, None)
    assert member is not None, f"{name} vanished"
    assert callable(member), f"{name} is no longer callable"

    is_async = inspect.iscoroutinefunction(member)
    assert is_async == expected["async"], (
        f"{name} was {'async' if expected['async'] else 'sync'} in 1.10 "
        f"and is {'async' if is_async else 'sync'} now"
    )

    if not expected["async"] and not _returns_awaitable(expected["returns"]):
        actual = getattr(member, "__annotations__", {}).get("return")
        assert not _returns_awaitable(actual), (
            f"{name} returned {expected['returns']} in 1.10 and now returns "
            f"{actual}. Changing a 1.x return type to a coroutine is a "
            f"breaking change: unawaited call sites become unused-coroutine "
            f"errors and Callable[..., None] descriptions become arg-type "
            f"errors. That is the wall this release exists to remove."
        )


def test_the_absent_list_stays_short_and_justified():
    """A guard on the guard. The cheap way to make the parametrised test
    above pass is to add a name here, so the list is pinned to exactly
    what was argued for."""
    assert DELIBERATELY_ABSENT == {"lookup_command"}


def test_the_fixture_describes_1_10_and_not_the_current_build():
    """The fixture must be generated from the tag, never regenerated
    from the code under test - a self-comparison would pass forever
    while proving nothing. Pinned by the counts measured at v1.10.0."""
    assert FIXTURE["_source"].endswith("class Receiver")
    assert "v1.10.0" in FIXTURE["_source"]
    assert len(FIXTURE["properties"]) == 64
    assert len(FIXTURE["methods"]) == 43
    assert sum(v["settable"] for v in FIXTURE["properties"].values()) == 18
