# Known issues

Problems that are understood but not fixed. Each entry says what happens,
why, how to avoid it, and what fixing it would involve.

_No current entries._

## Resolved

### The now-playing poll's HTTP calls are not genuinely cancellable (resolved in 2.0)

The streaming module's HTTP was `http.client` inside `run_in_executor`:
`asyncio.wait_for` cancels the *await*, not the work, so a request already
running in its executor thread ran to completion no matter what - and a
test that failed mid-poll could hang for up to two minutes on teardown.
Issue #45 could only bound the damage (`tests/conftest.py`'s
`_guarantee_disconnect` teardown fixture); it could not remove it.

The 2.0 port of `lyngdorf/streaming/` to aiohttp made every streaming HTTP
call genuinely cancellable - cancelling the poll task now aborts an
in-flight request instead of orphaning it in a thread - which retires this
entry and the two-minute test-hang caveat that came with it. The teardown
fixture remains as hygiene (a failing test still gets its receiver
disconnected), with a short timeout kept purely as a regression guard.
