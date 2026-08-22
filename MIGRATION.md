# Migration — lyngdorf 1.x → 2.0

## How to read this

Every changed member answers four questions:

- **Where is my equivalent?** Keyed on the OLD name in column 1 — that is what
  a migrator greps for and scans down.
- **Is it shimmed and until when?** The third column says which shim class
  applies and when it is deleted (2.1).
- **What breaks silently?** Each entry flags `**SILENT**` or `**HAZARD**` when
  the name compiles but does something different.
- **What is the runnable done-when?** A check you can run and observe the
  old name no longer exists.

Examples describe **shapes**, not actual consumer files — consumer code moves
underneath us, and pinned examples rot.

## The third column's vocabulary

| Term | Meaning |
|---|---|
| `kept` | Keeps its name and type; nothing changes for the caller. |
| `shim` | Renamed; the old name emits `DeprecationWarning` and delegates. Deleted in 2.1. |
| `shim (now async)` | Renamed AND the action is now async; the old sync-bodied shim returns the coroutine. Deleted in 2.1. |
| `await` | The ACTION keeps its name but becomes `async def`; the caller must now `await`. |
| `bump PR` | Attribute-based access changes shape (new property, new type); the integration's entity-description dataclass changes. |
| `removed` | GONE: no shim, no fallback. Static error at the call site. |

## Module level

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `async_create_receiver(host)` | `create_receiver(host, *, session=...)` | `shim` — resolves through `lyngdorf.__getattr__`, warns once at the importing module's import (PEP 562). The new raise-not-None contract applies through it: `**SILENT**` for callers catching `NotImplementedError`. |
| `async_find_receiver_model(host)` | `discover_model(host)` | `shim` — resolve-and-warn. Plain rename. |
| `async_get_device_serial(host)` | `discover_ssdp_location(host)` then `fetch_device_serial(location)` | `shim` — composes the split, reproducing 1.x exactly. The one shim that is not an alias. |
| `Receiver` | `LyngdorfReceiver` | `shim` — resolve-and-warn. |
| `async_probe_device_capabilities` | `probe_capabilities` | `shim` — resolve-and-warn. Accessed as `diagnostics.async_probe_device_capabilities`. |
| `from lyngdorf.device import …` | import from `lyngdorf` (the package root IS the entire public API) | `removed` — submodule path cannot be shimmed by `__getattr__`. Includes `monkeypatch.setattr("lyngdorf.device.…")` in a test suite. |
| `from lyngdorf.api import …` | import `LyngdorfApi` from `lyngdorf.rio` or use the public API | `removed` — same submodule-path limitation. |

## Module-level deprecation warnings fire ONCE, at import

The class shims warn per call; the module shims resolve through PEP 562's
`__getattr__`, so `from lyngdorf import async_create_receiver` at the top
of a module warns once when that module is imported. A migrator running
with `-W error::DeprecationWarning` finds every site; one grepping logs
for repeated warnings will under-count. The reliable check is escalating
`DeprecationWarning` to error (the third done-when below).

## `create_receiver`'s exception change — SILENT

The shimmed `async_create_receiver(host)` still resolves and still warns
about the *rename*, but it raises `UnsupportedModelError` (never
`NotImplementedError`, and never returns `None`). A caller catching
`NotImplementedError` around it stops catching anything, silently, at a
name that still resolves. The fix is `except UnsupportedModelError:`.
No dual-inheritance softening was used because a library should not raise
a builtin that means "abstract method" (§2.1).

## Lifecycle & callbacks

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `async_connect` | `connect` | `shim (now async)` — was already async in 1.x; plain rename. |
| `async_disconnect` | `disconnect` | `shim (now async)` — plain rename. |
| `register_notification_callback` | `on_change` — returns unsubscribe callable. | `shim`. |
| `register_position_jump_callback` | `player.on_position_jump` | `shim` — no-op unsubscribe without a player. |
| `un_register_notification_callback` | Unsubscribe returned by `on_change` — call the callable. | `removed` — the unsubscribe callable is safer (idempotent, removes exactly the registered callback). |

## Power / volume / mute

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `power_on` | `receiver.power_on` | `kept` |
| `volume` | `receiver.volume.value` | `**SILENT**` — same name, NEW TYPE. Was `float`; is now a `NumericControl` object. Read its `.value`. |
| `set_volume` | `await volume.set(x)` | `shim (now async)` — `**HAZARD**`: return type change. |
| `volume_up` / `volume_down` | `volume.up()` / `volume.down()` | `shim` — returns the coroutine; await it. |
| `volume_range` | `volume.range` | `shim` — `**HAZARD**`: 1.x used this as a capability flag (`is None` = no volume); 2.0's structural capability means the control itself is absent, not its range. |
| `mute_enabled` | `muted` | `shim` — read-only property. |
| `max_volume` | `max_volume` | `kept` |

