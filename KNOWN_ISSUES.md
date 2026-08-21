# Known issues

Problems that are understood but not fixed. Each entry says what happens, why,
how to avoid it, and what fixing it would involve.

## The now-playing poll's HTTP calls are not genuinely cancellable

**Fixed for tests as of issue #45**: `tests/conftest.py`'s `_guarantee_disconnect`
autouse fixture tracks every `LyngdorfApi` a test connects and calls
`async_disconnect()` on each one during teardown, whether the test passed,
failed, or raised. A test no longer has to remember to disconnect itself for
the suite to stay well-behaved - see `tests/disconnect_guarantee_test.py`.

**What remains.** Connecting to a streaming-capable model (every model except
the TDAI-2170 and the P series) starts a now-playing poll loop
(`LyngdorfApi._start_now_playing_poll`) that makes real HTTP requests using
`http.client` inside `loop.run_in_executor`. `asyncio.wait_for` cancels the
*await*, not the work: once a request is actually running in its executor
thread, nothing - not `task.cancel()`, not `async_disconnect()`, not this
fixture - can interrupt it mid-flight, because Python will not tear down a
thread-pool worker that is still inside a blocking call. If a test's own
failure happens to land while such a call is already in flight (most likely
against a slow-to-refuse host, e.g. a CI network path that drops packets
instead of returning a fast connection-refused), that specific call still
runs to completion in the background on its own schedule.

`_guarantee_disconnect` does not - and cannot - change that. What it changes
is what happens *around* it:

- `async_disconnect()` is always attempted, immediately, on every path -
  previously nothing called it at all once a test failed, so the poll kept
  retrying indefinitely (`while self._connection_enabled:` never became
  false), each retry a fresh chance to leave another call stuck.
- The disconnect attempt itself is bounded (`_DISCONNECT_TEARDOWN_TIMEOUT`,
  currently 2s): if a receiver's `async_disconnect()` doesn't complete in
  time, the fixture logs a warning and moves on, rather than blocking the
  rest of the suite on a thread that refuses to stop.

So a stray background thread finishing a request against a fake host in the
background is now a bounded, logged, one-off cost instead of an unbounded,
silent, compounding one - but it is a limitation of `http.client`-in-a-thread
being non-cancellable, not something test-side bookkeeping can fully close.

**Fixing it properly** would mean making the streaming HTTP calls genuinely
cancellable - either a socket with a short timeout that is polled cooperatively,
or an async HTTP client rather than `http.client` in a thread. Both are larger
changes than the problem currently justifies, and the async-client route would
add a runtime dependency the library has so far avoided. Worth revisiting if
this starts costing more than an occasional bounded wait and a warning in test
output.
