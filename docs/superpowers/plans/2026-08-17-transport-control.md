# Transport Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a consumer pause, skip, seek and set shuffle/repeat on streaming-capable Lyngdorf models, gated on what the device currently advertises.

**Architecture:** `streaming.py` becomes `streaming.py` and gains the write helpers, so one module owns everything spoken to the streaming module on `:8080` — session, parsing, now-playing, position and transport — as against the `:84` RIO protocol in `api.py`. Splitting reads from writes would have divided a single responsibility along a technical seam; both halves share the connection, the URL shapes and the error conventions. Capabilities are captured onto the existing frozen `NowPlaying` from the payload's `controls` dict, so capability changes propagate through the callback that already exists. `LyngdorfApi` and `Receiver` expose gated methods that raise rather than sending a request the device would answer `200` to and ignore.

**Tech Stack:** Python 3.11+, stdlib `http.client` (no new dependencies), pytest, `HTTPServer`-based fake device.

## Global Constraints

- Python 3.11+; no new runtime dependencies — stdlib `http.client` only, matching `streaming.py`.
- All quality gates must pass before each commit: `poetry run pytest`, `poetry run mypy lyngdorf/`, `poetry run ruff check .`, `poetry run black --check .`. In this checkout the venv binary is `.venv/bin/python -m <tool>`.
- No test may require a real device. Fixtures live in `tests/fixtures/` and are verbatim device captures.
- Transport is gated on `has_streaming_feature()`: MP-40/50/60, TDAI-1120/2210/3400 have it; TDAI-2170 and P-100/200/300 do not.
- Capability keys are read from `controls` **only where the value is `true`** — the device advertises unavailable controls as `false` (e.g. `backward15sec`).
- Wire formats confirmed against a real MP-60, do not alter:
  - transport: `GET /api/setData?path=player:player/control&role=activate&value={"control":"<name>"}`
  - next is `next_` with a trailing underscore
  - seek: `{"control":"seekTime","time":<milliseconds>}`
  - play mode: `GET /api/setData?path=settings:/mediaPlayer/playMode&role=value&value={"type":"playerPlayMode","playerPlayMode":"<mode>"}`
- A successful activate returns HTTP 200 with a body of literal `null`; a failure returns HTTP 500 with `{"error":{...}}`. Success **must** be determined from the HTTP status, never from the parsed body, because `null` parses to `None` exactly like a failure does.

---

## File Structure

| File | Responsibility |
|---|---|
| `lyngdorf/streaming.py` | **Renamed from `streaming.py`.** Everything spoken to the `:8080` streaming module: session, parsing, now-playing, position, and the new transport writes |
| `lyngdorf/const.py` | Add `PLAY_MODE_PATH`, `CONTROL_PATH` |
| `lyngdorf/exceptions.py` | Add `LyngdorfUnsupportedError` |
| `lyngdorf/api.py` | Gated async methods on `LyngdorfApi` |
| `lyngdorf/device.py` | `can_*` properties and async methods on `Receiver`, model-gated |
| `tests/streaming_test.py` | **Renamed from `nowplaying_test.py`.** Parsing, session, position |
| `tests/streaming_transport_test.py` | **New.** The transport writes. Split from the above for size, not responsibility — both exercise `streaming.py` |

---

### Task 1: Rename nowplaying.py to streaming.py

Pure refactor: no behaviour change, no new tests. Doing it first means every
later task lands in its final home and no commit has to be rewritten.

