import pytest

from lyngdorf.api import LyngdorfApi


@pytest.fixture(autouse=True)
def _no_setup_command_pacing(monkeypatch):
    """Tests don't talk to real hardware, so the inter-command delay in
    LyngdorfApi._writeSetup (needed to avoid overwhelming a real device with
    a rapid-fire command burst - see SETUP_COMMAND_DELAY in const.py) would
    only slow the suite down for no benefit."""
    monkeypatch.setattr(LyngdorfApi, "setup_command_delay", 0)
