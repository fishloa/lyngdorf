"""The public surface is exactly spec §2 plus the D9 shims (spec §12
WP4 done-when)."""

import inspect
import warnings

import pytest

import lyngdorf

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
        "lookup_receiver_model",
    ],
)
def test_removals_stay_dead(name):
    with pytest.raises(AttributeError):
        getattr(lyngdorf, name)
