# Known issues

Problems that are understood but not fixed. Each entry says what happens, why,
how to avoid it, and what fixing it would involve.

## Tests can hang for two minutes when connecting a streaming model to a fake host

**Symptom.** A test hangs for 120 seconds or more instead of failing. It looks
like a flaky or slow test; it is neither. Under CI it may present as a timeout
with no useful output.

**Trigger.** All three conditions together:

1. the test calls `async_connect()` on a receiver whose model has a streaming
   module — every model except the TDAI-2170 and the P series,
2. the host is not a real device (the suite uses `FAKE_IP = "0.0.0.0"`), and
3. the test fails, raises, or otherwise returns before reaching
   `async_disconnect()`.

**Cause.** Connecting starts the now-playing poll loop
(`LyngdorfApi._start_now_playing_poll`, called from
`_async_establish_connection` whenever `has_streaming_feature()` is true). That
loop makes real HTTP requests to `<host>:8080` using `http.client` inside
`loop.run_in_executor`.

`asyncio.wait_for` cancels the *await*, not the work. The executor's worker
thread keeps running the blocking socket call until the operating system gives
up on it, and Python will not tear down a thread-pool worker that is still
inside a blocking call. If the test already failed, nothing calls
`async_disconnect()` to stop the poll task, so teardown waits on a thread that
cannot be interrupted.

Nothing about this is specific to the streaming work — it predates it, and can
be reproduced on any commit where the poll loop exists.

**How to avoid it.** Any of these is enough:

- Wrap connecting tests so disconnect always runs, even on failure — a
  `try`/`finally`, or a fixture that disconnects during teardown. This is the
  right fix for the test and costs nothing.
- Test a non-streaming model (`TDAI_2170`, `P_100`, `P_200`, `P_300`) when the
  test has nothing to do with streaming. No poll loop is started at all.
- Do not call `async_connect()` when you only need to assert on written
  commands. Most of the suite attaches a mock `_protocol` directly and never
  connects, which is faster and avoids this entirely.

**Fixing it properly** would mean making the streaming HTTP calls genuinely
cancellable — either a socket with a short timeout that is polled cooperatively,
or an async HTTP client rather than `http.client` in a thread. Both are larger
changes than the problem currently justifies, and the async-client route would
add a runtime dependency the library has so far avoided. Worth revisiting if the
same hang starts appearing for reasons other than test authorship.
