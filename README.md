# Lyngdorf Audio Control Library

Python library to control Lyngdorf A/V processors and integrated amplifiers over TCP/IP (port 84).

[![Tests](https://github.com/fishloa/lyngdorf/workflows/Run%20tests/badge.svg)](https://github.com/fishloa/lyngdorf/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Supported Models

### MP Series (Multichannel Processors)
- **MP-40** - Entry-level processor (3 HDMI inputs, 12-channel decoding)
- **MP-50** - Mid-level processor (8 HDMI inputs, 11.1 + 4 aux)
- **MP-60** - Flagship processor (8 HDMI inputs, 16-channel decoding)

### TDAI Series (Integrated Amplifiers)
- **TDAI-1120** - Entry-level integrated amplifier
- **TDAI-2170** - Older integrated amplifier model, with a more limited protocol
- **TDAI-2210** - Integrated amplifier sharing the TDAI-1120/3400 protocol
- **TDAI-3400** - Top-of-line networked integrated amplifier

### P Series (Cinema Processors)
- **P100** - Entry-level cinema processor (4 HDMI inputs, no video output routing)
- **P200** - Mid-level cinema processor (9 HDMI inputs, up to 5 HDMI outputs)
- **P300** - Flagship cinema processor (9 HDMI inputs, up to 5 HDMI outputs)

The P series are cinema/multichannel processors with no built-in streaming
module and no discrete channel trim controls.

All models support:
- Power control
- Volume/mute control
- Source selection
- RoomPerfect™ room correction
- Voicing selection
- Trim controls (bass, treble, center, height, LFE, surround) - MP and TDAI series
- Zone B control (MP and P series)

## Installation

### From PyPI
```bash
pip install lyngdorf
```

### From Source
```bash
git clone https://github.com/fishloa/lyngdorf.git
cd lyngdorf
poetry install
```

## Quick Start

```python
import asyncio
from lyngdorf import async_create_receiver, LyngdorfModel

async def main():
    # Auto-detect model (recommended)
    receiver = await async_create_receiver("192.168.1.100")

    # Or specify model explicitly
    receiver = await async_create_receiver("192.168.1.100", LyngdorfModel.MP_60)

    # Connect to the receiver
    await receiver.async_connect()

    # Control the receiver
    receiver.power_on = True
    print(f"Volume: {receiver.volume} dB")
    receiver.volume = -22.5
    receiver.mute_enabled = False

    # Change source
    receiver.source = "HDMI 1"

    # RoomPerfect control
    receiver.room_perfect_position = "Focus 1"

    # Disconnect when done
    await receiver.async_disconnect()

asyncio.run(main())
```

## Usage Examples

### Power Control
```python
receiver.power_on = True   # Turn on
receiver.power_on = False  # Turn off
print(receiver.power_on)   # Check power state
```

### Volume Control
```python
receiver.volume = -25.0   # Set volume in dB
receiver.volume_up()      # Increase volume
receiver.volume_down()    # Decrease volume
receiver.mute_enabled = True  # Mute

# The device's current user-settable safety ceiling, in dB (MP series only,
# None on models that don't report it). Not a hardware maximum, and it can
# change at runtime - see max_volume's docstring before using it as a fixed
# slider bound.
print(receiver.max_volume)
```

### Source Selection
```python
# List available sources
print(receiver.available_sources)

# Select source by name
receiver.source = "HDMI 1"
```

### Audio/Video Inputs & Stream Types
```python
# Enumerate the possible values before building a closed-option UI
print(receiver.available_audio_inputs)
print(receiver.available_video_inputs)
print(receiver.available_stream_types)

# Current values
print(receiver.audio_input, receiver.video_input, receiver.streaming_source)
```

Empty for a model with no such table at all (e.g. a TDAI has no video inputs).
An unrecognised wire value deliberately escapes the table rather than being
added to it - see `available_audio_inputs`'s docstring - so a current value is
not guaranteed to appear in its corresponding `available_*` list.

### RoomPerfect™ & Voicing
```python
# List available positions
print(receiver.available_room_perfect_positions)

# Select position
receiver.room_perfect_position = "Focus 1"
receiver.room_perfect_position = "Global"
receiver.room_perfect_position = "Bypass"

# List available voicings
print(receiver.available_voicings)

# Select voicing
receiver.voicing = "Neutral"
```

### Trim Controls (MP Series)
```python
# Adjust trim levels (in dB)
receiver.trim_bass = 1.5      # +1.5 dB
receiver.trim_treble = -0.5   # -0.5 dB
receiver.trim_centre = 0.0    # Reset to 0 dB
receiver.trim_height = 2.0
receiver.trim_lfe = -1.0
receiver.trim_surround = 0.5

# Or use increment/decrement
receiver.trim_bass_up()
receiver.trim_bass_down()
```

### Numeric Ranges & Lip Sync
```python
# Each adjustable numeric setting has a matching *_range property -
# NumericRange(min, max, step) - None on a model with no such setting at
# all (e.g. trim_centre_range is None on every TDAI; every trim range is
# None on the P series). A UI (e.g. Home Assistant's `number` platform)
# should build its slider bounds from these instead of hardcoding them -
# they vary by model, and the MP series' 0.1 dB step genuinely differs
# from the TDAI series' whole-dB-only one even where the dB bound matches.
print(receiver.trim_bass_range)     # NumericRange(-12.0, 12.0, 0.1) on an MP
print(receiver.trim_centre_range)   # None on a TDAI - no discrete channel trims

# lipsync_range is a live property: it starts at the documented default
# (NumericRange(0, 500, 1)) and is overwritten once the device answers its
# own LIPSYNCRANGE? query - re-read it rather than caching it once. None
# on the TDAI family, which has no lip sync control at all.
print(receiver.lipsync_range)
receiver.lipsync = 20   # ms
```

### Zone B Control (MP Series)
```python
# Zone B power
receiver.zone_b_power_on = True

# Zone B volume
receiver.zone_b_volume = -30.0
receiver.zone_b_volume_up()
receiver.zone_b_volume_down()

# Zone B source
receiver.zone_b_source = "Apple TV"
```

### Callbacks & Events
```python
# Register for any state change (volume, source, power, now-playing, etc.)
def on_any_change():
    print("Receiver state changed")

unsubscribe = receiver.register_notification_callback(on_any_change)

# Detach later - e.g. when a Home Assistant entity is removed, or a config
# entry is reloaded. Safe to call more than once.
unsubscribe()
```

Every `register_*` method on `Receiver` (`register_notification_callback`,
`register_position_callback`, `register_position_jump_callback`) returns a plain
`Callable[[], None]` that removes that registration. The returned unsubscribe is
idempotent - calling it twice, or after the callback was already removed some
other way, is a no-op rather than an error, which matters for teardown paths that
run more than once. Registering the exact same callback a second time collapses
to the existing entry rather than firing it twice.

This matters most for Home Assistant: an integration that registers a callback on
entity setup but never unsubscribes on entity removal will accumulate duplicate
callbacks across every config-entry reload.

Reacting to one specific wire command (e.g. only `VOL` messages) has no public
API - that lives on the private `receiver._api.register_callback(...)` and isn't
part of the supported surface. `register_notification_callback` above is the
supported way to learn "something changed" and then read whichever properties
you care about.

### Now-Playing Metadata (Streaming Models Only)

Models with the embedded streaming module expose now-playing metadata for
streaming sources such as AirPlay, Spotify Connect, Qobuz and TIDAL. Check
`receiver.model.has_streaming_feature()` (or the narrower `receiver.has_position`
for position specifically) before relying on this - the TDAI-2170 and the P
series have no streaming module, so `now_playing`, position and transport
control are all unavailable on those models.

```python
now_playing = receiver.now_playing  # NowPlaying, or None if idle/unsupported
if now_playing is not None:
    print(f"{now_playing.artist} - {now_playing.title} ({now_playing.source})")
    print(now_playing.state)  # PlaybackState.PLAYING, .PAUSED, .STOPPED, ...
```

`NowPlaying` also carries `album`, `art_url`, `duration_ms`, the `controls` the
current source offers right now (see Transport Control below), and `play_modes`.

### Playback Position

```python
print(receiver.position_ms, receiver.position_updated_at, receiver.position_percent)
```

Position is reported through two different callbacks, for two different kinds of
consumer:

```python
# Fires on every raw update - about once a second while playing. For a
# live-counting UI that wants a smooth per-second value.
def on_position(position_ms):
    print(f"Position: {position_ms} ms")

receiver.register_position_callback(on_position)

# Fires only on discontinuities: a seek, a track change, a play/pause, or the
# reported position drifting from where it should be. Does NOT fire for
# ordinary once-a-second progress.
def on_position_jump(position_ms):
    print(f"Position jumped to {position_ms} ms")

unsubscribe = receiver.register_position_jump_callback(on_position_jump)
```

Use `register_position_jump_callback` for anything where each call has a cost -
a Home Assistant entity state write, say. The raw `register_position_callback`
firing once a second would mean roughly 86,400 state writes per player per day;
the jump callback only fires when something actually changed.

### Transport Control

```python
if receiver.can_pause:
    await receiver.async_pause()

if receiver.can_next:
    await receiver.async_next()

if receiver.can_seek:
    await receiver.async_seek(30_000)  # milliseconds
```

**Capabilities are per-source and change at runtime.** The device advertises what
the *current* source supports, not a fixed list for the model: AirPlay offers only
`can_pause` / `can_next` / `can_previous`; Spotify Connect adds `can_seek` and five
play modes; a stopped device advertises nothing, so every `can_*` property reads
`False`. Always check the relevant `can_*` property (or `available_play_modes` /
`available_repeat_modes`) before calling - calling something the current source
doesn't offer raises `LyngdorfUnsupportedError` (from `lyngdorf.exceptions`)
rather than returning `False`, because the device accepts unsupported commands
silently (an unrecognised play mode still returns HTTP 200 and is stored), so a
return value could never tell a caller whether anything actually happened.

> **Warning:** `async_pause()` is source-dependent, and on some sources it is
> destructive. On a source the device streams itself (Spotify Connect) it
> toggles: pause, then resume. On AirPlay and other controller-driven sources it
> instead **ends the session** - the device cannot restart it, and there is no
> separate resume command; only the controlling phone or app can start it again.
> Check `receiver.can_pause` and know your source before calling it.

Shuffle and repeat can be set independently - each call carries the other setting
over unchanged rather than leaving it to the device to infer:

```python
from lyngdorf import PlayMode, Repeat

await receiver.async_set_shuffle(True)
await receiver.async_set_repeat(Repeat.ALL)

# Or set both at once:
await receiver.async_set_play_mode(PlayMode(shuffle=True, repeat=Repeat.ALL))
```

`available_play_modes`, `available_repeat_modes` and `can_shuffle` report what the
current source actually allows.

`available_play_modes` is a union of two device-reported lists, not a straight
read of either one - each is a partial view of the same six-value shuffle/repeat
grid. The current source's own `controls.playMode` omits `normal`; the device's
global `settings:/mediaPlayer/playModes` list omits the repeat-all variants.
Taking either list alone leaves a genuinely supported mode unreachable - taking
only the per-source list, for instance, meant `normal` had nowhere to go, so
`async_set_shuffle(False)` raised instead of turning shuffle off whenever repeat
was already off. Verified against a real MP-60.

### Typed States

`PlayMode`, `Repeat`, `Control` and `PlaybackState` are importable directly from
`lyngdorf`:

```python
from lyngdorf import Control, PlaybackState, PlayMode, Repeat
```

- `Repeat` - `OFF` / `ONE` / `ALL`.
- `PlayMode` - a frozen dataclass pairing `shuffle: bool` with `repeat: Repeat`,
  not an enum: the device's six wire values (`normal`, `shuffle`, `repeatOne`, ...)
  are really a 2x3 grid of these two independent axes.
- `Control` - a transport action name (`PAUSE`, `NEXT_TRACK`, `PREVIOUS_TRACK`,
  `SEEK`, ...), as found in `NowPlaying.controls`.
- `PlaybackState` - `PLAYING` / `PAUSED` / `STOPPED` / `TRANSITIONING`, as found
  in `NowPlaying.state`.

### Command Pacing & Coalescing

Every outbound command is routed through a paced, coalescing queue, so a caller
never needs to throttle its own writes. This exists because a real MP-60
(firmware 5.4.2) has a fixed queue-depth cliff, not a throughput limit: a
read-only probe found 10 unpaced commands all got replies, while bursts of 30,
60 and 100 unpaced commands each got exactly 16 replies, with the rest silently
dropped - the device self-heals once traffic backs off. See
[issue #35](https://github.com/fishloa/lyngdorf/issues/35) for the measurement.
Left unhandled, a Home Assistant volume-slider drag (10-30 commands a second)
would overflow that cliff, the device would stop responding, and the keepalive
monitor would then read the silence as a dead connection and reconnect -
surfacing to a user as "Home Assistant keeps dropping my Lyngdorf".

The queue paces writes `COMMAND_PACING_MS` (50ms, see `lyngdorf/const.py`)
apart and coalesces selectively. Absolute setters - volume, Zone B volume, the
trims, lipsync, balance - collapse to only their latest queued value, since
only the final value can ever matter. Relative and sequential commands never
collapse: the volume/trim up-down steppers each mean "one more step", and
digit and cursor/navigation commands carry meaning in their order and count.
One consequence worth knowing deliberately: a rapid burst of volume sets can
result in fewer commands reaching the device than were issued - the
intermediate values were never going to be seen anyway.

## Model-Specific Features

### MP-40
- 3 HDMI inputs
- 12-channel decoding
- 16 balanced audio outputs

### MP-50
- 8 HDMI inputs
- 3 HDMI outputs (including HDBT)
- 11.1 setup + 4 auxiliary channels
- Optional 16-channel AES module support

### MP-60
- 8 HDMI inputs
- 3 HDMI outputs (including HDBT)
- 16-channel decoding
- Optional 16-channel AES module support

### TDAI-3400
- I-prefixed command protocol
- Dual speaker setup switching
- Headphone output controls
- Network connectivity (Ethernet + Wi-Fi)
- Media playback (Spotify, TIDAL, Roon, etc.)
- 3-band equalizer + balance control
- Streaming module connection reuse (keep-alive) confirmed working in the
  field on a real unit by @svwhisper - 20 sequential requests, one steady
  connection, zero reuse failures; see `lyngdorf/streaming.py`'s
  `StreamMagicSession` for details and the still-unexercised chunked-response
  fallback it walks back

## Development

### Setup
```bash
poetry install
```

### Run Tests
```bash
poetry run pytest -v
```

See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) before writing a test that calls
`async_connect()` on a streaming-capable model against a fake host - without a
guaranteed `async_disconnect()`, that combination can hang the test for two
minutes.

### Code Quality
```bash
poetry run black lyngdorf/ tests/      # Format code
poetry run ruff check lyngdorf/ tests/  # Lint
poetry run mypy lyngdorf/               # Type check
```

## Home Assistant Integration

This library is designed for use with Home Assistant. See the [Home Assistant Lyngdorf integration](https://www.home-assistant.io/integrations/lyngdorf/) for setup instructions.

## Protocol Documentation

All models communicate via TCP/IP on port 84 using ASCII commands:
- Commands start with `!` and end with `\r`
- Format: `!COMMAND(parameter)\r` or `!COMMAND?\r` for queries
- Responses start with `!` for status messages

Protocol details available in the `/spec` folder.

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please:
1. Run tests: `poetry run pytest`
2. Format code: `poetry run black .`
3. Check types: `poetry run mypy lyngdorf/`
4. Ensure all CI checks pass

## Support

- **Issues**: [GitHub Issues](https://github.com/fishloa/lyngdorf/issues)
- **Discussions**: [GitHub Discussions](https://github.com/fishloa/lyngdorf/discussions)