## Selections

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `source` / `sound_mode` / `room_perfect_position` / `voicing` | same name | `kept` — value unchanged. |
| `set_source` / `set_sound_mode` / `set_room_perfect_position` / `set_voicing` | `set_source(name)` / `set_sound_mode(name)` / `set_room_perfect_position(name)` / `set_voicing(name)` | `await` — same name, now async. Return value changes from `None` to `Coroutine`. |
| `available_sources` | `sources` | `shim` |
| `available_sound_modes` | `sound_modes` | `shim` |
| `available_room_perfect_positions` | `room_perfect_positions` | `shim` |
| `available_voicings` | `voicings` | `shim` |
| `available_audio_inputs` | `audio_inputs` | `shim` |
| `available_video_inputs` | `video_inputs` | `shim` |
| `available_stream_types` | `stream_types` | `shim` |
| `audio_input` / `video_input` / `streaming_source` / `audio_information` / `video_information` | same name | `kept` |

## Trims & lipsync

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `lipsync` | `receiver.lipsync.value` | `**SILENT**` — same name, NEW TYPE. Was `float`; is now a `NumericControl | None`. Read `.value`; check `is not None` for capability. |
| `lipsync = x` (assignment) | `await receiver.lipsync.set(x)` | `removed` |
| `set_lipsync` | `await lipsync.set(ms)` | `shim (now async)`. |
| `lipsync_range` | `lipsync.range` | `shim` — `**HAZARD**`: 1.x used `is None` as a capability flag. |
| `trim_bass` / `trim_treble` / `trim_centre` / `trim_height` / `trim_lfe` / `trim_surround` | `trims[Trim.BASS].value` etc. | `shim` — read-only property. `**HAZARD**`: 1.x used `is None` as capability; 2.0 tests `Trim.X in trims`. |
| `set_trim_bass` / `set_trim_treble` / `set_trim_centre` / `set_trim_height` / `set_trim_lfe` / `set_trim_surround` | `await trims[Trim.X].set(v)` | `shim (now async)` — `**HAZARD**`: return type changes from `None` to `Coroutine`. |
| `trim_bass_range` / `trim_treble_range` / `trim_centre_range` / `trim_height_range` / `trim_lfe_range` / `trim_surround_range` | `trims[Trim.X].range` | `shim` — `**HAZARD**`: `is None` gate changes. |
| `trim_bass_up` / `trim_bass_down` / `trim_treble_up` / `trim_treble_down` / `trim_centre_up` / `trim_centre_down` / `trim_height_up` / `trim_height_down` / `trim_lfe_up` / `trim_lfe_down` / `trim_surround_up` / `trim_surround_down` | `isinstance(trims[Trim.X], SteppableControl) and .up()` / `.down()` | `shim` — warn-and-ignore on non-steppable models, same as 1.x. |

## Zone B

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `zone_b_power_on` | `zone_b.power_on` | `shim` — read-only via component. |
| `zone_b_volume` | `zone_b.volume.value` | `shim` — `**HAZARD**`: return type changes from `float` to `float | None`. |
| `zone_b_volume = x` | `await zone_b.volume.set(x)` | `removed` — the old method works: `set_zone_b_volume(x)` → `shim (now async)`. |
| `set_zone_b_volume` | `await zone_b.volume.set(x)` | `shim (now async)`. |
| `zone_b_volume_up` / `zone_b_volume_down` | `zone_b.volume.up()` / `zone_b.volume.down()` | `shim` — warn-and-ignore when Zone B is absent, same as 1.x. |
| `zone_b_volume_range` | `zone_b.volume.range` | `shim` — `**HAZARD**`: `is None` gate changes. |
| `zone_b_mute_enabled` | `zone_b.muted` | `shim` — read-only. |
| `zone_b_source` / `zone_b_audio_input` / `zone_b_streaming_source` | `zone_b.source` / `zone_b.audio_input` / `zone_b.streaming_source` | `shim` — reads through the component. |
| `zone_b_available_sources` | `zone_b.sources` | `shim`. |

## Informational

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `model` | `receiver.model` (returns `LyngdorfModel`, not `str`) | `kept` — type narrowed. |
| `connected` | `receiver.connected` | `kept` |

