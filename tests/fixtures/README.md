# Real device captures

Verbatim responses captured from a real Lyngdorf MP-60 (system 5.3.0) on
2026-08-16, used as test fixtures so the parser is exercised against what
the hardware actually sends rather than hand-written approximations.

Captured over the streaming module's HTTP API on `:8080` while playing
AirPlay from an iPhone.

| File | Request |
|------|---------|
| `now_playing_airplay.json` | `GET /api/getData?path=player:player/data&roles=value` |
| `now_playing_idle.json` | same, with nothing playing |
| `play_time.json` | `GET /api/getData?path=player:player/data/playTime&roles=value` |
| `poll_queue_position.json` | `GET /api/event/pollQueue?queueId=<id>&timeout=10`, subscribed to `player:player/data/playTime` |
| `play_modes.json` | `GET /api/getRows?path=settings:/mediaPlayer/playModes&roles=value` |

The `poll_queue_position.json` capture is the one that resolved #33: the
queue pushes position changes roughly once a second with the value
inline, so no follow-up `getData` is needed. Four consecutive polls
returned 28650 / 29650 / 30650 / 31650 ms, each returning immediately
rather than waiting out the 10s long-poll timeout.

`play_modes.json` is the device's global play-mode enum, used as the
fallback when a source's own now-playing payload omits `controls.playMode`
entirely (see #32 fix wave). Row shape confirmed against a real MP-60.
