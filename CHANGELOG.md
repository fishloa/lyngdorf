# Changelog

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
