# P Series Oracle

Hardware lookup tables for Steinway Lyngdorf P-100, P-200, P-300 processors.

## Stream Types

**Not applicable.** P series processors have no built-in streaming module.

## Audio Inputs (Shared)

**Source: spec-verified** (from SL Processors External Control Manual)

| Index | Name |
|-------|------|
| 0 | None |
| 1 | HDMI |
| 2 | 8 Channel Analog |
| 3 | Spdif 1 (Optical) |
| 4 | Spdif 2 (Optical) |
| 5 | Spdif 3 (Optical) |
| 6 | Spdif 4 (Optical) |
| 7 | Spdif 5 (AES) |
| 8 | Spdif 6 (Coax) |
| 9 | Spdif 7 (Coax) |
| 10 | Spdif 8 (Coax) |
| 11 | Internal Player |
| 12 | USB |
| 13 | Analog 1 (Unbalanced) |
| 14 | Analog 2 (Unbalanced) |
| 15 | Analog 3 (Unbalanced) |
| 16 | Analog 4 (Unbalanced) |
| 17 | Analog 5 (Balanced) |
| 20 | 16-Channel Input (optional for P200/P300) |
| 21 | Audio Return Channel |

### Notes

- Index 2 "8 Channel Analog" is unique to P series (MP series skips this index).
- Indices 13-17 (discrete analog inputs) are P series only.
- Gap at 18-19: unused.

## Video Inputs

### P-100

| Index | Name |
|-------|------|
| 0 | None |
| 1 | HDMI 1 |
| 2 | HDMI 2 |
| 3 | HDMI 3 |
| 4 | HDMI 4 |

### P-200 / P-300

| Index | Name |
|-------|------|
| 0 | None |
| 1 | HDMI 1 |
| 2 | HDMI 2 |
| 3 | HDMI 3 |
| 4 | HDMI 4 |
| 5 | HDMI 5 |
| 6 | HDMI 6 |
| 7 | HDMI 7 |
| 8 | HDMI 8 |
| 9 | Internal |

### Notes

- P-100 has 4 HDMI inputs; P-200/P-300 have 8 plus Internal.

## Video Outputs (P-200 / P-300 only)

**Source: spec-verified** (from SL Processors External Control Manual)

| Index | Name |
|-------|------|
| 0 | None |
| 1 | HDMI Out 1 |
| 2 | HDMI Out 2 |
| 3 | HDMI Out 3 |
| 4 | HDMI Out 4 |
| 5 | HDBT Out |
| 7 | Video Wall |

### Notes

- P-100 has no video output routing.
- Gap at index 6: unused.

## Room Perfect Positions

Dynamic enumeration via RPFOCS? — no fixed table.

## Firmware Details

- **Firmware file**: not downloaded
- **Protocol**: shares MP series protocol family (VERB, PING/PONG, SRCS enumeration)
- **No streaming**: no STREAMTYPE command
