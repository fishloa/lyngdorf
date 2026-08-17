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
| `now_playing_spotify_connect.json` | same, with Spotify Connect playing |
| `play_time.json` | `GET /api/getData?path=player:player/data/playTime&roles=value` |
| `poll_queue_position.json` | `GET /api/event/pollQueue?queueId=<id>&timeout=10`, subscribed to `player:player/data/playTime` |
| `play_modes_roles_title_value.json` | `GET /api/getRows?path=settings:/mediaPlayer/playModes&roles=title,value` |
| `play_modes_roles_value.json` | `GET /api/getRows?path=settings:/mediaPlayer/playModes&roles=value` |
| `play_mode_current.json` | `GET /api/getData?path=settings:/mediaPlayer/playMode&roles=value` |
| `now_playing_spotify_smart_shuffle.json` | `GET /api/getData?path=player:player/data&roles=value`, with Spotify playing in "smart shuffle" |

The `poll_queue_position.json` capture is the one that resolved #33: the
queue pushes position changes roughly once a second with the value
inline, so no follow-up `getData` is needed. Four consecutive polls
returned 28650 / 29650 / 30650 / 31650 ms, each returning immediately
rather than waiting out the 10s long-poll timeout.

`play_modes_roles_title_value.json` and `play_modes_roles_value.json` are
both the device's global play-mode enum, used as the fallback when a
source's own now-playing payload omits `controls.playMode` entirely (see
#32 fix wave). The two captures differ only in which `roles` were
requested, which changes the row shape: `roles=title,value` gives `[title,
value]` rows (`play_modes_roles_title_value.json`), while `roles=value` -
what `async_fetch_play_modes` actually sends - gives single-element
`[value]` rows (`play_modes_roles_value.json`). Both are real device
responses, not hand-written approximations; keeping both as fixtures, and
naming each after the roles that produced it, is what caught a bug where
the parser was tested only against the `[title, value]` shape while the
code requested, and received, the single-element shape - a mismatch a
generically-named `play_modes.json` fixture had been quietly hiding.

`play_mode_current.json` and `now_playing_spotify_smart_shuffle.json` were
captured later, from the same MP-60, while chasing the fix above.
`play_mode_current.json` is a real value for `settings:/mediaPlayer/
playMode` (`async_fetch_play_mode`'s endpoint), captured mid-shuffle rather
than hand-written as `normal`. `now_playing_spotify_smart_shuffle.json` was
captured with Spotify's "smart shuffle" active; the device reports that
simply as the ordinary `shuffle` wire value; there is no distinct wire
value for it.
