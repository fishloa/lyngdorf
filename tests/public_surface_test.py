"""The public surface is exactly spec §2 plus the D9 shims (spec §12
WP4 done-when)."""

import inspect
import typing
import warnings

import pytest

import lyngdorf

EXPECTED_ALL = {
    "LyngdorfReceiver",
    "NumericControl",
    "SteppableControl",
    "VolumeControl",
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


# -- 2.1: the shim layer is GONE, and that is what needs proving ------------
#
# These replace the tests that asserted each shim resolved and warned.
# Inverted rather than deleted, in place, so the 2.0 -> 2.1 diff shows the
# removal happening rather than a block of tests silently disappearing -
# and so that a shim reintroduced by accident fails something.

LEGACY_NAMES = [
    "Receiver",
    "async_create_receiver",
    "async_find_receiver_model",
    "async_get_device_serial",
    "lookup_receiver_model",
]


@pytest.mark.parametrize("old", LEGACY_NAMES)
def test_1x_names_no_longer_resolve(old):
    """Hand-written, not derived from a registry: the registry was in
    _compat.py and is deleted, and a list generated from the code under
    test could only ever agree with it."""
    with pytest.raises(AttributeError):
        getattr(lyngdorf, old)


@pytest.mark.parametrize("mod", ["lyngdorf.device", "lyngdorf._compat"])
def test_1x_modules_no_longer_import(mod):
    """`lyngdorf.device` needed to be a real module, because a package
    __getattr__ cannot rescue a submodule path. So its removal has to be
    checked as an import, not an attribute lookup."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(mod)


def test_const_no_longer_re_exports_the_model_enum():
    import lyngdorf.const

    with pytest.raises(AttributeError):
        _ = lyngdorf.const.LyngdorfModel


def test_diagnostics_no_longer_shims_the_1x_probe_name():
    import lyngdorf.diagnostics

    with pytest.raises(AttributeError):
        _ = lyngdorf.diagnostics.async_probe_device_capabilities


def test_model_feature_predicates_are_gone():
    """`has_zone_b_feature` and friends. Capability is structural in 2.x -
    a model without Zone B has no ZoneB object - so these had no job left
    beyond keeping 1.x callers compiling."""
    from lyngdorf.models import LyngdorfModel

    for name in (
        "has_zone_b_feature",
        "has_video_feature",
        "has_surround_feature",
    ):
        assert not hasattr(LyngdorfModel.MP_60, name), name


def test_nothing_still_references_the_deleted_shim_module():
    """The layer was reachable from several places - the package
    __getattr__, the receiver's base class, diagnostics, the model enum.
    Greps the source rather than trusting that the imports above failing
    means every reference went with them."""
    import pathlib as _pathlib

    root = _pathlib.Path(__file__).parent.parent / "lyngdorf"
    offenders = [
        str(f.relative_to(root.parent))
        for f in sorted(root.rglob("*.py"))
        if "_compat" in f.read_text()
    ]
    assert not offenders, f"still referencing the deleted shim layer: {offenders}"


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
        names = list(lyngdorf.__all__)
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
