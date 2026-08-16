# Playback transport control via the :8080 API

Design for [#32](https://github.com/fishloa/lyngdorf/issues/32). Follows #31
(now-playing metadata) and #33 (playback position), both shipped.

Purpose: let Home Assistant drive playback — pause, next, previous, and
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
underscore on `next_`. The same comment records that `seekTime` and
`seekTrack` are "not yet implemented".

**Play modes** go through `settings:/mediaPlayer/playMode`, set as a value:

```
GET /api/setData?path=settings:/mediaPlayer/playMode&role=value
    &value={"type":"playerPlayMode","playerPlayMode":"shuffle"}
```

Shuffle and repeat are not independent flags but one combined enum. The
authoritative list is the device's own, from `getRows` on
`settings:/mediaPlayer/playModes`. On the MP-60 that is `normal`, `shuffle`,
`repeatOne`, `shuffleRepeatOne` — note there is **no `repeatAll`**, though
the vendor's generic web client hardcodes one at that index. The device's
enum wins; the shipped UI is wrong about this model.

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

**Capabilities are per-source.** AirPlay advertises only `next_`,
`previous`, `pause`, and reports `audioType: audioBroadcast` with
`live: true`, which is why it offers no seek. A natively-streamed source may
well advertise more (see Open questions).

## Design

### Module

A new `lyngdorf/transport.py`. `nowplaying.py` is already around 450 lines
and reads; this writes. Three functions in the style of the existing
helpers, each taking the optional `StreamMagicSession` so they reuse the
poll loop's connection rather than opening sockets of their own:

| Function | Purpose |
|---|---|
| `async_activate_control(host, control, …)` | One transport action |
| `async_set_play_mode(host, mode, …)` | Set the combined shuffle/repeat enum |
| `async_fetch_play_modes(host, …)` | Read the device's declared enum |

Each returns a bool for success and never raises on network failure,
matching the read helpers.

### The capability gate

The core of the design, and the part the no-validation finding makes
mandatory.

`parse_now_playing` currently discards the payload's `controls` dict. It
will capture it instead, as `NowPlaying.controls: frozenset[str]`. Transport
calls check against it; play-mode calls check against the enum, fetched once
per queue initialisation and cached.

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
can_pause / can_next / can_previous  -> bool
available_play_modes                 -> tuple[str, ...]
play_mode                            -> str | None

async_pause()          # see warning below
async_next()
async_previous()
async_set_play_mode(mode)
```

`async_pause()` carries an explicit docstring warning that on
controller-driven sources it ends the session and **cannot be undone from
the device**. This is the most surprising behaviour in the feature and the
likeliest source of a confused bug report, so it belongs in the API
documentation rather than a footnote.

Position, now-playing and the poll loop are untouched.

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

**Seek.** The vendor marks it unimplemented, and the two available sources
disagree on the command name (`seek` in the device's web client, `seekTime`
in `jsoutter/ha-lyngdorf`). Revisit only if a source is found that
advertises it.

**`play` / `playContainer`.** Browse-and-play needs the whole `getRows`
browsing layer — a separate feature deserving its own issue.

**Independent shuffle and repeat flags.** The device models them as one
enum. Presenting them as two booleans would mean read-modify-write on every
change, with a real risk of clobbering the other axis. Expose the enum
honestly and let the caller map it.

## Open questions

**Spotify Connect capabilities are uncaptured.** Every measurement so far is
AirPlay, including a phone streaming Spotify *over* AirPlay
(`serviceID: airplay`), which is not the same thing as Spotify Connect. A
natively-streamed source is the most likely to advertise `seekTime`, a real
pause/resume rather than a teardown, and a non-`live` duration. Capture its
`controls` dict before implementing; it may expand what is worth building.
The capability gate means a richer source is picked up automatically, so
this changes scope rather than architecture.

**Whether `repeatAll` is honoured.** The MP-60 accepts and stores it despite
not declaring it. Unknown whether the player logic acts on it. The design
sidesteps this by trusting the declared enum, so HA's repeat-"all" is simply
unavailable on this model.

## Home Assistant mapping

| HA feature | Status |
|---|---|
| `PAUSE` | Supported, with the teardown caveat |
| `NEXT_TRACK` / `PREVIOUS_TRACK` | Supported when advertised |
| `PLAY` | Not supported — no resume command exists |
| `STOP` | What `pause` effectively does on Connect sources |
| `SHUFFLE_SET` | Via the combined enum |
| `REPEAT_SET` | Partial — no `repeatAll` on the MP-60 |
| `SEEK` | Not supported |
