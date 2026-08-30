"""Runtime capability discovery for Lyngdorf devices.

Vendor External Control Manual PDFs are not always accurate (see the
TDAI-3400 "I-prefixed" command fabrication and the MP series
TRIMTREB/TRIMTREBLE reply-vs-query mismatch discovered while fixing issue
#16). This module probes a real, connected device with every command we
know about from *any* supported model's protocol and records which ones
actually get a reply, so a consumer (e.g. a Home Assistant integration) can
dump ground-truth capability data when filing a spec-correction issue.

Safety: this only ever sends the read-only "?" query form of a command
(e.g. "!VOL?"), never a bare action command (e.g. "!MUTEON", "!ON") or a
"(value)" set-form command (e.g. "!VOL(0)"). The candidate command list is
restricted to an explicit allowlist of Msg types that are genuinely
status/info queries - it deliberately excludes power/mute toggle actions
(POWER_ON, POWER_OFF, MUTE_ON, MUTE_OFF, and the Zone B equivalents), which
have no query form and would change device state if sent verbatim. This
probe must never mutate a real amplifier's state.

Known limitation (verified against a real MP-60): a handful of commands in
our model dicts are reply-only echo keys - e.g. Msg.ROOM_PERFECT_POSITIONS_COUNT
("RPFOCCOUNT") only ever appears as the first line of the "!RPFOCS?"
list-style reply, and is not independently queryable as "!RPFOCCOUNT?". This
probe queries every candidate token standalone, so these show up in
`documented_broken_commands` even though the model genuinely supports the
underlying feature via its list-style query. Read that list with this in
mind rather than as an unconditional bug signal.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from .const import DEFAULT_LYNGDORF_PORT, Msg
from .models import (
    MP40_CONFIG,
    MP50_CONFIG,
    MP60_CONFIG,
    TDAI1120_CONFIG,
    TDAI2170_CONFIG,
    TDAI3400_CONFIG,
    LyngdorfModel,
)

_LOGGER = logging.getLogger(__package__)

# Msg types that are genuine read-only status/info queries on at least one
# supported model. Deliberately excludes action-only commands (POWER_ON,
# POWER_OFF, MUTE_ON, MUTE_OFF and their Zone B equivalents) which have no
# "?" query form and would toggle real device state if probed.
SAFE_QUERY_MESSAGES: frozenset[Msg] = frozenset(
    {
        Msg.DEVICE,
        Msg.VERBOSE,
        Msg.PING,
        Msg.POWER,
        Msg.VOLUME,
        Msg.MUTE,
        Msg.SOURCES_COUNT,
        Msg.SOURCE,
        Msg.SOURCES,
        Msg.SOURCE_LIST,
        Msg.ZONE_B_POWER,
        Msg.ZONE_B_VOLUME,
        Msg.ZONE_B_MUTE,
        Msg.ZONE_B_SOURCES_COUNT,
        Msg.ZONE_B_SOURCE,
        Msg.ZONE_B_SOURCES,
        Msg.AUDIO_IN,
        Msg.ZONE_B_AUDIO_IN,
        Msg.VIDEO_IN,
        Msg.STREAM_TYPE,
        Msg.ZONE_B_STREAM_TYPE,
        Msg.VIDEO_TYPE,
        Msg.AUDIO_TYPE,
        Msg.AUDIO_MODES_COUNT,
        Msg.AUDIO_MODE,
        Msg.AUDIO_MODEL,
        Msg.ROOM_PERFECT_POSITIONS_COUNT,
        Msg.ROOM_PERFECT_POSITION,
        Msg.ROOM_PERFECT_POSITIONS,
        Msg.ROOM_PERFECT_POSITION_LIST,
        Msg.ROOM_PERFECT_VOICINGS_COUNT,
        Msg.ROOM_PERFECT_VOICING,
        Msg.ROOM_PERFECT_VOICINGS,
        Msg.ROOM_PERFECT_VOICING_LIST,
        Msg.LIP_SYNC,
        Msg.LIP_SYNC_MIN_MAX,
        Msg.TRIM_BASS,
        Msg.TRIM_CENTRE,
        Msg.TRIM_HEIGHT,
        Msg.TRIM_LFE,
        Msg.TRIM_SURROUND,
        Msg.TRIM_TREBLE,
        Msg.TRIM_TREBLE_SET,
        Msg.BALANCE,
    }
)

_ALL_CONFIGS = (
    MP40_CONFIG,
    MP50_CONFIG,
    MP60_CONFIG,
    TDAI1120_CONFIG,
    TDAI2170_CONFIG,
    TDAI3400_CONFIG,
)


def _all_candidate_tokens() -> list[str]:
    """Union of every safe, query-only command string across all modeled
    device protocols - including commands from OTHER models than the one
    connected, since the whole point is finding commands a model's own
    spec/dict got wrong (e.g. a fabricated prefix, or a missing command).
    """
    tokens: set[str] = set()
    for config in _ALL_CONFIGS:
        for msg, command in config.messages.items():
            if msg in SAFE_QUERY_MESSAGES:
                tokens.add(command)
    return sorted(tokens)


@dataclass
class ProbeResult:
    """Result of probing a single candidate command against a device."""

    command: str
    response: str | None
    known_to_model: bool

    @property
    def responded(self) -> bool:
        return self.response is not None

    @property
    def reply_key(self) -> str | None:
        """The command name the device's reply is keyed under, e.g. for a
        response of "!TRIMTREBLE(0)" this is "TRIMTREBLE".

        This can legitimately differ from `command` (the token queried
        with) - e.g. querying MP series with "!TRIMTREB?" replies
        "!TRIMTREBLE(0)". That asymmetry is exactly the kind of spec
        inaccuracy this probe exists to surface - see `key_mismatch`.
        """
        if self.response is None:
            return None
        body = self.response.lstrip("!#")
        for sep in ("(", "?"):
            if sep in body:
                body = body.split(sep, 1)[0]
        return body or None

    @property
    def key_mismatch(self) -> bool:
        """True if the device replied under a different command name than
        the one queried with - e.g. asked "TRIMTREB?", got back
        "!TRIMTREBLE(...)". A strong signal the spec/dict has the wrong
        string for one of query-vs-reply."""
        return self.reply_key is not None and self.reply_key != self.command


@dataclass
class CapabilityProbeReport:
    """Full result of probing a device with every known candidate command."""

    host: str
    model: LyngdorfModel | None
    results: list[ProbeResult] = field(default_factory=list)

    @property
    def working_commands(self) -> list[ProbeResult]:
        """Commands that got a real reply."""
        return [r for r in self.results if r.responded]

    @property
    def undocumented_working_commands(self) -> list[ProbeResult]:
        """Commands that work but the connected model's own dict doesn't
        claim - evidence the model's spec/dict is missing something."""
        return [r for r in self.working_commands if not r.known_to_model]

    @property
    def documented_broken_commands(self) -> list[ProbeResult]:
        """Commands the connected model's own dict claims to support but
        got no reply - evidence the model's spec/dict has a wrong string."""
        return [r for r in self.results if r.known_to_model and not r.responded]

    @property
    def reply_key_mismatches(self) -> list[ProbeResult]:
        """Commands where the device replied under a different command name
        than the one queried with (see ProbeResult.key_mismatch) - the exact
        bug class that hid the MP series TRIMTREB/TRIMTREBLE mismatch:
        querying "TRIMTREB?" replies "!TRIMTREBLE(...)", so a plain
        working/broken check alone would miss it."""
        return [r for r in self.results if r.key_mismatch]

    def to_dict(self) -> dict[str, object]:
        """JSON-serializable summary suitable for attaching to a bug report."""
        return {
            "host": self.host,
            "model": self.model.name if self.model else None,
            "working_commands": {r.command: r.response for r in self.working_commands},
            "undocumented_working_commands": {
                r.command: r.response for r in self.undocumented_working_commands
            },
            "documented_broken_commands": [
                r.command for r in self.documented_broken_commands
            ],
            "reply_key_mismatches": {
                r.command: r.reply_key for r in self.reply_key_mismatches
            },
        }

    def to_text(self) -> str:
        """Human-readable summary suitable for pasting into a GitHub issue."""
        lines = [f"Lyngdorf capability probe for {self.host}"]
        lines.append(f"Model: {self.model.name if self.model else 'unknown'}")
        lines.append("")
        lines.append(f"Working commands ({len(self.working_commands)}):")
        for r in self.working_commands:
            lines.append(f"  {r.command} -> {r.response}")
        if self.undocumented_working_commands:
            lines.append("")
            lines.append(
                f"Undocumented working commands ({len(self.undocumented_working_commands)}) "
                "- not in this model's own command set, but responded anyway:"
            )
            for r in self.undocumented_working_commands:
                lines.append(f"  {r.command} -> {r.response}")
        if self.reply_key_mismatches:
            lines.append("")
            lines.append(
                f"Reply key mismatches ({len(self.reply_key_mismatches)}) - queried "
                "with one command name, device replied under a different one:"
            )
            for r in self.reply_key_mismatches:
                lines.append(f"  queried {r.command!r} -> replied as {r.reply_key!r}")
        if self.documented_broken_commands:
            lines.append("")
            lines.append(
                f"Documented but broken commands ({len(self.documented_broken_commands)}) "
                "- this model's command set claims these, but got no reply:"
            )
            for r in self.documented_broken_commands:
                lines.append(f"  {r.command}")
        return "\n".join(lines)