**Files:**
- Rename: `lyngdorf/nowplaying.py` → `lyngdorf/streaming.py`
- Rename: `tests/nowplaying_test.py` → `tests/streaming_test.py`
- Modify: `lyngdorf/__init__.py`, `lyngdorf/api.py`, `lyngdorf/device.py`, `examples/monitor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: every public name previously importable from `lyngdorf.nowplaying`
  — `NowPlaying`, `StreamMagicSession`, `parse_now_playing`,
  `parse_position_events`, `async_fetch_now_playing`, `async_fetch_position`,
  `async_init_now_playing_queue`, `async_subscribe_now_playing`,
  `async_poll_now_playing_events` — importable from `lyngdorf.streaming`
  instead, unchanged.

- [ ] **Step 1: Move both files with history preserved**

```bash
git mv lyngdorf/nowplaying.py lyngdorf/streaming.py
git mv tests/nowplaying_test.py tests/streaming_test.py
```

Use `git mv`, not delete-and-create: it keeps `git log --follow` and `git
blame` working, which matters for a file carrying this much
reverse-engineering commentary.

- [ ] **Step 2: Update the import sites**

There are five, all `from .nowplaying import` or `from lyngdorf.nowplaying
import`. Find them:

```bash
grep -rn "nowplaying" lyngdorf tests examples
```

Change each to `streaming`. Do not alter the imported names — only the module
path. `lyngdorf/const.py` and `lyngdorf/models/base.py` mention the word in
prose comments; update those to say `streaming.py` too, so the comments keep
pointing at a file that exists.

- [ ] **Step 3: Widen the module docstring**

`streaming.py` now owns more than now-playing, so replace the opening line of
its docstring:

```python
"""The streaming module's HTTP API.

Streaming-capable Lyngdorf models (see ``ModelConfig.has_streaming``) embed a
StreamUnlimited streaming module that exposes its own HTTP JSON API on port
8080 - unrelated to the ``:84`` RIO protocol the rest of this library speaks.
This module owns everything spoken to it: the connection, now-playing
metadata, playback position, and transport control.
```

Keep the remainder of the existing docstring — the long-poll mechanism, the
websocket findings and the no-vendor-documentation caveat all still apply.

- [ ] **Step 4: Verify nothing changed**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, the same count as before the rename (341).

Run: `.venv/bin/python -m mypy lyngdorf/` — Expected: Success.

Run: `grep -rn "nowplaying" lyngdorf tests examples` — Expected: no output.

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m black --check .
git add -A
git commit -m "Rename nowplaying.py to streaming.py

The module is about to gain transport control, and a file called
nowplaying.py holding pause and seek would undersell it. Splitting reads
from writes was the alternative and it is the wrong seam: both halves talk
to the same streaming module on :8080, share its connection, URL shapes and
error conventions, and differ only in direction.

One module now owns everything spoken to that module, as against the :84
RIO protocol in api.py - a boundary that matches the hardware.

Pure rename via git mv, so history and blame follow. No behaviour change."
```

---

### Task 2: Capture capabilities onto NowPlaying

**Files:**
- Modify: `lyngdorf/streaming.py` (the `NowPlaying` dataclass and `parse_now_playing`)
- Test: `tests/streaming_test.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `NowPlaying.controls: frozenset[str]` and `NowPlaying.play_modes: frozenset[str]`, both defaulting to `frozenset()`. Later tasks read these. The defaults matter — existing tests construct `NowPlaying` positionally with seven arguments and must keep working.

- [ ] **Step 1: Write the failing tests**

Add to `tests/streaming_test.py`, inside `class TestRealCaptures`:

```python
    def test_spotify_connect_capabilities(self):
        """The native source advertises far more than AirPlay."""
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_spotify_connect.json"))
        )
        assert np is not None
        assert "pause" in np.controls
        assert "next_" in np.controls
        assert "previous" in np.controls
        assert "seekTime" in np.controls
        assert "repeatAll" in np.play_modes
        assert "shuffle" in np.play_modes

    def test_false_controls_are_not_capabilities(self):
        """The device advertises unavailable controls as false."""
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_spotify_connect.json"))
        )
        assert np is not None
        assert "backward15sec" not in np.controls
        assert "forward15sec" not in np.controls

    def test_airplay_has_no_seek_or_play_modes(self):
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_airplay.json"))
        )
        assert np is not None
        assert np.controls == frozenset({"pause", "next_", "previous"})
        assert np.play_modes == frozenset()

    def test_play_mode_key_is_not_itself_a_control(self):
        """`playMode` is a nested dict, not a transport action."""
        np = parse_now_playing(
            _unwrap_value(load_fixture("now_playing_spotify_connect.json"))
        )
        assert np is not None
        assert "playMode" not in np.controls
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/streaming_test.py -k "capabilit or false_controls or airplay_has_no or play_mode_key" -v`
Expected: FAIL with `AttributeError: 'NowPlaying' object has no attribute 'controls'`

- [ ] **Step 3: Add the fields and parse them**

In `lyngdorf/streaming.py`, extend the dataclass docstring's `Attributes:` block with:

```
        controls: Transport actions the device currently offers, e.g.
            {"pause", "next_", "previous", "seekTime"}. Source-dependent
            and empty when nothing is playing.
        play_modes: Shuffle/repeat modes the current source offers, e.g.
            {"shuffle", "repeatAll"}. Empty on sources that offer none.
```

Then add the two fields at the **end** of the field list, with defaults:

```python
    duration_ms: int | None
    controls: frozenset[str] = frozenset()
    play_modes: frozenset[str] = frozenset()
```

Add this helper above `parse_now_playing`:

```python
def _enabled_keys(payload: object) -> frozenset[str]:
    """Keys whose value is exactly True.

    The device lists unavailable controls as `false` rather than omitting
    them, so presence is not permission.
    """
    if not isinstance(payload, dict):
        return frozenset()
    return frozenset(k for k, v in payload.items() if v is True)
```

Inside `parse_now_playing`, after the `media_roles` assignment, add:

```python
    controls_payload = payload.get("controls")
    controls_payload = controls_payload if isinstance(controls_payload, dict) else {}
    # `playMode` is a nested capability dict, not a transport action.
    controls = _enabled_keys(
        {k: v for k, v in controls_payload.items() if k != "playMode"}
    )
    play_modes = _enabled_keys(controls_payload.get("playMode"))
```

and pass them to the constructor:

```python
        duration_ms=int(duration) if isinstance(duration, (int, float)) else None,
        controls=controls,
        play_modes=play_modes,
    )
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, all tests including the 341 that existed before.

- [ ] **Step 5: Quality gates and commit**

```bash
.venv/bin/python -m ruff check . --fix
.venv/bin/python -m black .
.venv/bin/python -m mypy lyngdorf/
.venv/bin/python -m pytest -q
git add lyngdorf/streaming.py tests/streaming_test.py
git commit -m "Capture the device's advertised capabilities on NowPlaying

The payload's controls dict was parsed and discarded. It is the only
trustworthy description of what the current source can do, and it varies
widely: AirPlay offers pause/next/previous, Spotify Connect adds seek and
five play modes.

Capabilities are built from keys whose value is true, because the device
advertises unavailable controls as false rather than omitting them.

Carrying them on the frozen NowPlaying means a capability change makes the
object unequal and fires the existing callback, so consumers learn about it
through the path metadata already uses."
```

---

### Task 3: Status-returning request helpers

**Files:**
- Modify: `lyngdorf/streaming.py`
- Test: `tests/streaming_transport_test.py` (create)

**Interfaces:**
- Consumes: `StreamMagicSession`, already on `main`.
- Produces:
  - `StreamMagicSession.get_status(path_and_query: str, timeout: float) -> int | None`
  - `async def _smoip_status(host: str, port: int, path_and_query: str, timeout: float) -> int | None`
  - `async def _get_status(session, host, port, path_and_query, timeout) -> int | None`

  All return the HTTP status code, or `None` on network failure. Task 3 needs these because a successful activate returns a body of literal `null`, which is indistinguishable from failure once parsed.

- [ ] **Step 1: Write the failing test**

Create `tests/streaming_transport_test.py`:

```python
"""Tests for transport control (writes to the :8080 API).

