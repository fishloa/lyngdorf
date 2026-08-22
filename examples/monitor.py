#!/usr/bin/env python3
"""Live monitor — connects to a Lyngdorf device and prints every state
change to the terminal. Useful for validating callbacks and data against
real hardware.

Usage:
    python examples/monitor.py <host>
    python examples/monitor.py <host> --model tdai-1120
    python examples/monitor.py <host> --debug

Runs until Ctrl+C. All state is printed on connect (after the setup
burst settles), then every callback fires a line. Pass --debug to see
raw protocol traffic.
"""

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime

from lyngdorf import (
    NowPlaying,
    Trim,
    create_receiver,
)
from lyngdorf.discovery import _lookup_model


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def print_state(label: str, value: object) -> None:
    print(f"[{ts()}] {label:.<40s} {value}")


def dump_all_state(r: object) -> None:
    """Print every known property of the receiver."""
    print(f"\n{'=' * 60}")
    print(f" Connected to: {r.name}  (model: {r.model.config.model_name})")  # type: ignore[union-attr]
    print(f"{'=' * 60}")
    print_state("power", r.power_on)  # type: ignore[union-attr]
    print_state("volume", r.volume.value)  # type: ignore[union-attr]
    print_state("mute", r.muted)  # type: ignore[union-attr]
    print_state("source", r.source)  # type: ignore[union-attr]
    print_state("available_sources", r.sources)  # type: ignore[union-attr]
    print_state("streaming_source", r.streaming_source)  # type: ignore[union-attr]
    print_state("audio_input", r.audio_input)  # type: ignore[union-attr]
    print_state("video_input", r.video_input)  # type: ignore[union-attr]
    print_state("audio_information", r.audio_information)  # type: ignore[union-attr]
    print_state("video_information", r.video_information)  # type: ignore[union-attr]
    print_state("sound_mode", r.sound_mode)  # type: ignore[union-attr]
    print_state("available_sound_modes", r.sound_modes)  # type: ignore[union-attr]
    print_state("room_perfect_position", r.room_perfect_position)  # type: ignore[union-attr]
    print_state("available_rp_positions", r.room_perfect_positions)  # type: ignore[union-attr]
    print_state("voicing", r.voicing)  # type: ignore[union-attr]
    print_state("available_voicings", r.voicings)  # type: ignore[union-attr]
    lip = r.lipsync  # type: ignore[union-attr]
    print_state("lipsync", lip.value if lip else None)  # type: ignore[union-attr]
    trims = r.trims  # type: ignore[union-attr]
    for trim, label in [
        (Trim.BASS, "trim_bass"),
        (Trim.TREBLE, "trim_treble"),
        (Trim.CENTER, "trim_centre"),
        (Trim.HEIGHT, "trim_height"),
        (Trim.LFE, "trim_lfe"),
        (Trim.SURROUND, "trim_surround"),
    ]:
        if trim in trims:
            print_state(label, trims[trim].value)

    if r.zone_b is not None:  # type: ignore[union-attr]
        zb = r.zone_b  # type: ignore[union-attr]
        print_state("zone_b_power", zb.power_on)
        print_state("zone_b_volume", zb.volume.value)
        print_state("zone_b_mute", zb.muted)
        print_state("zone_b_source", zb.source)
        print_state("zone_b_available_sources", zb.sources)
        print_state("zone_b_streaming_source", zb.streaming_source)

    print_state("max_volume", r.max_volume)  # type: ignore[union-attr]

    player = r.player  # type: ignore[union-attr]
    if player is not None:
        np = player.now_playing
        if np:
            print_now_playing(np)
        else:
            print_state("now_playing", None)
        print_state("play_mode", player.play_mode)
        print_state("available_play_modes", sorted(str(m) for m in player.play_modes))
        print_state("transport", transport_summary(player))
        print_state("position_ms", player.position_ms)
        print_state("position_percent", player.position_percent)

    rem = r.remote  # type: ignore[union-attr]
    print_state("has_remote_keys", rem is not None)
    if rem is not None:
        print_state("available_remote_keys", sorted(str(k) for k in rem.keys))

    print(f"{'=' * 60}\n")
    print("Monitoring for changes... (Ctrl+C to stop)\n")


def transport_summary(p: object) -> str:
    """The device's currently advertised transport capabilities."""
    return (
        f"pause={p.can_pause} next={p.can_next} "  # type: ignore[union-attr]
        f"prev={p.can_previous} seek={p.can_seek}"  # type: ignore[union-attr]
    )


