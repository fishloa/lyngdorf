# Changelog

## 2.2.0 (unreleased)

Mostly a hardware-truth release: a P200 owner measured a real device
against the vendor manual and the manual lost repeatedly. See
[docs/p-series.md](docs/p-series.md) for the probe results, which are
now the authoritative record for that family.

### Breaking

- The **whole P series now reports streaming** (`has_streaming=True`,
  `player is not None`). Previously all three models were configured as
  having no streaming module. A consumer that treats `player is None` as
  "this is a P-series processor" will change behaviour. The P200 is
  measured; the P100 and P300 rest on the vendor manual, which marks
  every other P100 restriction explicitly and leaves `11 Internal
  Player` unmarked (#60).
- **P200 `audio_inputs` is now the MP-60 table**, not the P manual's.
  The device reports `24` for Audio Return Channel where the manual says
  `21`, and reports `37`/`41`/`42` where the manual's table stops at
  `21`. Index-to-name lookups on a P200 change accordingly. P100 and
  P300 keep the manual's table — it describes physical inputs they have
  and the MP one does not.

### Added

- `VolumeControl.maximum_volume` — the device's live `!MAXVOL` ceiling,
  on the control rather than the receiver, with capability expressed as
  the `VolumeControl` subtype (#54). A user-set safety ceiling that
  *clamps writes*, not the hardware range; `range` is still the
  hardware's capability and its meaning is unchanged. Read-only by the
  device's own constraint — a real P200 ignores `!MAXVOL(300)`.
- A **loud, latched error** when a model configured as streaming cannot
  reach its `:8080` API, or gets a response it cannot parse. Everything
  on that path logged at `DEBUG`, so a wrong `has_streaming` was
  indistinguishable from a device with nothing to show. Reports once per
  outage at `ERROR` naming host and port; recovery logs at `WARNING` and
  re-arms.
- `!STREAMTYPE` / `!ZSTREAMTYPE` mapped and queried at setup for the P
  series.

### Changed

- `lookup_model` strips surrounding whitespace (#58). The input is a
  vendor's UPnP `modelName`, which reaches the library unnormalised — a
  stray space made a fully supported device abort discovery as
  `unsupported_model`. A **brand prefix is still not matched**, and that
  is deliberate: a substring match that guesses wrong yields the wrong
  `ModelConfig`, which connects happily and then misbehaves quietly.
- **P200 Zone B volume floor is `-99.0`**, not `-99.9` — measured
  (`!ZVOL(-999)` reads back `!ZVOL(-990)`). The main zone really does
  reach `-99.9` on the same unit, so this is a genuine per-zone
  difference. Roughly 0.7% of Zone B slider travel for a consumer
  mapping through `range`.

### Deprecated

- `LyngdorfReceiver.max_volume` — use `volume.maximum_volume`, and
  `isinstance(volume, VolumeControl)` for the capability check. Removed
  in 3.0.

### Documentation

- **Firmware provenance disclosed.** Some static lookup tables — stream
  type indices in particular — were recovered by disassembling ARM
  binaries from official firmware packages, because `!STREAMTYPE`
  returns bare integers no manual explains. Packages, versions, binaries
  and addresses in [docs/firmware-provenance.md](docs/firmware-provenance.md);
  per-model tables in [docs/oracle/](docs/oracle/), each tagged
  `firmware-verified`, `spec-verified` or `code-only`.
- `docs/p-series.md` gains a "Hardware measurements" section recording
  volume ranges, `!MAXVOL` semantics, standby behaviour, the queries that
  are *legal but silent* on a P200, and corrections to the manual.
- `!DEFVOL` is documented as deliberately not modelled. It is a
  speaker-safety setting that takes effect at power-on, when nobody is
  at the controls, and a bad write is silent until the device next
  wakes.

### Known gaps

- Volume writes are **silently discarded in standby** on a P200 — no
  error, no state change, indistinguishable from a write that landed
  (#59). Source selection is not affected; `!SRC(n)` powers the zone on.
  Unresolved in this release.

## 2.0.0

Breaking. See [MIGRATION.md](MIGRATION.md) for the complete 1.x → 2.0
table; every renamed or relocated member keeps working in 2.0 as a
`DeprecationWarning` shim, deleted in 2.1.

### Breaking

- Every write is `async def` and must be awaited. All 18 property setters
  are removed with no shim — assignment is now a static error, so a type
  checker finds every call site.
- `volume` and `lipsync` are now control objects, not numbers. They keep
  their names, so this compiles and misbehaves: read `.value`.
- `create_receiver` raises `UnsupportedModelError`, never
  `NotImplementedError`. Applies through the shim.
- Structural capability replaces `has_*_feature()`: check
  `player is not None`, `zone_b is not None`, `remote is not None`,
  `Trim.X in trims`.
- `*_range is None` as a capability flag is gone. Check for the control's
  existence instead.
- Submodule import paths (`lyngdorf.device`, `lyngdorf.api`) are removed.
  Import from `lyngdorf` (the package root).
- Module-level deprecation warnings fire once per import (PEP 562).
- `un_register_notification_callback` removed with no shim.

### Added

- `create_receiver(host, *, session=None)` — the factory with session
  injection and model auto-detection.
- `discover_model(host)` / `discover_ssdp_location(host)` /
  `fetch_device_serial(location, *, session=None)` — the discovery split.
- `UnsupportedModelError` — typed exception for unknown devices.
- `NowPlayingPoll` in `streaming/poll.py` — the extracted poll loop.
- `NumericControl.set()`, `SteppableControl.up()`/`.down()` — the control
  object write surface.
- `Player` / `Remote` / `ZoneB` components — per-capability objects.
- `py.typed` — inline types shipped in the wheel.

### Changed

- All :8080 streaming HTTP driven by aiohttp, not http.client.
- `LyngdorfApi` delegates streaming to `NowPlayingPoll`.
- Session ownership decided in `LyngdorfReceiver.__init__` exactly once.

### Removed

- `async_create_receiver`, `async_find_receiver_model`,
  `async_get_device_serial` — renamed with shims.
- `Receiver` — renamed to `LyngdorfReceiver` with shim.
- `async_probe_device_capabilities` — renamed to `probe_capabilities`
  with shim.
- Ten model-specific receiver subclasses (`MP60Receiver`, etc.).
- `attrs` dependency.
- All `has_*_feature()` methods — shimmed, deleted in 2.1.
- All property setters — removed with no shim, static error at call site.

### Fixed

- The now-playing poll's HTTP is genuinely cancellable (aiohttp vs
  http.client-in-executor, #45).
- Connection-per-write for transport controls with `Connection: close`
  preserves the device's limited slot count (#29, #31).
- The single retained `run_in_executor` (UDP M-SEARCH) is bounded, D8.
