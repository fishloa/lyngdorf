# Known issues

Problems that are understood but not fixed. Each entry says what happens,
why, how to avoid it, and what fixing it would involve.

## Volume writes are silently discarded in standby

Measured on a P200 (firmware p20.5.4.1): with the zone off, `!VOL(-794)`
followed by `!VOL?` returned the unchanged previous value. The device
answers every query while in standby but discards volume writes — no
error, no reply, no state change — so the library cannot tell a
discarded write from one that landed.

Source selection is **not** affected: `!SRC(n)` powers the main zone on
rather than being ignored, so this is specific to volume rather than a
property of writes.

Avoid it by checking `receiver.power_on` before setting volume. Fixing it
properly means raising a distinct, catchable exception from the volume
setters when the zone is known to be off — scoped to where it is
measured, and never raised when `power_on` is `None` (not yet reported),
since a spurious failure during the startup window would be worse than
the bug. Tracked in #59.

## Resolved

### One bounded, discovery-time-only UDP executor hop (resolved in 2.1)

`discover_ssdp_location` ran a blocking `socket.recvfrom()` inside
`loop.run_in_executor`. It was bounded twice and only ran during
discovery, and spec D8 retained it deliberately, citing evidence that 17
of the 86 libraries behind platinum-tier Home Assistant integrations use
an executor.

2.1 removed it anyway (`loop.create_datagram_endpoint`, deliberately not
connected to the remote so a reply from any source port is accepted).
The platinum async-dependency rule admits no exceptions in its own text,
so the evidence D8 rested on argued against the rule rather than
satisfying it. **There is now no `run_in_executor` anywhere in the
library**, and D8 is reversed rather than merely unmet.


### The now-playing poll's HTTP calls are not genuinely cancellable (resolved in 2.0)

The streaming module's HTTP was `http.client` inside `run_in_executor`:
`asyncio.wait_for` cancels the *await*, not the work, so a request already
running in its executor thread ran to completion no matter what — and a
test that failed mid-poll could hang for up to two minutes on teardown.
Issue #45 could only bound the damage (`tests/conftest.py`'s
`_guarantee_disconnect` teardown fixture); it could not remove it.

The 2.0 port of `lyngdorf/streaming/` to aiohttp made every streaming HTTP
call genuinely cancellable — cancelling the poll task now aborts an
in-flight request instead of orphaning it in a thread — which retires this
entry and the two-minute test-hang caveat that came with it. The teardown
fixture remains as hygiene (a failing test still gets its receiver
disconnected), with a short timeout kept purely as a regression guard.