## Streaming / player

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `has_position` | `player is not None` | `shim` — `**HAZARD**`: 1.x returns `bool`; structural capability now means the component itself is absent. |
| `has_remote_keys` | `remote is not None` | `shim` — `**HAZARD**`: same structural change. |
| `now_playing` | `player.now_playing` | `shim` — read-only. |
| `position_ms` / `position_updated_at` | `player.position_ms` / `player.position_updated_at` | `shim`. |
| `async_pause` / `async_next` / `async_previous` | `player.pause()` / `player.next_track()` / `player.previous_track()` | `shim (now async)` — raises `LyngdorfUnsupportedError` when applicable. |
| `async_seek` | `player.seek(ms)` | `shim (now async)` — `**HAZARD**`: return type change. |
| `async_set_play_mode` | `player.set_play_mode(mode)` | `shim (now async)`. |
| `async_set_shuffle` | `player.set_shuffle(shuffle)` | `shim (now async)`. |
| `async_set_repeat` | `player.set_repeat(repeat)` | `shim (now async)`. |
| `play_mode` / `shuffle` / `repeat` | `player.play_mode` / `player.shuffle` / `player.repeat` | `shim` — `**HAZARD**`: on a non-streaming model these move from the receiver to the player, which is `None`. |
| `can_pause` / `can_next` / `can_previous` / `can_seek` / `can_shuffle` | `player.can_pause` / etc. | `shim` — read-only. `**HAZARD**`: runtime-varying (source-level) capability stays the same; structural (model-level) capability is `player is not None`. |
| `available_play_modes` | `player.play_modes` | `shim`. |
| `available_repeat_modes` | `player.repeat_modes` | `shim`. |

## Remote

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `available_remote_keys` | `remote.keys` | `shim` — type narrowed to `RemoteKey` set. |
| `send_remote_commands` | `remote.send(cmds, num_repeats=N)` | `shim (now async)` — `**HAZARD**`: return type change. |

## Types

| 1.x | 2.0 | In 2.0 |
|---|---|---|
| `lyngdorf-select` | `SelectDescription` (frozen dataclass with key, options_fn, current_fn, select_fn) | `bump PR` — the lambda body is unchanged (returning the call, now a coroutine, needs zero lambda edits). |
| `lyngdorf-remote` | `Remote` component | `bump PR` — `remote.press(key)`, `remote.send(commands)`, `remote.keys`. |

## Behavioural changes beyond renames

1. **Every write is `async def` and must be awaited.** All 18 property setters
   are removed with no shim — assignment is a static `[misc]` error that a
   type checker finds at every call site.

2. **`volume` and `lipsync` are now control objects, not numbers.** They
   keep their names, so this compiles and misbehaves. Read `.value`.

3. **`create_receiver` raises `UnsupportedModelError`, never
   `NotImplementedError`.** Applies through the shim — `except
   NotImplementedError` stops catching anything, silently.

4. **Structural capability replaces `has_*_feature()`.** Check
   `player is not None`, `zone_b is not None`, `remote is not None`,
   `Trim.X in trims` — no boolean proxy methods.

5. **`*_range is None` as a capability flag is gone.** A control that
   exists always has a range. Check for the control's existence instead.

6. **Submodule import paths are removed.** `from lyngdorf.device import …`
   and `from lyngdorf.api import …` break with no deprecation window.
   Import from `lyngdorf` (the package root).

7. **Module-level deprecation warnings fire once, at import.** PEP 562's
   mechanism means `from lyngdorf import async_create_receiver` warns
   exactly once per importing module. The per-class shims warn per call.

8. **The `un_register_notification_callback` method is removed with no
   shim.** Use the unsubscribe callable returned by `on_change`.

## Migration guidance

### Payload: what your integration's entity-description dataclasses look like

```python
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from lyngdorf import LyngdorfReceiver, NumericControl, SteppableControl, Trim

@dataclass(frozen=True)
class SelectDescription:
    key: str
    options_fn: Callable[[LyngdorfReceiver], list[str]]
    current_fn: Callable[[LyngdorfReceiver], str | None]
    select_fn: Callable[[LyngdorfReceiver, str], Awaitable[None]]

@dataclass(frozen=True)
class SwitchDescription:
    key: str
    is_on_fn: Callable[[LyngdorfReceiver], bool | None]
    set_fn: Callable[[LyngdorfReceiver, bool], Awaitable[None]]

@dataclass(frozen=True)
class NumberDescription:
    key: str
    control_fn: Callable[[LyngdorfReceiver], NumericControl | None]
```

### Non-deferrable: what the old names must be gone by

2.1 deletes every shim. Run with `-W error::DeprecationWarning` to find
every legacy call site.

### Measured hazards per category (what breaks silently)

| Hazard | Count | Fix |
|---|---|---|
| Same name, new type (volume, lipsync) | 2 | Read `.value` |
| `*_range is None` capability flag | 8 | Check control existence |
| Return type change (bool → None on non-streaming) | 1 | Use `player is not None` |
| `NotImplementedError` catch around `async_create_receiver` | 1 | Catch `UnsupportedModelError` |

### Runnable done-whens

1. **`-W error::DeprecationWarning`** — your integration imports cleanly
   with deprecation warnings escalated to errors. Every shimmed legacy
   name is gone.

