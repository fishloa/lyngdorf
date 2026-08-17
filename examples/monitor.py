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

from lyngdorf.device import (
    Receiver,
    async_create_receiver,
    lookup_receiver_model,
)
from lyngdorf.streaming import NowPlaying


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def print_state(label: str, value: object) -> None:
    print(f"[{ts()}] {label:.<40s} {value}")


def dump_all_state(r: Receiver) -> None:
    """Print every known property of the receiver."""
    print(f"\n{'=' * 60}")
    print(f" Connected to: {r.name}  (model: {r.model.model_name})")
    print(f"{'=' * 60}")
    print_state("power", r.power_on)
    print_state("volume", r.volume)
    print_state("mute", r.mute_enabled)
    print_state("source", r.source)
    print_state("available_sources", r.available_sources)
    print_state("streaming_source", r.streaming_source)
    print_state("audio_input", r.audio_input)
    print_state("video_input", r.video_input)
    print_state("audio_information", r.audio_information)
    print_state("video_information", r.video_information)
    print_state("sound_mode", r.sound_mode)
    print_state("available_sound_modes", r.available_sound_modes)
    print_state("room_perfect_position", r.room_perfect_position)
    print_state("available_rp_positions", r.available_room_perfect_positions)
    print_state("voicing", r.voicing)
    print_state("available_voicings", r.available_voicings)
    print_state("lipsync", r.lipsync)
    print_state("trim_bass", r.trim_bass)
    print_state("trim_treble", r.trim_treble)

    if r.model.has_surround_feature():
        print_state("trim_centre", r.trim_centre)
        print_state("trim_height", r.trim_height)
        print_state("trim_lfe", r.trim_lfe)
        print_state("trim_surround", r.trim_surround)

    if r.model.has_zone_b_feature():
        print_state("zone_b_power", r.zone_b_power_on)
        print_state("zone_b_volume", r.zone_b_volume)
        print_state("zone_b_mute", r.zone_b_mute_enabled)
        print_state("zone_b_source", r.zone_b_source)
        print_state("zone_b_available_sources", r.zone_b_available_sources)
        print_state("zone_b_streaming_source", r.zone_b_streaming_source)

    if r.model.has_streaming_feature():
        np = r.now_playing
        if np:
            print_now_playing(np)
        else:
            print_state("now_playing", None)

    print(f"{'=' * 60}\n")
    print("Monitoring for changes... (Ctrl+C to stop)\n")


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
    """Wraps a Receiver and prints every state change."""

    def __init__(self, receiver: Receiver):
        self.r = receiver
        self._prev: dict[str, object] = {}

    def _check(self, label: str, current: object) -> None:
        if self._prev.get(label) != current:
            self._prev[label] = current
            print_state(label, current)

    def on_notification(self) -> None:
        self._check("power", self.r.power_on)
        self._check("volume", self.r.volume)
        self._check("mute", self.r.mute_enabled)
        self._check("source", self.r.source)
        self._check("streaming_source", self.r.streaming_source)
        self._check("audio_input", self.r.audio_input)
        self._check("video_input", self.r.video_input)
        self._check("audio_information", self.r.audio_information)
        self._check("video_information", self.r.video_information)
        self._check("sound_mode", self.r.sound_mode)
        self._check("room_perfect_position", self.r.room_perfect_position)
        self._check("voicing", self.r.voicing)
        self._check("lipsync", self.r.lipsync)
        self._check("trim_bass", self.r.trim_bass)
        self._check("trim_treble", self.r.trim_treble)

        if self.r.model.has_surround_feature():
            self._check("trim_centre", self.r.trim_centre)
            self._check("trim_height", self.r.trim_height)
            self._check("trim_lfe", self.r.trim_lfe)
            self._check("trim_surround", self.r.trim_surround)

        if self.r.model.has_zone_b_feature():
            self._check("zone_b_power", self.r.zone_b_power_on)
            self._check("zone_b_volume", self.r.zone_b_volume)
            self._check("zone_b_mute", self.r.zone_b_mute_enabled)
            self._check("zone_b_source", self.r.zone_b_source)
            self._check("zone_b_streaming_source", self.r.zone_b_streaming_source)

    def on_now_playing(self, np: NowPlaying | None) -> None:
        if np:
            print_now_playing(np)
        else:
            print_state("now_playing", None)


async def run(host: str, model_name: str | None, settle_time: float) -> None:
    if model_name:
        model = lookup_receiver_model(model_name)
        if not model:
            print(f"Unknown model: {model_name}", file=sys.stderr)
            sys.exit(1)
    else:
        model = None

    print(f"[{ts()}] Connecting to {host}...")

    receiver = await async_create_receiver(host, model)
    if not receiver:
        print(f"[{ts()}] Could not identify device at {host}", file=sys.stderr)
        sys.exit(1)

    monitor = Monitor(receiver)

    receiver.register_notification_callback(monitor.on_notification)
    if receiver.model.has_streaming_feature():
        receiver._api.register_now_playing_callback(monitor.on_now_playing)

    await receiver.async_connect()

    # Let the setup burst settle before dumping initial state
    await asyncio.sleep(settle_time)
    dump_all_state(receiver)

    # Snapshot current state so Monitor only prints future *changes*
    monitor.on_notification()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()

    print(f"\n[{ts()}] Disconnecting...")
    await receiver.async_disconnect()
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
