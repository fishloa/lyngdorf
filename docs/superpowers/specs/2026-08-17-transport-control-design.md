# Playback transport control via the :8080 API

Design for [#32](https://github.com/fishloa/lyngdorf/issues/32). Follows #31
(now-playing metadata) and #33 (playback position), both shipped.

Purpose: let Home Assistant drive playback — pause, next, previous, seek and
shuffle/repeat — through the streaming module's HTTP API. This is the first
feature in the library that *writes* to that API; everything before it was
read-only.

## What the hardware actually does

Established against a real MP-60 (system 5.3.0) and by reading the device's
own web client, which is the only documentation that exists.

**Transport** goes through `player:player/control`, activated rather than
set:

```
GET /api/setData?path=player:player/control&role=activate&value={"control":"pause"}
```

The vendor left the valid actions in a comment in their own JavaScript:
`pause`, `next_`, `previous`, `like`, `dislike` — note the trailing
underscore on `next_`. That comment also claims `seekTime` and `seekTrack`
are "not yet implemented", but the hardware contradicts it: Spotify Connect
advertises `seekTime: true` (below). Treat the comment as stale and the
device's own `controls` payload as the source of truth.

**Play modes** go through `settings:/mediaPlayer/playMode`, set as a value:

```
GET /api/setData?path=settings:/mediaPlayer/playMode&role=value
    &value={"type":"playerPlayMode","playerPlayMode":"shuffle"}
```

Shuffle and repeat are not independent flags but one combined enum. Two
sources describe what is available and they disagree, which matters:
`getRows` on `settings:/mediaPlayer/playModes` returns a *global* list
(`normal`, `shuffle`, `repeatOne`, `shuffleRepeatOne` on the MP-60), while
the now-playing payload's `controls.playMode` returns what the *current
source* supports — which on Spotify Connect includes `repeatAll` and
`shuffleRepeatAll` as well. The per-source dict is authoritative; the global
enum is a fallback for payloads that omit it.

### Two findings that drive the whole design

**The device validates nothing.** Writing the play mode `bogusMode` returns
HTTP 200 and reads back as `bogusMode`. So do `repeatAll` and
`shuffleRepeatAll`, neither of which the MP-60 declares. A successful write
therefore proves nothing about whether the device will honour the value, and
no amount of error handling around the request can tell us otherwise. The
library has to be the gatekeeper, because the device will not be.

**Pause is destructive on controller-driven sources.** On AirPlay, sending
`pause` does not pause. Measured:

```
before : state='playing'  controls={"next_":true,"previous":true,"pause":true}
pause  : state='stopped'  controls={}     ← track metadata gone
pause  : state='stopped'  controls={}     ← does not resume
```

It tears the session down, and the device cannot re-establish it — the
`controls` dict goes empty, so there is nothing left to send. Resume has to
come from the controlling app. This is inherent to AirPlay and the Connect
protocols: the phone is the source, and the device is only a sink.

This also explains the vendor UI's play/pause button, which sends `pause`
when available and `stop` otherwise, but never a `play` command. There *is*
a `play` control, but it takes `mediaRoles`/container arguments — it means
"start playing this item", not "resume".

**Capabilities are per-source, and the difference is large.** AirPlay
advertises only `next_`, `previous`, `pause`. Spotify Connect, streamed
natively by the device, advertises considerably more:

```json
{"previous": true, "pause": true, "next_": true, "seekTime": true,
 "backward15sec": false, "forward15sec": false,
 "playMode": {"shuffle": true, "repeatOne": true, "repeatAll": true,
              "shuffleRepeatOne": true, "shuffleRepeatAll": true}}
```

Three things follow. **Seek is real** - `seekTime` is advertised, despite the
vendor comment claiming it unimplemented, so that comment is stale or refers
to a different path. **The play modes available here include `repeatAll` and
`shuffleRepeatAll`**, which the device's global enum does not list - so
`controls.playMode` is the authoritative per-source capability list and the
global enum is only a fallback. And **`live: true` with
`audioType: audioBroadcast` is reported even by this source**, alongside
`seekTime: true`, so those flags say nothing useful about seekability. Only
`controls` does.

The `backward15sec`/`forward15sec` pair (podcast-style skip) appears as
`false` here, which is a useful reminder that the dict advertises keys set to
`false` as well as `true`: presence is not permission, and the value has to
be checked.

## Design

### Module

A new `lyngdorf/transport.py`. `nowplaying.py` is already around 450 lines
and reads; this writes. Three functions in the style of the existing
helpers, each taking the optional `StreamMagicSession` so they reuse the
poll loop's connection rather than opening sockets of their own:

| Function | Purpose |
|---|---|
| `async_activate_control(host, control, …)` | One transport action |
| `async_seek(host, position_ms, …)` | Seek, via `seekTime` with `time` in ms |
| `async_set_play_mode(host, mode, …)` | Set the combined shuffle/repeat enum |
| `async_fetch_play_modes(host, …)` | Read the device's global enum (fallback) |

Each returns a bool for success and never raises on network failure,
matching the read helpers.

### The capability gate

The core of the design, and the part the no-validation finding makes
mandatory.

`parse_now_playing` currently discards the payload's `controls` dict. It
will capture it instead, as `NowPlaying.controls: frozenset[str]` - built
from the keys whose value is `true`, since the device also advertises
unavailable controls as `false` (`backward15sec` on Spotify Connect).

Transport calls check against that set. Play-mode calls check against
`controls.playMode`, which is per-source and authoritative; the global
`settings:/mediaPlayer/playModes` enum is only a fallback for when the
payload carries no `playMode` key.

A call for something unsupported raises `LyngdorfUnsupportedError` (new, in
`exceptions.py`) instead of sending a request that would return 200 and do
nothing. The alternative — firing and trusting the caller — fails silently
on this hardware, which is the worst possible behaviour for an integration
that a user is watching.

When playback stops, `controls` becomes empty and the gate refuses
everything. That is correct: there is genuinely nothing the device can do
from that state.

### Public API

On `Receiver`:

```python
can_pause / can_next / can_previous / can_seek  -> bool
available_play_modes                 -> tuple[str, ...]
play_mode                            -> str | None

async_pause()          # see warning below
async_next()
async_previous()
async_seek(position_ms)
async_set_play_mode(mode)
```

`can_seek` and `available_play_modes` both read from the live `controls`
payload, so they narrow and widen as the source changes - AirPlay reports no
seek and no play modes, Spotify Connect reports both.

`async_pause()` carries an explicit docstring warning that on
controller-driven sources it ends the session and **cannot be undone from
the device**. This is the most surprising behaviour in the feature and the
likeliest source of a confused bug report, so it belongs in the API
documentation rather than a footnote.

Position, now-playing and the poll loop are untouched.

### Home Assistant integration note

`MediaPlayerEntity.supported_features` is a property re-read on every state
write, so it can legitimately change at runtime — the frontend shows and
hides buttons to match. The integration should map the `can_*` properties
onto it **strictly dynamically**: AirPlay renders pause/next/previous only,
Spotify Connect adds seek and shuffle/repeat.

That means the controls disappear entirely when playback stops, because
`controls` goes empty. This is deliberate rather than a rough edge. On
controller-driven sources a pause genuinely ends the session, so a live pause
button on a stopped device would invite exactly the "why will it not resume"
confusion the teardown behaviour causes. Showing nothing is honest about what
the device can actually do.

The library's job stops at reporting capabilities truthfully; the mapping
lives in the integration.

### Model gating

Transport reuses the existing `has_streaming_feature()` gate: the TDAI-2170
and the P series have no streaming module, so every capability property
reports `False` and every call raises. A test asserts every model is
classified, matching the pattern used for position.

### Testing

Fake-server tests, no device required, following `nowplaying_test.py`:

- gating: allowed calls send, unsupported calls raise
- the empty-`controls` (stopped) case refuses everything
- enum validation rejects `bogusMode` before any request is made
- request URL and payload shape, including the `next_` underscore
- play modes round-trip through the device's declared enum
- non-streaming models raise

Real captures of the `controls` dict in both playing and stopped states join
the existing fixtures.

Hardware verification before release: each transport action against a real
device, confirming the state change — the project's standing rule, and
doubly warranted for writes to an undocumented API.

## Out of scope

**`play` / `playContainer`.** Browse-and-play needs the whole `getRows`
browsing layer — a separate feature deserving its own issue.

**Independent shuffle and repeat flags.** The device models them as one
enum. Presenting them as two booleans would mean read-modify-write on every
change, with a real risk of clobbering the other axis. Expose the enum
honestly and let the caller map it.

## Open questions

**The seek command name.** `controls` advertises the capability as
`seekTime`, the device's own web client sends `{"control":"seek","time":…}`,
and `jsoutter/ha-lyngdorf` sends `seekTime` with `time`. Confirm against
hardware before shipping; the capability flag is not proof of the wire name.

**Whether pause tears down Spotify Connect too.** Measured only on AirPlay,
where it ends the session irrecoverably. Connect is controller-driven in the
same way, so the same behaviour is likely, but it is worth confirming
directly - it determines whether HA can offer `PLAY` on any source at all.

## Home Assistant mapping

| HA feature | Status |
|---|---|
| `PAUSE` | Supported, with the teardown caveat |
| `NEXT_TRACK` / `PREVIOUS_TRACK` | Supported when advertised |
| `PLAY` | Not supported — no resume command exists |
| `STOP` | What `pause` effectively does on Connect sources |
| `SHUFFLE_SET` | Supported where `controls.playMode` offers `shuffle` |
| `REPEAT_SET` | Full off/one/all on Spotify Connect; unavailable on AirPlay |
| `SEEK` | Supported where `controls` offers `seekTime` |