async def probe_capabilities(
    host: str,
    model: LyngdorfModel | None = None,
    port: int = DEFAULT_LYNGDORF_PORT,
    per_command_timeout: float = 1.0,
) -> CapabilityProbeReport:
    """Probe a real, live device with every known safe query command.

    Only ever sends the "?" query form of a command - never a bare action
    command or a "(value)" set-form command - so this cannot change the
    device's state. Useful when a model's documented command set
    (ModelConfig.messages) doesn't match reality: run this against the real
    device and diff the report against the model's own dict to find what
    the vendor spec got wrong.

    Args:
        host: Device IP address or hostname.
        model: The model believed to be connected, used only to annotate
            which probed commands the model's own dict already claims.
            Pass None to skip that annotation.
        port: TCP port to connect to.
        per_command_timeout: Seconds to wait for the first byte of a reply
            before considering the command unsupported.

    Returns:
        A CapabilityProbeReport with one ProbeResult per candidate command.
    """
    known_commands = set(model.config.messages.values()) if model else set()
    reader, writer = await asyncio.open_connection(host, port)
    results: list[ProbeResult] = []
    try:
        for token in _all_candidate_tokens():
            writer.write(f"!{token}?\r".encode())
            await writer.drain()
            data = await _read_reply_until_quiet(reader, per_command_timeout)
            response = data.decode("utf-8", errors="replace").strip() or None
            _LOGGER.debug("%s: probed %s -> %s", host, token, response)
            results.append(
                ProbeResult(
                    command=token,
                    response=response,
                    known_to_model=token in known_commands,
                )
            )
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return CapabilityProbeReport(host=host, model=model, results=results)


async def _read_reply_until_quiet(
    reader: asyncio.StreamReader,
    first_byte_timeout: float,
    quiet_period: float = 0.3,
) -> bytes:
    """Read a full reply, including multi-line list-style bursts (e.g. a
    "?LIST" query replies with a COUNT line followed by N item lines).

    A single `reader.read()` call can return only the first chunk of such a
    burst if the OS delivers it across more than one TCP segment - the rest
    would then bleed into the NEXT command's read, corrupting its result.
    So after the first byte arrives, keep draining until a short quiet
    period passes with no further data.
    """
    chunks: list[bytes] = []
    try:
        chunks.append(
            await asyncio.wait_for(reader.read(4096), timeout=first_byte_timeout)
        )
    except TimeoutError:
        return b""
    while True:
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=quiet_period)
        except TimeoutError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)
