# Firmware Oracle

Ground-truth hardware lookup tables per model, derived from firmware reverse engineering and vendor specs.

## Verification Levels

- **firmware-verified** -- extracted by disassembling ARM binaries from actual device firmware
- **spec-verified** -- from vendor External Control Manual PDFs
- **code-only** -- from library source code, not independently verified

## Files

| Model | File | Stream Types | Other Tables |
|-------|------|-------------|--------------|
| MP-40 | [mp-40.md](mp-40.md) | firmware-verified | audio/video inputs (code-only) |
| MP-50 | [mp-50.md](mp-50.md) | firmware-verified | audio/video inputs/outputs (code-only) |
| MP-60 | [mp-60.md](mp-60.md) | firmware-verified | audio/video inputs/outputs, RP positions (code-only) |
| TDAI-1120 | [tdai-1120.md](tdai-1120.md) | firmware-verified (3 functions) | RP positions (code-only) |
| TDAI-2170 | [tdai-2170.md](tdai-2170.md) | n/a (no streaming) | sources, voicings (spec-verified); RP positions (code-only) |
| TDAI-3400 | [tdai-3400.md](tdai-3400.md) | firmware-verified (3 functions) | RP positions (code-only) |
| P-100/200/300 | [p-series.md](p-series.md) | n/a (no streaming) | audio/video inputs/outputs (spec-verified) |

## Key Findings

### Stream type index differences between device families (all firmware-verified)

| Index | MP Series | TDAI-3400 | TDAI-1120 |
|-------|-----------|-----------|-----------|
| 0 | None | None | None |
| 1 | vTuner | vTuner | vTuner *(unused)* |
| 2 | Spotify | Spotify | Spotify |
| 3 | AirPlay | AirPlay | Airplay |
| 4 | UPnP | UPnP | UPnP |
| 5 | Storage | USB File | USB File |
| 6 | Roon Ready | Roon Ready | Roon Ready |
| 7 | **TIDAL** | ***(gap)*** | **Bluetooth** |
| 8 | **airable** | **TIDAL** | **Googlecast** |
| 9 | **PureAudio** | **airable** | **TIDAL** |
| 10 | **Qobuz** | **Qobuz** | **airable** |
| 11 | -- | *(default)* | **Qobuz** |
| 12 | -- | -- | *(default)* |

**Key insight**: Indices 0-6 are consistent across all families. Divergence starts at index 7 because different devices have different extra services (Bluetooth, GoogleCast, PureAudio) inserted into the sequence.

**Display name column**: uses firmware `get_stream_type_name()` where available (TDAI), NSDK string names for MP (no libtdai). Note MP uses "Storage" while TDAI uses "USB File" for the same NSDK "Storage" service at index 5.

### Stream type to audio input mapping (firmware-verified, TDAI only)

| Stream Type | TDAI-3400 Audio Input | TDAI-1120 Audio Input |
|-------------|----------------------|----------------------|
| 0 (None) | 255 | 28 |
| 1 (vTuner) | 28 | 14 |
| 2 (Spotify) | 29 | 8 |
| 3 (AirPlay) | 30 | 10 |
| 4 (UPnP) | 32 | 12 |
| 5 (USB File) | 33 | 13 |
| 6 (Roon Ready) | 31 | 9 |
| 7 (Bluetooth/gap) | 34 | 11 |
| 8 (TIDAL/Googlecast) | 35 | 7 |
| 9 (airable/TIDAL) | 36 | 25 |
| 10 (Qobuz/airable) | 37 | 26 |
| 11 (default/Qobuz) | 255 | 27 |

MP series: per-streaming-service audio inputs (35-42) are in the main processor firmware, not the streaming module. Cannot extract from `nsdkd`.

### Firmware formats by device family

| Family | Format | Size | Platform | Binary |
|--------|--------|------|----------|--------|
| MP-40/50/60 | `.gpg` -> ZIP -> .dupdate -> rootfs.tar.xz | ~100MB | StreamSDK (NSDK) | `nsdkd` (ARM Thumb-2) |
| TDAI-1120 | `.swu` (SWUpdate CPIO) -> UBIFS rootfs | ~164MB | Stream810 (NSDK) | `stream_p` (ARM32 PIE) + `libtdai.so` |
| TDAI-3400 | `.gpg` -> ZIP -> .dupdate -> rootfs.tar.xz | ~80MB | StreamSDK (NSDK) | `stream_p` (ARM Thumb-2) + `libtdai.so` |
| TDAI-2170 | `.upd` (bare-metal DSP) | ~3MB | No Linux/NSDK | N/A -- no streaming |

### Library code bugs found

| Model | Index | Code Says | Firmware Says | Severity |
|-------|-------|-----------|---------------|----------|
| TDAI-1120 | 9 | Unknown | TIDAL | **Wrong** |
| TDAI-1120 | 10 | Qobuz | airable | **Wrong** |
| TDAI-1120 | 11 | *(missing)* | Qobuz | **Missing** |
| TDAI-3400 | 7 | Bluetooth | *(not assigned by stream_p)* | **Misleading** -- name correct but unreachable |
| TDAI-3400 | 9 | Unknown | airable | **Wrong** |
| TDAI-2170 | 0-7 | stream types defined | no streaming at all | **Vestigial** |

### Still TODO

- Verify MP-50/MP-60 per-streaming-service audio input indices (Qobuz/PureAudio at 43-44?)
- Extract MP main processor firmware for audio input mapping (35-42+)