No device required: the fake server from streaming_test stands in.
"""

import json

import pytest

from lyngdorf.streaming import StreamMagicSession, _smoip_status

from .streaming_test import FakeStreamMagicServer, fake_server  # noqa: F401


@pytest.mark.asyncio
async def test_status_helper_reports_200(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    assert await _smoip_status(str(host), port, "/api/getData?path=x", 5.0) == 200


@pytest.mark.asyncio
async def test_status_helper_reports_404(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    assert await _smoip_status(str(host), port, "/nope", 5.0) == 404


@pytest.mark.asyncio
async def test_status_helper_none_on_connection_error():
    assert await _smoip_status("127.0.0.1", 1, "/api/getData?path=x", 0.5) is None


@pytest.mark.asyncio
async def test_session_status_reuses_connection(fake_server: FakeStreamMagicServer):
    host, port = fake_server.server_address
    session = StreamMagicSession(str(host), port)
    fake_server.connections = 0
    try:
        for _ in range(3):
            assert await session.get_status("/api/getData?path=x", 5.0) == 200
    finally:
        session.close()
    assert fake_server.connections == 1
```

`tests/` has no `__init__.py`; if the relative import fails, use `from streaming_test import ...` instead — pytest puts the test directory on `sys.path`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/streaming_transport_test.py -v`
Expected: FAIL with `ImportError: cannot import name '_smoip_status'`

- [ ] **Step 3: Implement the helpers**

In `lyngdorf/streaming.py`, add this method to `StreamMagicSession`, directly after `get`:

```python
    async def get_status(self, path_and_query: str, timeout: float) -> int | None:
        """GET a path and return the HTTP status rather than the body.

        Writes need this: a successful `activate` returns a body of
        literal `null`, which parses to None exactly like a failure, so
        only the status distinguishes them.
        """
        async with self._lock:
            return await self._request_status(path_and_query, timeout)

    async def _request_status(
        self, path_and_query: str, timeout: float
    ) -> int | None:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._fetch_status, path_and_query, timeout),
                timeout=timeout + 1,
            )
        except (TimeoutError, OSError):
            _LOGGER.debug(
                "%s: StreamMagic request to %s failed", self._host, path_and_query
            )
            self.close()
            return None

    def _fetch_status(self, path_and_query: str, timeout: float) -> int | None:
        for attempt in (1, 2):
            reusing = self._conn is not None
            self.reused_connection = reusing
            try:
                if self._conn is None:
                    self._conn = http.client.HTTPConnection(
                        self._host, self._port, timeout=timeout
                    )
                conn = self._conn
                headers = {"Connection": "close"} if self.keep_alive_disabled else {}
                conn.request("GET", path_and_query, headers=headers)
                resp = conn.getresponse()
                resp.read()
                if resp.will_close or self.keep_alive_disabled:
                    self.close()
            except (OSError, http.client.HTTPException):
                self.close()
                if reusing:
                    self._note_reuse_failure()
                    if attempt == 1:
                        continue
                raise
            else:
                if reusing:
                    self._reuse_failures = 0
                return resp.status
        return None
```

Then add these two module-level functions immediately after `_smoip_get`:

```python
async def _smoip_status(
    host: str, port: int, path_and_query: str, timeout: float
) -> int | None:
    """One-shot request returning the HTTP status rather than the body."""
    loop = asyncio.get_running_loop()

    def _fetch() -> int:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path_and_query, headers={"Connection": "close"})
            resp = conn.getresponse()
            resp.read()
            return resp.status
        finally:
            conn.close()

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _fetch), timeout=timeout + 1
        )
    except (TimeoutError, OSError):
        _LOGGER.debug("%s: StreamMagic request to %s failed", host, path_and_query)
        return None


async def _get_status(
    session: StreamMagicSession | None,
    host: str,
    port: int,
    path_and_query: str,
    timeout: float,
) -> int | None:
    """Route a status request through a reused connection when available."""
    if session is not None:
        return await session.get_status(path_and_query, timeout)
    return await _smoip_status(host, port, path_and_query, timeout)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/streaming_transport_test.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Quality gates and commit**

```bash
.venv/bin/python -m ruff check . --fix
.venv/bin/python -m black .
.venv/bin/python -m mypy lyngdorf/
.venv/bin/python -m pytest -q
git add lyngdorf/streaming.py tests/streaming_transport_test.py
git commit -m "Add status-returning request helpers

Writes cannot use the existing helpers to detect success. A successful
activate returns HTTP 200 with a body of literal null, which parses to None
exactly as a failed request does, so the body carries no signal at all and
only the status distinguishes them.

These mirror the read helpers, including connection reuse and the
keep-alive fallback, so writes share the poll loop's connection rather than
opening their own."
```

---

### Task 4: Transport writes

**Files:**
- Modify: `lyngdorf/const.py`
- Modify: `lyngdorf/streaming.py`
- Test: `tests/streaming_transport_test.py`

**Interfaces:**
- Consumes: `_get_status`, `StreamMagicSession` from Task 3.
- Produces:
  - `async def async_activate_control(host, control, port=STREAMMAGIC_PORT, timeout=8.0, session=None) -> bool`
  - `async def async_seek(host, position_ms, port=STREAMMAGIC_PORT, timeout=8.0, session=None) -> bool`
  - `async def async_set_play_mode(host, mode, port=STREAMMAGIC_PORT, timeout=8.0, session=None) -> bool`
  - Constants `CONTROL_PAUSE = "pause"`, `CONTROL_NEXT = "next_"`, `CONTROL_PREVIOUS = "previous"`, `CONTROL_SEEK = "seekTime"`

- [ ] **Step 1: Write the failing tests**

Append to `tests/streaming_transport_test.py`:

```python
from lyngdorf.streaming import (
    CONTROL_NEXT,
    CONTROL_PAUSE,
    CONTROL_PREVIOUS,
    CONTROL_SEEK,
    async_activate_control,
    async_seek,
    async_set_play_mode,
)


class TestTransportWireFormat:
    """The exact requests confirmed against a real MP-60."""

    @pytest.mark.asyncio
    async def test_pause_request_shape(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        assert await async_activate_control(str(host), CONTROL_PAUSE, port) is True
        path = fake_server.last_path
        assert "/api/setData" in path
        assert "path=player%3Aplayer%2Fcontrol" in path
        assert "role=activate" in path
        assert json.dumps({"control": "pause"}) in _unquote(path)

    @pytest.mark.asyncio
    async def test_next_uses_trailing_underscore(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        await async_activate_control(str(host), CONTROL_NEXT, port)
        assert '"control": "next_"' in _unquote(fake_server.last_path)

    @pytest.mark.asyncio
    async def test_seek_sends_milliseconds(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        assert await async_seek(str(host), 60000, port) is True
        body = _unquote(fake_server.last_path)
        assert '"control": "seekTime"' in body
        assert '"time": 60000' in body

    @pytest.mark.asyncio
    async def test_play_mode_request_shape(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        assert await async_set_play_mode(str(host), "shuffle", port) is True
        path = _unquote(fake_server.last_path)
        assert "path=settings:/mediaPlayer/playMode" in path
        assert "role=value" in path
        assert '"playerPlayMode": "shuffle"' in path
        assert '"type": "playerPlayMode"' in path

    @pytest.mark.asyncio
    async def test_failure_returns_false(self, fake_server: FakeStreamMagicServer):
        """The device answers a rejected control with HTTP 500."""
        fake_server.fail_writes = True
        host, port = fake_server.server_address
        assert await async_activate_control(str(host), CONTROL_PAUSE, port) is False

    @pytest.mark.asyncio
    async def test_network_failure_returns_false(self):
        assert await async_activate_control("127.0.0.1", CONTROL_PREVIOUS, 1, 0.5) is False

    @pytest.mark.asyncio
    async def test_uses_session_when_given(self, fake_server: FakeStreamMagicServer):
        host, port = fake_server.server_address
        session = StreamMagicSession(str(host), port)
        fake_server.connections = 0
        try:
            for control in (CONTROL_PAUSE, CONTROL_NEXT, CONTROL_PREVIOUS):
                assert await async_activate_control(
                    str(host), control, port, session=session
                )
        finally:
            session.close()
        assert fake_server.connections == 1
```

Add this helper near the top of `tests/streaming_transport_test.py`, below the imports:

```python
from urllib.parse import unquote


def _unquote(path: str) -> str:
    return unquote(path)
```

The fake server needs to record the last path and be able to fail writes. In `tests/streaming_test.py`, add to `FakeStreamMagicServer`:

```python
    last_path: str = ""
    fail_writes: bool = False
```

and at the very top of `_NowPlayingHandler.do_GET`, before the existing branches:

```python
        self.server.last_path = self.path
        if "/api/setData" in self.path:
            if self.server.fail_writes:
                body = b'{"error":{"title":"Error","message":"failed"}}'
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.write(body)
            else:
                self._respond(b"null")
            return
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/streaming_transport_test.py -q`
Expected: FAIL with `ImportError: cannot import name 'async_activate_control'`

- [ ] **Step 3: Add the constants**

In `lyngdorf/const.py`, directly below `NOW_PLAYING_POSITION_PATH`:

```python
# Transport control. `activate` rather than `value`: this node is an action,
# not a setting. Confirmed against a real MP-60 - see lyngdorf/streaming.py.
CONTROL_PATH = "player:player/control"
# Combined shuffle/repeat mode. One enum, not two independent flags.
PLAY_MODE_PATH = "settings:/mediaPlayer/playMode"
```

and add both names to `__all__`, next to `"NOW_PLAYING_POSITION_PATH",`:

```python
    "CONTROL_PATH",
    "PLAY_MODE_PATH",
```

- [ ] **Step 4: Add the transport section**

Append to `lyngdorf/streaming.py`, below the read helpers, under a section
comment:

```python
# -- Transport control (writes) ------------------------------------------
#
# Everything below writes to the device. Two behaviours are worth knowing
# before calling any of it.

**The device validates nothing.** Setting the play mode `bogusMode`
returns HTTP 200 and reads back as `bogusMode`; so do modes the device
does not declare. A request succeeding says only that it was accepted,
never that it will be honoured. Callers must check `NowPlaying.controls`
and `NowPlaying.play_modes` first - `LyngdorfApi` does.

**Pause means different things on different sources.** Where the device
does its own streaming, as with Spotify Connect, `pause` toggles: playing
to paused and back again, since there is no separate resume command. On
AirPlay and other controller-driven sources the same command ends the
session outright, and the device cannot restart it - only the controlling
app can. The device reports which happened: a real pause leaves `controls`
populated, a teardown empties it.

:license: MIT, see LICENSE for more details.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import quote

from .const import CONTROL_PATH, PLAY_MODE_PATH, STREAMMAGIC_PORT
from .nowplaying import StreamMagicSession, _get_status

_LOGGER = logging.getLogger(__package__)

CONTROL_PAUSE = "pause"
CONTROL_NEXT = "next_"
CONTROL_PREVIOUS = "previous"
CONTROL_SEEK = "seekTime"


async def _activate(
    host: str,
    payload: dict,
    port: int,
    timeout: float,
    session: StreamMagicSession | None,
) -> bool:
    """POST-less write to the control node, reporting HTTP success.

    Success is read from the status, never the body: the device answers a
    successful activate with literal `null`, which parses to None exactly
    as a failure does.
    """
    status = await _get_status(
        session,
        host,
        port,
        f"/api/setData?path={quote(CONTROL_PATH)}"
        f"&role=activate&value={quote(json.dumps(payload))}",
        timeout,
    )
    if status != 200:
        _LOGGER.debug("%s: control %s rejected (status %s)", host, payload, status)
    return status == 200


async def async_activate_control(
    host: str,
    control: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> bool:
    """Send one transport action, e.g. `CONTROL_PAUSE`.

    Returns False on rejection or network failure rather than raising.
    """
    return await _activate(host, {"control": control}, port, timeout, session)


async def async_seek(
    host: str,
    position_ms: int,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> bool:
    """Seek to an absolute position, in milliseconds.

    The device's own web client sends `{"control": "seek", ...}`, which is
    wrong - that is parsed as the browse-and-play control and answered
    with HTTP 500 "Directory is empty. No playable items found."
    """
    return await _activate(
        host, {"control": CONTROL_SEEK, "time": int(position_ms)}, port, timeout, session
    )


async def async_set_play_mode(
    host: str,
    mode: str,
    port: int = STREAMMAGIC_PORT,
    timeout: float = 8.0,
    session: StreamMagicSession | None = None,
) -> bool:
    """Set the combined shuffle/repeat mode, e.g. "shuffle", "repeatAll".

    One enum rather than two flags, so setting it replaces both axes at
    once.
    """
    value = json.dumps({"type": "playerPlayMode", "playerPlayMode": mode})
    status = await _get_status(
        session,
        host,
        port,
        f"/api/setData?path={quote(PLAY_MODE_PATH)}&role=value&value={quote(value)}",
        timeout,
    )
    if status != 200:
        _LOGGER.debug("%s: play mode %r rejected (status %s)", host, mode, status)
    return status == 200
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/streaming_transport_test.py -q`
Expected: PASS

- [ ] **Step 6: Quality gates and commit**

```bash
.venv/bin/python -m ruff check . --fix
.venv/bin/python -m black .
.venv/bin/python -m mypy lyngdorf/
.venv/bin/python -m pytest -q
git add lyngdorf/streaming.py lyngdorf/const.py tests/
git commit -m "Add transport write helpers for the :8080 API

pause, next, previous, seek and play mode, in the style of the read
helpers and sharing their connection.

Success is taken from the HTTP status rather than the body, because the
device answers a successful activate with literal null - indistinguishable
from a failure once parsed.

Seek is {\"control\":\"seekTime\",\"time\":<ms>}. The device's own web client
sends {\"control\":\"seek\"}, which is parsed as browse-and-play and answered
with HTTP 500; the wire format here is the one that actually seeks."
```

---

### Task 5: Gated methods on LyngdorfApi

**Files:**
- Modify: `lyngdorf/exceptions.py`, `lyngdorf/api.py`
- Test: `tests/streaming_transport_test.py`

**Interfaces:**
- Consumes: `NowPlaying.controls`/`play_modes` (Task 2), the transport helpers (Task 4).
- Produces on `LyngdorfApi`: `available_controls -> frozenset[str]`, `available_play_modes -> frozenset[str]`, and `async_pause()`, `async_next()`, `async_previous()`, `async_seek(position_ms)`, `async_set_play_mode(mode)`, each returning `bool` and raising `LyngdorfUnsupportedError` when the capability is absent.

- [ ] **Step 1: Write the failing tests**

Append to `tests/streaming_transport_test.py`:

```python
from lyngdorf.api import LyngdorfApi
from lyngdorf.const import LyngdorfModel
from lyngdorf.exceptions import LyngdorfUnsupportedError
from lyngdorf.streaming import NowPlaying


def _np(controls=(), play_modes=()):
    return NowPlaying(
        "playing", "T", None, None, None, None, None,
        frozenset(controls), frozenset(play_modes),
    )


class TestApiGating:
    """The device accepts anything, so the library must refuse."""

    @pytest.mark.asyncio
    async def test_pause_raises_when_not_advertised(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(controls=["next_"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_pause()

    @pytest.mark.asyncio
    async def test_seek_raises_when_not_advertised(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(controls=["pause"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_seek(1000)

    @pytest.mark.asyncio
    async def test_everything_raises_when_stopped(self):
        """Stopped devices report no controls at all."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(None)
        for call in (api.async_pause(), api.async_next(), api.async_previous()):
            with pytest.raises(LyngdorfUnsupportedError):
                await call

    @pytest.mark.asyncio
    async def test_play_mode_raises_when_not_offered(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["shuffle"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_play_mode("repeatAll")

    @pytest.mark.asyncio
    async def test_bogus_play_mode_never_reaches_the_device(self):
        """The device would answer 200 and store it."""
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        api._update_now_playing(_np(play_modes=["shuffle"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_set_play_mode("bogusMode")

    @pytest.mark.asyncio
    async def test_non_streaming_model_raises(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.TDAI_2170)
        api._update_now_playing(_np(controls=["pause"]))
        with pytest.raises(LyngdorfUnsupportedError):
            await api.async_pause()

    def test_available_sets_reflect_now_playing(self):
        api = LyngdorfApi("127.0.0.1", LyngdorfModel.MP_60)
        assert api.available_controls == frozenset()
        api._update_now_playing(_np(controls=["pause"], play_modes=["shuffle"]))
        assert api.available_controls == frozenset({"pause"})
        assert api.available_play_modes == frozenset({"shuffle"})

    @pytest.mark.asyncio
    async def test_supported_call_reaches_the_device(
        self, fake_server: FakeStreamMagicServer
    ):
        host, port = fake_server.server_address
        api = LyngdorfApi(str(host), LyngdorfModel.MP_60)
        api.streammagic_port = port
        api._update_now_playing(_np(controls=["pause"]))
        assert await api.async_pause() is True
        assert '"control": "pause"' in _unquote(fake_server.last_path)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/streaming_transport_test.py -k Gating -q`
Expected: FAIL with `ImportError: cannot import name 'LyngdorfUnsupportedError'`

- [ ] **Step 3: Add the exception**

Append to `lyngdorf/exceptions.py`:

```python
class LyngdorfUnsupportedError(LyngdorfError):
    """Raised when asking a device to do something it does not offer.

    The streaming module accepts anything - an unknown play mode returns
    HTTP 200 and is stored - so a request succeeding proves nothing. The
    library refuses up front instead, based on what the device advertises
    for the current source.
    """
```

- [ ] **Step 4: Implement the API methods**

In `lyngdorf/api.py`, add to the imports:

```python
from .exceptions import LyngdorfUnsupportedError
from .transport import (
    CONTROL_NEXT,
    CONTROL_PAUSE,
    CONTROL_PREVIOUS,
    CONTROL_SEEK,
    async_activate_control,
    async_seek,
    async_set_play_mode,
)
```

Then add these members, directly after `register_position_callback`:

```python
    @property
    def available_controls(self) -> frozenset[str]:
        """Transport actions the current source offers, or empty."""
        if not self._model.has_streaming_feature() or self._now_playing is None:
            return frozenset()
        return self._now_playing.controls

    @property
    def available_play_modes(self) -> frozenset[str]:
        """Shuffle/repeat modes the current source offers, or empty."""
        if not self._model.has_streaming_feature() or self._now_playing is None:
            return frozenset()
        return self._now_playing.play_modes

    def _require_control(self, control: str) -> None:
        if control not in self.available_controls:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer {control!r} "
                f"(available: {sorted(self.available_controls) or 'none'})"
            )

    async def async_pause(self) -> bool:
        """Toggle pause on the current source.

        The device has no separate resume: on a source it streams itself
        this pauses a playing track and resumes a paused one. On AirPlay
        and other controller-driven sources it instead ends the session,
        which cannot be undone from the device.
        """
        self._require_control(CONTROL_PAUSE)
        return await async_activate_control(
            self.host, CONTROL_PAUSE, self.streammagic_port
        )

    async def async_next(self) -> bool:
        """Skip to the next track."""
        self._require_control(CONTROL_NEXT)
        return await async_activate_control(
            self.host, CONTROL_NEXT, self.streammagic_port
        )

    async def async_previous(self) -> bool:
        """Skip to the previous track."""
        self._require_control(CONTROL_PREVIOUS)
        return await async_activate_control(
            self.host, CONTROL_PREVIOUS, self.streammagic_port
        )

    async def async_seek(self, position_ms: int) -> bool:
        """Seek to an absolute position, in milliseconds."""
        self._require_control(CONTROL_SEEK)
        return await async_seek(self.host, position_ms, self.streammagic_port)

    async def async_set_play_mode(self, mode: str) -> bool:
        """Set the combined shuffle/repeat mode."""
        if mode not in self.available_play_modes:
            raise LyngdorfUnsupportedError(
                f"{self.host}: device does not currently offer play mode {mode!r} "
                f"(available: {sorted(self.available_play_modes) or 'none'})"
            )
        return await async_set_play_mode(self.host, mode, self.streammagic_port)
```

Note `streammagic_port` is a class attribute, so the test assigning `api.streammagic_port = port` shadows it per-instance, which is the existing pattern.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/streaming_transport_test.py -q`
Expected: PASS

- [ ] **Step 6: Quality gates and commit**

```bash
.venv/bin/python -m ruff check . --fix
.venv/bin/python -m black .
.venv/bin/python -m mypy lyngdorf/
.venv/bin/python -m pytest -q
git add lyngdorf/api.py lyngdorf/exceptions.py tests/streaming_transport_test.py
git commit -m "Gate transport calls on what the device advertises

The streaming module validates nothing: an unknown play mode returns HTTP
200 and is stored, so firing a request and trusting the response cannot
tell a caller whether anything happened. The library refuses up front
instead, from the controls the device reports for the current source.

Refusing raises rather than returning False, so a caller cannot mistake
'this device cannot do that' for 'the request failed'.

A stopped device reports no controls at all, so everything raises - which
is correct, since there is genuinely nothing it can do from that state."
```

---

### Task 6: Receiver surface and hardware verification

**Files:**
- Modify: `lyngdorf/device.py`
- Test: `tests/streaming_transport_test.py`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces on `Receiver`: `can_pause`, `can_next`, `can_previous`, `can_seek` (all `bool`), `available_play_modes -> frozenset[str]`, and `async_pause()`, `async_next()`, `async_previous()`, `async_seek(position_ms)`, `async_set_play_mode(mode)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/streaming_transport_test.py`:

```python
from lyngdorf.device import Receiver


class TestReceiverCapabilities:
    STREAMING = [
        LyngdorfModel.MP_40, LyngdorfModel.MP_50, LyngdorfModel.MP_60,
        LyngdorfModel.TDAI_1120, LyngdorfModel.TDAI_2210, LyngdorfModel.TDAI_3400,
    ]
    NON_STREAMING = [
        LyngdorfModel.TDAI_2170,
        LyngdorfModel.P_100, LyngdorfModel.P_200, LyngdorfModel.P_300,
    ]

    def test_every_model_is_covered(self):
        assert set(self.STREAMING) | set(self.NON_STREAMING) == set(LyngdorfModel)

    def test_capabilities_follow_the_source(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        assert (r.can_pause, r.can_next, r.can_previous, r.can_seek) == (
            False, False, False, False
        )
        # AirPlay: no seek
        r._api._update_now_playing(_np(controls=["pause", "next_", "previous"]))
        assert (r.can_pause, r.can_next, r.can_previous, r.can_seek) == (
            True, True, True, False
        )
        # Spotify Connect: adds seek and play modes
        r._api._update_now_playing(
            _np(controls=["pause", "next_", "previous", "seekTime"],
                play_modes=["shuffle", "repeatAll"])
        )
        assert r.can_seek is True
        assert r.available_play_modes == frozenset({"shuffle", "repeatAll"})

    def test_capabilities_vanish_when_stopped(self):
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        r._api._update_now_playing(_np(controls=["pause", "seekTime"]))
        r._api._update_now_playing(None)
        assert (r.can_pause, r.can_seek) == (False, False)
        assert r.available_play_modes == frozenset()

    @pytest.mark.parametrize("model", NON_STREAMING)
    def test_non_streaming_models_offer_nothing(self, model):
        r = Receiver("127.0.0.1", model)
        r._api._update_now_playing(_np(controls=["pause"], play_modes=["shuffle"]))
        assert (r.can_pause, r.can_next, r.can_previous, r.can_seek) == (
            False, False, False, False
        )
        assert r.available_play_modes == frozenset()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", NON_STREAMING)
    async def test_non_streaming_models_raise(self, model):
        r = Receiver("127.0.0.1", model)
        with pytest.raises(LyngdorfUnsupportedError):
            await r.async_pause()

    def test_capability_change_fires_the_existing_callback(self):
        """This is how Home Assistant learns to redraw its buttons."""
        r = Receiver("127.0.0.1", LyngdorfModel.MP_60)
        seen = []
        r.register_notification_callback(lambda: seen.append(r.can_seek))
        r._api._update_now_playing(_np(controls=["pause"]))
        r._api._update_now_playing(_np(controls=["pause", "seekTime"]))
        assert seen == [False, True]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/streaming_transport_test.py -k Receiver -q`
Expected: FAIL with `AttributeError: 'MP60Receiver' object has no attribute 'can_pause'`

- [ ] **Step 3: Implement the Receiver surface**

In `lyngdorf/device.py`, add to the imports:

```python
from .transport import CONTROL_NEXT, CONTROL_PAUSE, CONTROL_PREVIOUS, CONTROL_SEEK
```

Then add these members directly after `position_percent`:

```python
    @property
    def can_pause(self) -> bool:
        """Whether the current source offers pause.

        Narrows and widens as the source changes, and is False whenever
        nothing is playing.
        """
        return CONTROL_PAUSE in self._api.available_controls

    @property
    def can_next(self) -> bool:
        """Whether the current source offers skip-forward."""
        return CONTROL_NEXT in self._api.available_controls

    @property
    def can_previous(self) -> bool:
        """Whether the current source offers skip-back."""
        return CONTROL_PREVIOUS in self._api.available_controls

    @property
    def can_seek(self) -> bool:
        """Whether the current source offers seek.

        AirPlay does not; Spotify Connect does. Note the payload's `live`
        and `audioType` fields say nothing useful about this - both
        sources report `live: true`.
        """
        return CONTROL_SEEK in self._api.available_controls

    @property
    def available_play_modes(self) -> frozenset[str]:
        """Shuffle/repeat modes the current source offers."""
        return self._api.available_play_modes

    async def async_pause(self) -> bool:
        """Toggle pause on the current source.

        There is no separate resume: on a source the device streams
        itself this pauses a playing track and resumes a paused one.

        On AirPlay and other controller-driven sources it instead ends the
        session, and the device cannot restart it - only the controlling
        app can. Afterwards the device reports no controls at all, so
        `can_pause` becomes False.
        """
        return await self._api.async_pause()

    async def async_next(self) -> bool:
        """Skip to the next track."""
        return await self._api.async_next()

    async def async_previous(self) -> bool:
        """Skip to the previous track."""
        return await self._api.async_previous()

    async def async_seek(self, position_ms: int) -> bool:
        """Seek to an absolute position, in milliseconds."""
        return await self._api.async_seek(position_ms)

    async def async_set_play_mode(self, mode: str) -> bool:
        """Set the combined shuffle/repeat mode, e.g. "shuffle"."""
        return await self._api.async_set_play_mode(mode)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Quality gates and commit**

```bash
.venv/bin/python -m ruff check . --fix
.venv/bin/python -m black .
.venv/bin/python -m mypy lyngdorf/
.venv/bin/python -m pytest -q
git add lyngdorf/device.py tests/streaming_transport_test.py
git commit -m "Expose transport capabilities and controls on Receiver

can_pause/can_next/can_previous/can_seek narrow and widen with the source
and go False when nothing is playing, so a consumer can render exactly the
controls that will work. AirPlay reports three; Spotify Connect adds seek
and five play modes.

Capability changes ride the existing notification callback, since controls
sit on the frozen NowPlaying and any change makes it unequal. A Home
Assistant entity therefore redraws its buttons on the path metadata
already uses, with no extra plumbing.

Non-streaming models report nothing and raise on every call."
```

- [ ] **Step 6: Verify on real hardware**

Not optional — this is the project's standing rule, and these are writes to an undocumented API. Requires a streaming-capable device playing from a source it streams itself (Spotify Connect, not AirPlay — AirPlay cannot resume, so pause there ends the test).

Write `/tmp/verify_transport.py`:

```python
import asyncio, sys
sys.path.insert(0, "/Volumes/External/Projects/lyngdorf")
from lyngdorf.const import LyngdorfModel
from lyngdorf.device import async_create_receiver

HOST = "192.168.16.16"

async def main():
    r = await async_create_receiver(HOST, LyngdorfModel.MP_60)
    await r.async_connect()
    await asyncio.sleep(4)

    print(f"caps: pause={r.can_pause} next={r.can_next} "
          f"prev={r.can_previous} seek={r.can_seek}")
    print(f"play modes: {sorted(r.available_play_modes)}")
    print(f"now playing: {r.now_playing.title if r.now_playing else None}")

    start = r.position_ms
    print(f"\nseek: {start} -> 60000")
    await r.async_seek(60000)
    await asyncio.sleep(3)
    print(f"  position now {r.position_ms} (expect ~60000-63000)")

    print("\npause (expect state 'paused', capabilities intact)")
    await r.async_pause()
    await asyncio.sleep(3)
    print(f"  state={r.now_playing.state if r.now_playing else None} "
          f"can_pause={r.can_pause}")

    print("\npause again (expect resume)")
    await r.async_pause()
    await asyncio.sleep(3)
    print(f"  state={r.now_playing.state if r.now_playing else None}")

    await r.async_disconnect()

asyncio.run(main())
```

Run: `.venv/bin/python /tmp/verify_transport.py`

Expected: `can_seek=True`, five play modes, position lands near 60000, pause reports `paused` with capabilities intact, second pause returns to `playing`.

Do not mark this task complete on compilation or green tests alone. If any check fails, stop and report rather than adjusting the expectations.

- [ ] **Step 7: Close the issue**

Once hardware verification passes:

```bash
gh issue close 32 --repo fishloa/lyngdorf --reason completed
```

Include in the closing comment: the confirmed wire formats, that pause toggles on device-streamed sources but tears down on AirPlay, and that the Home Assistant integration work (dynamic `supported_features`) is a separate pull request against `home-assistant/core`.

---

## Out of Scope

Deliberately excluded, per the design:

- **`play` / `playContainer`** — browse-and-play needs the whole `/api/getRows` browsing layer; its own issue.
- **`STOP`** — nothing advertises a stop control. The AirPlay teardown is a side effect of `pause`, not a feature.
- **`like` / `dislike`** — listed as valid actions by the vendor but with no Home Assistant equivalent.
- **Independent shuffle and repeat booleans** — the device models them as one enum; splitting them would mean read-modify-write on every change, risking clobbering the other axis.
- **`async_fetch_play_modes`, the global-enum fallback** the design mentions. Every payload observed carries `controls.playMode`, which is both per-source and a superset of the global enum, so a second code path would be unexercised. Add it only if a source turns up that omits `playMode` while still supporting modes.
