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
- **TDAI-2170** - Older integrated amplifier model
- **TDAI-3400** - Top-of-line networked integrated amplifier

All models support:
- Power control
- Volume/mute control
- Source selection
- RoomPerfect™ room correction
- Voicing selection
- Trim controls (bass, treble, center, height, LFE, surround)
- Zone B control (MP series)

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
    receiver.power_on(True)
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
receiver.power_on(True)   # Turn on
receiver.power_on(False)  # Turn off
print(receiver.power_on)  # Check power state
```

### Volume Control
```python
receiver.volume = -25.0   # Set volume in dB
receiver.volume_up()      # Increase volume
receiver.volume_down()    # Decrease volume
receiver.mute_enabled = True  # Mute
```

### Source Selection
```python
# List available sources
print(receiver.sources)

# Select source by name
receiver.source = "HDMI 1"

# Or by index
receiver.change_source(1)
```

### RoomPerfect™ & Voicing
```python
# List available positions
print(receiver.room_perfect_positions)

# Select position
receiver.room_perfect_position = "Focus 1"
receiver.room_perfect_position = "Global"
receiver.room_perfect_position = "Bypass"

# List available voicings
print(receiver.voicings)

# Select voicing
receiver.voicing = "Neutral"
```

### Trim Controls (MP Series)
```python
# Adjust trim levels (in dB)
receiver.trim_bass(1.5)      # +1.5 dB
receiver.trim_treble(-0.5)   # -0.5 dB
receiver.trim_centre(0.0)    # Reset to 0 dB
receiver.trim_height(2.0)
receiver.trim_lfe(-1.0)
receiver.trim_surround(0.5)

# Or use increment/decrement
receiver.trim_bass_up()
receiver.trim_bass_down()
```

### Zone B Control (MP Series)
```python
# Zone B power
receiver.zone_b_power_on(True)

# Zone B volume
receiver.zone_b_volume = -30.0
receiver.zone_b_volume_up()
receiver.zone_b_volume_down()

# Zone B source
receiver.change_zone_b_source(2)
```

### Callbacks & Events
```python
# Register for volume changes
def on_volume_change(param1, param2):
    print(f"Volume changed: {param1}")

receiver._api.register_callback("VOL", on_volume_change)

# Register for any change notification
def on_any_change():
    print("Receiver state changed")

receiver._api.register_notification_callback(on_any_change)
```

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

## Development

### Setup
```bash
poetry install
```

### Run Tests
```bash
poetry run pytest -v
```

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
