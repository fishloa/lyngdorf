# Firmware provenance

Where this library's static lookup tables come from.

Several tables — stream type indices in particular — are not documented in any
vendor manual. They were recovered by **disassembling ARM binaries extracted
from official firmware update packages** — the GPG-encrypted `.gpg` / `.swu`
files published on the Lyngdorf download center. Tooling: `gpg`/`cpio` to
unpack, `radare2` and `arm-linux-gnueabihf-objdump`/`readelf` to disassemble.

Per-model results, including the tables themselves, are in
[`docs/oracle/`](oracle/). Each entry there is tagged `firmware-verified`,
`spec-verified` or `code-only`, so a consumer can tell measured fact from
transcription from assumption.

## What was analysed

| Model(s) | Firmware package | Version | Binaries | Extracted |
|---|---|---|---|---|
| MP-40, MP-50, MP-60 | `update-streaming_5.4.1.gpg` | 5.4.1 (Apr 2026) | `nsdkd` — ARM 32-bit, `/usr/bin/nsdkd` | Stream types, from `getStreamtypeFromNsdkString` @ `0x15840` |
| TDAI-1120 | `update-tdai1120_2.6.3.swu` | 2.6.3 (Mar 2026) | `stream_p` — ARM 32-bit PIE, `/usr/bin/stream_p`<br>`libtdai.so.0.1.0` — ARM 32-bit, `/usr/lib/` | NSDK strings, from `RemoteBrowserObserverImpl.virtual_28` @ `0xe02c`<br>Display names, from `get_stream_type_name` pointer table @ vaddr `0x449d8`<br>Audio input map, from `get_stream_input` switch table @ vaddr `0x26274` |
| TDAI-3400 | `update-tdai3400-3-6-2.gpg` | 3.6.2 (Apr 2026) | `stream_p` — ARM 32-bit Thumb-2, `/usr/bin/stream_p`<br>`libtdai.so.0.1.0` — ARM 32-bit, `/usr/lib/` | NSDK strings, from stream type mapping function @ `0x1882c`<br>Display names, from `get_stream_type_name` pointer table @ file offset `0x2a388`<br>Audio input map, from `get_stream_input` switch table |
| TDAI-2170 | `ti1_141a.upd` | 1.41a (Jun 2021, final) | none — bare-metal DSP image, no Linux filesystem | **Negative result**: no NSDK, no `stream_p`/`nsdkd`, no streaming services. Release notes SW1.15A–SW1.41A likewise. Confirms the model has no streaming capability |

The MP series share one streaming firmware package across all three models, and
the extracted stream type mapping is identical for each.

## What was not analysed

| Model(s) | Status |
|---|---|
| TDAI-2210 | No firmware examined. Support is derived from its sharing the TDAI-1120/3400 protocol |
| P-100, P-200, P-300 | No firmware downloaded. Tables are spec-verified from the vendor manual, plus hardware probing of a real P200 — see [`p-series.md`](p-series.md) |

## Platform notes

- **MP series, TDAI-1120, TDAI-3400** run StreamUnlimited StreamSDK (NSDK) on
  Linux. The TDAI-1120 is a StreamUnlimited Stream810 board
  (`stream810tdai1120`), shipping a UBIFS rootfs, FIT kernel and U-Boot in an
  SWUpdate CPIO archive.
- **TDAI-2170** is bare-metal DSP firmware, ~3 MB, no operating system. Updated
  by USB stick rather than over the network.

## Why this was necessary

Stream type indices are returned by `!STREAMTYPE` as bare integers with no
accompanying name, and no vendor manual lists what they mean. The mapping also
differs between device families — indices 0–6 agree, then diverge from index 7
because different models insert different extra services. Guessing produces a
library that silently reports the wrong service.

One concrete example: index 7 was `"Unknown"` in this library until the MP
firmware showed it is TIDAL.

## Scope and intent

This is interoperability work: reading published firmware to learn the meaning
of values the device already sends over its own documented control protocol. No
firmware is redistributed here, none is modified, and nothing in this repository
circumvents a protection measure. Only the extracted lookup tables are recorded,
in `docs/oracle/`.
