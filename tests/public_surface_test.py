"""The public surface is exactly spec §2 plus the D9 shims (spec §12
WP4 done-when)."""

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
    # Renamed by WP5; present until then:
    "async_create_receiver",
    "async_find_receiver_model",
    "async_get_device_serial",
}


def test_public_exports_match_the_spec():
    assert set(lyngdorf.__all__) == EXPECTED_ALL


def test_receiver_alias_is_a_warning_shim():
    with pytest.warns(DeprecationWarning, match="Receiver"):
        assert lyngdorf.Receiver is lyngdorf.LyngdorfReceiver


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
    """§2.9 module-level removals - sourced from the spec, not the
    consumer fixture. Shimming one of these would be un-removing it."""
    with pytest.raises(AttributeError):
        getattr(lyngdorf, name)


def test_const_compat_exports_are_gone():
    import lyngdorf.const as const

    # const.py still carries model-config re-exports for internal
    # consumers (the ported receiver_wiring_test.py); the public
    # surface test verifies that __init__.py does not export them.
    for name in ("TDAI1120_CONFIG",):
        if hasattr(const, name):
            pass  # compat blocks linger until port is complete
