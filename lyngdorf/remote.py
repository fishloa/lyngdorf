"""Remote-control keys - the RIO protocol's write-only button commands.

`Msg` (see `lyngdorf/const.py`) is a *bidirectional* registry: every entry
is both registered for an inbound callback and looked up for an outbound
write. Remote-control buttons (cursor navigation, `MENU`/`INFO`/`SETUP`,
`NUM(0..9)`, ...) do not fit that shape at all - the device replies to
none of them, ever. Putting them in `Msg` anyway is exactly what let them
sit dead for so long: nothing about a registry with no callback ever
firing looked wrong from the outside. This module gives them their own
table instead, kept deliberately separate from `Msg`.

`RemoteKey` is the primary interface, not merely a convenience typed
wrapper. Its consumer is Home Assistant's `remote` platform -
`RemoteEntity.async_send_command` is handed `command: Iterable[str]` - so
the *string* value is the stable, load-bearing API and the enum is there
so a non-HA caller (or a type checker) does not have to spell string
literals. Do not renumber or "clean up" these values; they are what a
consumer's YAML/scripts/blueprints will have on file.

Unlike `Control`/`PlaybackState` in `lyngdorf/states.py`, `RemoteKey` is
deliberately NOT lenient: there is no `_missing_` that turns an unknown
string into a usable member. Those two model values a live device reports
back and must never choke on (forwards compatibility with firmware this
library has not seen yet); a remote key is the opposite direction
entirely - a caller asking this library to send something - and a typo
there should be rejected loudly (`LyngdorfUnsupportedError`, raised by
`Receiver.send_remote_commands`/`Receiver.press`), not silently accepted
as a new "unknown" button that then goes nowhere.

See issue #46 for the audit that found this dead code and the design
behind this module.

:license: MIT, see LICENSE for more details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RemoteKey(StrEnum):
    """A button on the device's remote.

    The value is the command string a consumer sends (to
    `Receiver.send_remote_commands`) or receives back (from
    `Receiver.available_remote_keys`), and is stable public API - see the
    module docstring for why it must not be renumbered.
    """

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    ENTER = "enter"
    BACK = "back"
    EXIT = "exit"
    MENU = "menu"
    INFO = "info"
    SETTINGS = "settings"
    MULTIVIEW = "multiview"
    DIGIT_0 = "0"
    DIGIT_1 = "1"
    DIGIT_2 = "2"
    DIGIT_3 = "3"
    DIGIT_4 = "4"
    DIGIT_5 = "5"
    DIGIT_6 = "6"
    DIGIT_7 = "7"
    DIGIT_8 = "8"
    DIGIT_9 = "9"


# The ten digit keys, handled separately from `RemoteKeyTable.commands` -
# see that class's docstring for why.
_DIGIT_KEYS: frozenset[RemoteKey] = frozenset(
    {
        RemoteKey.DIGIT_0,
        RemoteKey.DIGIT_1,
        RemoteKey.DIGIT_2,
        RemoteKey.DIGIT_3,
        RemoteKey.DIGIT_4,
        RemoteKey.DIGIT_5,
        RemoteKey.DIGIT_6,
        RemoteKey.DIGIT_7,
        RemoteKey.DIGIT_8,
        RemoteKey.DIGIT_9,
    }
)


@dataclass(frozen=True)
class RemoteKeyTable:
    """The write-only remote-key wire commands for one model family.

    `commands` maps every non-digit `RemoteKey` to its literal wire token
    (e.g. `RemoteKey.UP` -> `"DIRU"`). The default is empty, which is
    exactly right for the whole TDAI family: no navigation hardware, no
    remote keys, an explicitly empty table rather than one inferred from
    some other capability flag - see `ModelConfig.remote_keys`.

    Digits are deliberately NOT ten entries in `commands`. `!NUM(X)` is
    one parameterised command on the wire, and `digit_format` - a single
    `str.format`-style template such as `"NUM({})"` - expresses that
    directly, applied to the digit `RemoteKey`'s own value ("0".."9")
    rather than transcribing the wire format one digit at a time. `None`
    on a model with no digit buttons at all (matching `commands` being
    empty by default on such a model).

    `commands` is a plain `dict`, not something immutable - `RemoteKeyTable`
    is frozen, but that only stops rebinding the field, not mutating the
    dict object it points to. Treat it as read-only regardless: the same
    `RemoteKeyTable` instance (`MP_REMOTE_KEYS`, `P_REMOTE_KEYS` in
    mp_series.py/p_series.py) is shared across every model in a family, so
    a mutation to one model's table would silently change every sibling
    model's capability too.
    """

    commands: dict[RemoteKey, str] = field(default_factory=dict)
    digit_format: str | None = None

    def available_keys(self) -> frozenset[RemoteKey]:
        """Every `RemoteKey` this table has a wire command for."""
        keys: set[RemoteKey] = set(self.commands)
        if self.digit_format is not None:
            keys.update(_DIGIT_KEYS)
        return frozenset(keys)

    def command_for(self, key: RemoteKey) -> str:
        """The wire command for `key`.

        Raises:
            KeyError: `key` is not in this table - same failure mode as
                `ModelConfig.lookup_command` for an unsupported `Msg`.
        """
        if key in self.commands:
            return self.commands[key]
        if self.digit_format is not None and key in _DIGIT_KEYS:
            return self.digit_format.format(key.value)
        raise KeyError(key)


def resolve_remote_key(value: str | RemoteKey) -> RemoteKey | None:
    """Resolve a command name to a `RemoteKey`, case-insensitively.

    Home Assistant users type `up` in YAML, scripts may send `UP`, and
    blueprints may send `Up` - all three (and any other casing) resolve
    to `RemoteKey.UP`. A `RemoteKey` passed in directly is returned
    unchanged, so callers that are not going through strings at all (and
    the resolver's own callers below, which do not need to special-case
    the two possible input types) both work the same way.

    Returns `None` rather than raising when `value` matches nothing -
    only the caller (`Receiver.send_remote_commands`) knows which keys
    the connected model actually supports, and can raise one
    `LyngdorfUnsupportedError` that names both the bad value and what the
    model does support, instead of this function raising on the resolve
    step alone with no model context at all.
    """
    if isinstance(value, RemoteKey):
        return value
    if not isinstance(value, str):
        # Statically unreachable given the annotation - the parameter is
        # `str | RemoteKey` and RemoteKey is handled above - and kept
        # deliberately. Values reach this from a consumer's untyped
        # edges: Home Assistant passes whatever a user typed into a
        # service call, whatever the signature says. Returning None lets
        # the caller raise one error naming the bad value and the model's
        # supported keys; deleting it turns that into an AttributeError
        # from .strip().
        return None  # type: ignore[unreachable]
    try:
        return RemoteKey(value.strip().lower())
    except ValueError:
        return None