def print_now_playing(np: NowPlaying) -> None:
    dur = f" [{np.duration_ms // 1000}s]" if np.duration_ms else ""
    art = f"  art={np.art_url}" if np.art_url else ""
    print(
        f"[{ts()}] NOW PLAYING [{np.state}] "
        f"{np.artist or '?'} — {np.title or '?'} "
        f"({np.album or '?'}){dur}"
        f"  via {np.source or '?'}{art}"
    )


class Monitor:
    """Wraps a receiver and prints every state change."""

    def __init__(self, receiver: object) -> None:
        self.r = receiver
        self._prev: dict[str, object] = {}

    def _check(self, label: str, current: object) -> None:
        if self._prev.get(label) != current:
            self._prev[label] = current
            print_state(label, current)

    def on_notification(self) -> None:
        self._check("power", self.r.power_on)  # type: ignore[union-attr]
        self._check("volume", self.r.volume.value)  # type: ignore[union-attr]
        self._check("mute", self.r.muted)  # type: ignore[union-attr]
        self._check("source", self.r.source)  # type: ignore[union-attr]
        self._check("streaming_source", self.r.streaming_source)  # type: ignore[union-attr]
        self._check("audio_input", self.r.audio_input)  # type: ignore[union-attr]
        self._check("video_input", self.r.video_input)  # type: ignore[union-attr]
        self._check("audio_information", self.r.audio_information)  # type: ignore[union-attr]
        self._check("video_information", self.r.video_information)  # type: ignore[union-attr]
        self._check("sound_mode", self.r.sound_mode)  # type: ignore[union-attr]
        self._check("room_perfect_position", self.r.room_perfect_position)  # type: ignore[union-attr]
        self._check("voicing", self.r.voicing)  # type: ignore[union-attr]
        lip = self.r.lipsync  # type: ignore[union-attr]
        self._check("lipsync", lip.value if lip else None)  # type: ignore[union-attr]

        trims = self.r.trims  # type: ignore[union-attr]
        for trim, label in [
            (Trim.BASS, "trim_bass"),
            (Trim.TREBLE, "trim_treble"),
            (Trim.CENTER, "trim_centre"),
            (Trim.HEIGHT, "trim_height"),
            (Trim.LFE, "trim_lfe"),
            (Trim.SURROUND, "trim_surround"),
        ]:
            if trim in trims:
                self._check(label, trims[trim].value)

        if self.r.zone_b is not None:  # type: ignore[union-attr]
            zb = self.r.zone_b  # type: ignore[union-attr]
            self._check("zone_b_power", zb.power_on)
            self._check("zone_b_volume", zb.volume.value)
            self._check("zone_b_mute", zb.muted)
            self._check("zone_b_source", zb.source)
            self._check("zone_b_streaming_source", zb.streaming_source)

        if self.r.player is not None:  # type: ignore[union-attr]
            self._check("play_mode", self.r.player.play_mode)  # type: ignore[union-attr]
            self._check("transport", transport_summary(self.r.player))  # type: ignore[union-attr]
            self._check(
                "available_play_modes",
                sorted(str(m) for m in self.r.player.play_modes),  # type: ignore[union-attr]
            )

    def on_now_playing(self, np: NowPlaying | None) -> None:
        if np:
            print_now_playing(np)
        else:
            print_state("now_playing", None)


async def run(host: str, model_name: str | None, settle_time: float) -> None:
    if model_name:
        model = _lookup_model(model_name)
        if not model:
            print(f"Unknown model: {model_name}", file=sys.stderr)
            sys.exit(1)
    else:
        model = None

    print(f"[{ts()}] Connecting to {host}...")

    receiver = await create_receiver(host, model)
    monitor = Monitor(receiver)
    receiver.on_change(monitor.on_notification)  # type: ignore[union-attr]
    if receiver.player is not None:  # type: ignore[union-attr]
        receiver._api._poll.register_now_playing_callback(monitor.on_now_playing)  # type: ignore[union-attr]

    await receiver.connect()  # type: ignore[union-attr]

    await asyncio.sleep(settle_time)
    dump_all_state(receiver)
    monitor.on_notification()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()

    print(f"\n[{ts()}] Disconnecting...")
    await receiver.disconnect()  # type: ignore[union-attr]
    print(f"[{ts()}] Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live-monitor a Lyngdorf device, printing every state change."
    )
    parser.add_argument("host", help="IP address or hostname of the device")
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (e.g. mp-60, tdai-1120). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (shows raw protocol traffic)",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=3.0,
        help="Seconds to wait after connect before dumping state (default: 3)",
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run(args.host, args.model, args.settle))


if __name__ == "__main__":
    main()
