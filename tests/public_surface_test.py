"""The public surface is exactly spec §2 plus the D9 shims (spec §12
WP4 done-when)."""

import inspect
import typing
import warnings

import pytest

import lyngdorf
from lyngdorf import _compat

EXPECTED_ALL = {
    "LyngdorfReceiver",
    "NumericControl",
    "SteppableControl",
    "Trim",
    "ZoneB",
    "Player",
    "Remote",
    "LyngdorfModel",
    "NumericRange",
    "NowPlaying",
    "Control",
    "PlaybackState",
    "PlayMode",
    "Repeat",
    "RemoteKey",
    "LyngdorfError",
    "LyngdorfInvalidValueError",
    "LyngdorfUnsupportedError",
    "UnsupportedModelError",
    "create_receiver",
    "discover_model",
    "lookup_model",
    "discover_ssdp_location",
    "fetch_device_serial",
}


def test_public_exports_match_the_spec():
    assert set(lyngdorf.__all__) == EXPECTED_ALL


def test_receiver_alias_is_a_warning_shim():
    with pytest.warns(DeprecationWarning, match="Receiver"):
        assert lyngdorf.Receiver is lyngdorf.LyngdorfReceiver


@pytest.mark.parametrize("old", sorted(lyngdorf._compat.MODULE_SHIMS))
def test_module_shim_resolves_and_warns(old):
    """D9 category 4 shape: resolving the name warns. The warning fires
    in the module __getattr__, which is PEP 562's idiom, so
    `from lyngdorf import async_create_receiver` warns once at the
    importing module's import, not once per call."""
    with pytest.warns(DeprecationWarning, match="lyngdorf 2.1"):
        getattr(lyngdorf, old)


@pytest.mark.parametrize(
    "old",
    ["async_create_receiver", "async_find_receiver_model", "async_get_device_serial"],
)
def test_module_shim_is_a_coroutine_function(old):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert inspect.iscoroutinefunction(getattr(lyngdorf, old))


def test_shimmed_names_are_not_in_dunder_all():
    assert not (set(lyngdorf._compat.MODULE_SHIMS) & set(lyngdorf.__all__))


@pytest.mark.asyncio
async def test_legacy_get_device_serial_composes_the_split(monkeypatch):
    seen: list[str] = []

    async def _loc(host, timeout=5.0):
        seen.append(host)
        return "http://d/desc.xml"

    async def _serial(location, *, session=None, timeout=5.0):
        seen.append(location)
        return "abc123"

    monkeypatch.setattr("lyngdorf.discovery.discover_ssdp_location", _loc)
    monkeypatch.setattr("lyngdorf.discovery.fetch_device_serial", _serial)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        fn = lyngdorf.async_get_device_serial
    assert await fn("10.0.0.5") == "abc123"
    assert seen == ["10.0.0.5", "http://d/desc.xml"]


@pytest.mark.asyncio
async def test_legacy_get_device_serial_returns_none_without_a_location(monkeypatch):
    async def _loc(host, timeout=5.0):
        return None

    monkeypatch.setattr("lyngdorf.discovery.discover_ssdp_location", _loc)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert await lyngdorf.async_get_device_serial("10.0.0.5") is None


@pytest.mark.parametrize(
    "name",
    [
        "MP40Receiver",
        "MP50Receiver",
        "MP60Receiver",
        "TDAI1120Receiver",
        "TDAI2170Receiver",
        "TDAI2210Receiver",
        "TDAI3400Receiver",
        "P100Receiver",
        "P200Receiver",
        "P300Receiver",
        "supported_models",
    ],
)
def test_removals_stay_dead(name):
    with pytest.raises(AttributeError):
        getattr(lyngdorf, name)


# -- py.typed means nothing where the surface returns Any ---------------------


def _bare_any(annotation: object) -> bool:
    return annotation is typing.Any or str(annotation) in ("Any", "typing.Any")


def _public_callables() -> list[tuple[str, object]]:
    """Every callable a consumer can reach from the package root: the
    module-level functions in __all__, the public methods of the classes
    in __all__, and the deprecated module-level shims."""
    found: list[tuple[str, object]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        names = list(lyngdorf.__all__) + list(_compat.MODULE_SHIMS)
        for name in names:
            obj = getattr(lyngdorf, name, None)
            if inspect.isfunction(obj):
                found.append((name, obj))
            elif inspect.isclass(obj):
                for attr, member in vars(obj).items():
                    if not attr.startswith("_") and inspect.isfunction(member):
                        found.append((f"{obj.__name__}.{attr}", member))
    return found


@pytest.mark.parametrize(
    "name,func", _public_callables(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_no_public_callable_returns_bare_any(name, func):
    """Shipping py.typed asserts the package is typed. One `-> Any` on
    the public surface quietly makes that untrue for everything a caller
    does with the result, and nothing reports it - mypy is silent by
    design when it has been handed Any.

    `create_receiver` was annotated `-> Any` through 1.11.0, 2.0.0 and
    2.0.1. It is the factory for the main object, so the natural
    `receiver = await create_receiver(host)` left every subsequent
    attribute access unchecked, in the one package that had just
    advertised itself as typed. It was a workaround for an import cycle,
    not a deliberate widening.

    Written as a population check rather than a check on that one
    function: the defect was not that a particular annotation was wrong
    but that nothing was asking the question of the surface as a whole.
    Parameter arguments may still be Any where a signature genuinely
    passes anything through - only return types are pinned here.
    """
    try:
        annotation = typing.get_type_hints(func).get("return")
    except Exception:
        # NOT a skip. get_type_hints cannot resolve a name imported only
        # under TYPE_CHECKING - which is exactly how create_receiver's
        # return type is written, so skipping here silently excused the
        # one function this test exists for. That is the same shape as
        # the defect itself: a check that appears to cover something and
        # does not. Fall back to the raw annotation text, which is all
        # this assertion needs.
        annotation = func.__annotations__.get("return")
    assert not _bare_any(annotation), (
        f"{name} returns bare Any. Every call site loses type checking "
        f"from that point on, silently."
    )


def test_the_population_is_not_empty_and_nothing_is_skipped():
    """An empty or silently-skipped parametrize reads like coverage.

    The population must include the factory by name - that is the
    function the whole check exists for, and it was the one being
    skipped.
    """
    names = {n for n, _ in _public_callables()}
    assert len(names) > 20
    assert "create_receiver" in names
    assert "async_create_receiver" in names