2. **Type-check your entity descriptions** — `mypy --strict` against your
   `SelectDescription` / `SwitchDescription` / `NumberDescription` lambdas
   reports zero errors. If you changed a lambda body, it's wrong.

3. **The `is None` checks return** — every former `has_*_feature()` call
   is replaced with structural checks (`player is not None` etc.), and
   every former `*_range is None` capability check is replaced with
   control-existence checks (`Trim.X in trims`).

---

## The measured minimum: what the bump PR actually costs

Measured against a real Home Assistant integration migrating to this
release — the minimum change that keeps its CI green with 2.0.0 installed
and **everything else untouched**, which is the state `dev` sits in
between the version bump and each later platform PR.

```
15 files changed, +36 / −31        91 passed, 0 failed
```

Nine production files, and **seven of those changes are a single import
line**. The entire non-import production delta is four edits:

- `register_notification_callback` now returns an unsubscribe; keep it and
  call it, instead of `un_register_notification_callback`
- `receiver.volume` → `receiver.volume.value` (two sites)
- `receiver.lipsync` → `receiver.lipsync.value if receiver.lipsync else None`

Everything else **defers**. `now_playing`, `position_ms`, `shuffle`,
`repeat`, `can_shuffle`, `available_repeat_modes`,
`register_position_jump_callback`, every `zone_b_*`, every `trim_*`,
`set_volume`, `send_remote_commands`, the steppers — all still work
through shims, untouched, green. You migrate them when you touch that
platform, not to get onto 2.0.

Two consequences worth stating, both measured rather than assumed:

- **Shim `DeprecationWarning`s do not fail Home Assistant CI.** Core
  escalates only `sqlalchemy.exc.SAWarning` and one `usefixtures`
  `UserWarning`; there is no blanket `DeprecationWarning` filter. That run
  emitted 476 shim warnings and stayed green.
- **The intermediate state is shippable.** `dev` can carry 2.0.0 with
  every platform still on shims, tests green, users unaffected. That is
  the claim the whole deprecation layer rests on, and it is now a
  measurement rather than an argument.

---

## Migrating your test suite — the part no inventory predicts

Every list in this document is derived from *member names*. Your test
suite breaks in ways member names cannot describe, and the numbers below
are measured from a real integration migrating against this release, not
estimated.

Budget for this. It was the largest single chunk of that migration, and
the bulk of it is unavoidable rather than deferrable.

### A deliberate removal still costs adaptation work

`un_register_notification_callback` is listed as **removed**, which reads
like a one-line deletion — and in production it genuinely is two lines.
But a broken *teardown* multiplies: leaving it unadapted produced **472
test failures**, one line amplified across every test that tears down an
entity.

So the cost is not the edit, it is the blast radius when you miss it.

The lesson generalises: a removal's row in a table says nothing about the
size of its blast radius. Grep for each removed name across your *tests*
as well as your production code before estimating, because a name used by
a shared fixture or helper appears once and detonates everywhere.

### Relocated members move as a group, when you touch that platform

`now_playing`, `position_ms`, `shuffle`, `repeat`, `can_shuffle`,
`available_repeat_modes` and `register_position_jump_callback` are all
shimmed, so they keep working indefinitely — and they are **not** part of
the bump PR. Nothing above forces you to touch them.

When you *do* migrate the platform that uses them, they move to
`player.*` **at once**, because they relocated to the same component. So
the deferral is real but lumpy: you defer the whole cluster or none of
it. Plan each platform PR around the component boundary rather than
around individual names — and note that this is a choice about how to
stage your own work, not a cost 2.0 imposes on you.

### Mock-introspecting test helpers break SILENTLY

This is the one that costs an afternoon.

A helper that reads the library's *call history* rather than calling the
library has no import to fail and no attribute to raise:

```python
# Reads how the entity registered. Renaming the registration method does
# not break this line — it just stops matching, forever.
callback = receiver.register_notification_callback.call_args_list[0][0][0]
callback()
```

Entities now register through `on_change`, so `call_args_list` on the old
name is empty, the helper fires nothing, and your state assertions fail
somewhere else entirely with no indication of why. Nothing in this
document's tables can warn you: the name in your helper is a *mock
attribute*, not a library member, so it is invisible to any inventory.

Audit for helpers that touch `.call_args`, `.call_args_list`,
`.mock_calls` or `.assert_called*` against a renamed member, and fix them
first — before you try to interpret any other failure, because a broken
helper makes every downstream failure misleading.

### The same trap, in reverse: assertions naming old methods

`assert_called_once_with` against `set_volume` or `send_remote_commands`
keeps passing type checks and keeps failing at runtime for a reason that
looks like a behaviour change. It is not — the method was renamed and the
mock happily recorded nothing.
