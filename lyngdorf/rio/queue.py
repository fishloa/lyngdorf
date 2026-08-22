"""The paced, coalescing outbound command queue (spec §9 item 1).

Measured against a real MP-60: writing straight to the transport with no
pacing overflows a hardware queue-depth cliff of ~16 in-flight commands
(https://github.com/fishloa/lyngdorf/issues/35). This module holds the
pure, stateless half of that fix - the coalescing-key logic and the
absolute-setter shape it depends on; the pacing/draining half lives in
`RioClient` (client.py), which is where the actual queue and its drain
task live.
"""

from __future__ import annotations

import dataclasses
import re

from ..const import ABSOLUTE_SETTER_MESSAGES
from ..models import LyngdorfModel

# Shape of an absolute-setter command: a bare uppercase token followed by a
# single parenthesised integer, e.g. "VOL(-300)" or "TRIMBASS(20)". Chosen
# deliberately narrow rather than a bare `TOKEN(.*)`: every write this
# library actually sends in that family (volume, zone B volume, the six
# trims, lipsync, balance) is a signed integer, so anything else matching
# `TOKEN(...)` but not this exact shape is left alone rather than guessed
# at - see `_coalesce_key`.
_ABSOLUTE_SETTER_SHAPE = re.compile(r"^([A-Z][A-Z0-9_]*)\(-?\d+\)$")


def _absolute_setter_tokens_for_model(model: LyngdorfModel) -> frozenset[str]:
    """The wire tokens this model uses for an absolute-setter message.

    Derived from `ABSOLUTE_SETTER_MESSAGES` (const.py) via
    `model.lookup_command` rather than hardcoded as literal strings,
    because the wire token for the same message differs by family - e.g.
    `Msg.TRIM_BASS` is `TRIMBASS` on MP/P but `BASS` on TDAI. A message a
    given model does not define (`KeyError`) simply contributes no token,
    same as any other unsupported message lookup elsewhere in this file.
    """
    tokens = set()
    for msg in ABSOLUTE_SETTER_MESSAGES:
        try:
            tokens.add(model.lookup_command(msg))
        except KeyError:
            continue
    return frozenset(tokens)


def _coalesce_key(command: str, absolute_setter_tokens: frozenset[str]) -> str | None:
    """The coalescing key for `command`, or None if it must never coalesce.

    Only a command shaped like an absolute setter (see
    `_ABSOLUTE_SETTER_SHAPE`) *and* whose token is one this model actually
    uses for a message in `ABSOLUTE_SETTER_MESSAGES` can coalesce - for
    those, the latest value fully replaces the meaning of an earlier
    queued one. Everything else keeps no key and is therefore never
    coalesced:

    - a relative/stepping command (`VOLUP`, `VOL+`, `RPVOI-`, ...) has no
      parenthesised value at all, so it never matches the shape;
    - a query (`VOL?`) likewise never matches the shape;
    - sequential input - the `NUM(0)`..`NUM(9)` digits, where `NUM` is not
      an absolute-setter token for any model - matches the shape but is
      filtered out by the token check, because order and count are the
      whole meaning there.
    """
    match = _ABSOLUTE_SETTER_SHAPE.match(command)
    if match is None:
        return None
    token = match.group(1)
    if token not in absolute_setter_tokens:
        return None
    return token


@dataclasses.dataclass(frozen=True, slots=True)
class _QueuedWrite:
    """One command waiting to be written, and its coalescing key (if any)."""

    command: str
    coalesce_key: str | None
