import asyncio

import pytest

from lyngdorf.api import LyngdorfApi


@pytest.fixture(autouse=True)
def _no_setup_command_pacing(monkeypatch):
    """Tests don't talk to real hardware, so the inter-command delay in
    LyngdorfApi._writeSetup (needed to avoid overwhelming a real device with
    a rapid-fire command burst - see SETUP_COMMAND_DELAY in const.py) would
    only slow the suite down for no benefit."""
    monkeypatch.setattr(LyngdorfApi, "setup_command_delay", 0)
    # Same reasoning for the runtime outbound command queue's own pacing
    # (see COMMAND_PACING_MS in const.py and LyngdorfApi._drain_write_queue) -
    # a test that specifically wants to observe real pacing overrides this
    # back up on its own `api`/`client._api` instance, same pattern as
    # `setup_command_delay` above.
    monkeypatch.setattr(LyngdorfApi, "command_pacing_seconds", 0)


async def flush_write_queue(api: LyngdorfApi, max_iterations: int = 200) -> None:
    """Pump the event loop until `api`'s outbound command queue drains.

    Real writes go through a paced, coalescing queue (see
    `LyngdorfApi._writeCommand`/`_drain_write_queue`) serviced by a
    background task rather than landing on the transport synchronously. A
    test that fires off several commands and then immediately inspects
    what reached the (mocked) transport must give that task a chance to
    run first. Relies on `command_pacing_seconds` being zeroed (see
    `_no_setup_command_pacing` above) - each loop iteration then lets the
    drain task write at most one more already-queued command, since the
    write itself happens synchronously, before that item's own
    `asyncio.sleep`, the moment it is popped.
    """
    for _ in range(max_iterations):
        if not api._write_queue:
            return
        await asyncio.sleep(0)
    raise AssertionError(
        f"write queue for {api.host} did not drain within {max_iterations} "
        "event loop iterations"
    )
