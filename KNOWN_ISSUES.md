# Known issues

Problems that are understood but not fixed. Each entry says what happens,
why, how to avoid it, and what fixing it would involve.

## Most writes are silently discarded in standby

Measured on a P200 (firmware p20.5.4.1) and, for main-zone volume, on an
MP-60 (5.4.2). The device answers every query while in standby but
discards most writes — no error, no reply, no state change — so the
library cannot tell a discarded write from one that landed.

Discarded in full standby on the P200:

| | |
|---|---|
| `!VOL(x)`, `!ZVOL(x)`, `!ZVOL±(n)` | volume, both zones |
| `!AUDMODE(x)` | audio processing mode |
| `!RPFOC(x)`, `!RPVOI(x)` | RoomPerfect position and voicing |
| `!MUTEOFF`, `!ZMUTEOFF` | see the caveat below |
| `!ZSRC(n)` | Zone B source, in full standby |

Two exceptions, and they are the interesting part:

- **`!SRC(n)` powers the main zone on** rather than being discarded.
  `!ZSRC(n)` does the same for Zone B *when the main zone is already on* —
  but is discarded when the whole unit is in standby.
- **`!LIPSYNC(x)` is applied.**

So this is **not volume-specific**. `!SRC` is the exception; discarding
is the rule.

**Mute is not observable in standby.** `!MUTE?` answers `!MUTEON`
whenever the unit is in standby regardless of what was sent — it reads
`!MUTEON` before and after a power cycle with no mute command in
between, and `!MUTEOFF` while on. So the mute setters cannot be
confirmed either way from standby, and an earlier record here claiming
`!MUTEON` was *applied* was a misreading of that.

Avoid it by checking `receiver.power_on` before writing. Raising a
distinct exception instead was specified in detail and **dropped** — see
[#59](https://github.com/fishloa/lyngdorf/issues/59) for why, in short:
no other Home Assistant media player raises on device-off, and the
device self-heals anyway, re-reporting both zone volumes unprompted on
power-on before `!POWER(1)` arrives.

Unmeasured: the TDAI family entirely, and everything but main-zone
volume on the MP family.

## Resolved

### One bounded, discovery-time-only UDP executor hop (resolved in 2.1)

`discover_ssdp_location` ran a blocking `socket.recvfrom()` inside
`loop.run_in_executor`. It was bounded twice and only ran during
discovery, and spec D8 retained it deliberately, citing evidence that 17
of the 86 libraries behind platinum-tier Home Assistant integrations use
an executor.

2.1 removed it anyway (`loop.create_datagram_endpoint`, deliberately not
connected to the remote so a reply from any source port is accepted).
The platinum async-dependency rule admits no exceptions in its own text,
so the evidence D8 rested on argued against the rule rather than
satisfying it. **There is now no `run_in_executor` anywhere in the
library**, and D8 is reversed rather than merely unmet.


### The now-playing poll's HTTP calls are not genuinely cancellable (resolved in 2.0)

The streaming module's HTTP was `http.client` inside `run_in_executor`:
`asyncio.wait_for` cancels the *await*, not the work, so a request already
running in its executor thread ran to completion no matter what — and a
test that failed mid-poll could hang for up to two minutes on teardown.
Issue #45 could only bound the damage (`tests/conftest.py`'s
`_guarantee_disconnect` teardown fixture); it could not remove it.

The 2.0 port of `lyngdorf/streaming/` to aiohttp made every streaming HTTP
call genuinely cancellable — cancelling the poll task now aborts an
in-flight request instead of orphaning it in a thread — which retires this
entry and the two-minute test-hang caveat that came with it. The teardown
fixture remains as hygiene (a failing test still gets its receiver
disconnected), with a short timeout kept purely as a regression guard.
