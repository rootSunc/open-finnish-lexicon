"""One argv walk for every pipeline CLI subcommand.

Each subcommand used to take its options with its own hand-written
``while index < len(argv)`` loop -- 36 copies of the same walk, every one of
them free to drift. The walk lives here now; a subcommand only declares the
options it accepts and whatever validation it wants once parsing is done.

The semantics are exactly the ones those loops already had, because the
commands ship in ``package.json`` scripts and in ``scripts/``:

* ``argv[0]`` is the subcommand name and is skipped.
* A bare ``--`` is ignored rather than ending option parsing.
* An option that needs a value but sits last in ``argv`` is reported as
  unrecognised, like any unknown token.
* Anything unrecognised raises ``SystemExit(usage)``.
* Repeating an option overwrites the earlier value, in argv order, so flags
  that clear other options stay order-sensitive.

``argparse`` would change all of that: it ends option parsing at ``--``,
accepts ``--opt=value`` and prefix abbreviations, adds ``-h``, and exits 2
through stderr instead of raising ``SystemExit`` with a usage string.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "Option",
    "choice",
    "flag",
    "flags",
    "ignored",
    "int_or_all",
    "mapped",
    "non_empty",
    "opt",
    "parse_options",
    "positive_int",
    "require_input_path",
]


@dataclass(frozen=True)
class Option:
    """One ``--name`` the walk recognises.

    ``convert`` set means the option takes the next token as its value;
    otherwise it is a flag and ``writes`` says which destinations it sets.
    """

    name: str
    convert: Callable[[str], Any] | None = None
    dest: str | None = None
    writes: Mapping[str, Any] | None = None
    append: bool = False


def opt(name: str, dest: str, convert: Callable[[str], Any], *, append: bool = False) -> Option:
    """``--name <value>``. With ``append`` every occurrence is collected."""

    return Option(name=name, convert=convert, dest=dest, append=append)


def flag(name: str, dest: str, *, value: Any = True) -> Option:
    """``--name`` with no value, storing ``value`` in ``dest``."""

    return Option(name=name, writes={dest: value})


def flags(name: str, writes: Mapping[str, Any]) -> Option:
    """``--name`` with no value, writing several destinations where it appears."""

    return Option(name=name, writes=dict(writes))


def ignored(name: str) -> Option:
    """``--name`` accepted for compatibility and discarded."""

    return Option(name=name, writes={})


def parse_options(
    argv: list[str],
    usage: str,
    *,
    defaults: Mapping[str, Any],
    options: tuple[Option, ...],
) -> dict[str, Any]:
    """Walk ``argv[1:]`` and return the resolved option values."""

    by_name = {option.name: option for option in options}
    values: dict[str, Any] = dict(defaults)
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "--":
            index += 1
            continue
        option = by_name.get(token)
        if option is None:
            raise SystemExit(usage)
        if option.convert is None:
            values.update(option.writes or {})
            index += 1
            continue
        if index + 1 >= len(argv):
            # The hand-written loops guarded every value option with
            # `index + 1 < len(argv)`, so a trailing option fell through to
            # their unknown-token branch.
            raise SystemExit(usage)
        value = option.convert(argv[index + 1])
        assert option.dest is not None
        if option.append:
            values[option.dest] = [*values[option.dest], value]
        else:
            values[option.dest] = value
        index += 2
    return values


def require_input_path(argv: list[str], usage: str) -> Path:
    """``--input <path>`` and nothing else; the first match wins.

    Unlike :func:`parse_options` this returns as soon as it sees the option,
    so trailing tokens are never looked at.
    """

    index = 1
    while index < len(argv):
        if argv[index] == "--":
            index += 1
            continue
        if argv[index] == "--input" and index + 1 < len(argv):
            return Path(argv[index + 1])
        raise SystemExit(usage)
    raise SystemExit(usage)


def choice(allowed: Container[str], usage: str) -> Callable[[str], str]:
    """Value restricted to ``allowed``, checked where the option appears."""

    def convert(raw: str) -> str:
        if raw not in allowed:
            raise SystemExit(usage)
        return raw

    return convert


def mapped(mapping: Mapping[str, Any], usage: str) -> Callable[[str], Any]:
    """Value translated through ``mapping``; anything else is a usage error."""

    def convert(raw: str) -> Any:
        if raw not in mapping:
            raise SystemExit(usage)
        return mapping[raw]

    return convert


def int_or_all(raw: str) -> int | None:
    """``<n>`` as an int, or ``all`` meaning no limit."""

    return None if raw == "all" else int(raw)


def positive_int(option: str, usage: str) -> Callable[[str], int]:
    """Int that must be > 0, reporting the bad value and the range separately."""

    def convert(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise SystemExit(usage) from None
        if value <= 0:
            raise SystemExit(f"{option} must be a positive integer")
        return value

    return convert


def non_empty(option: str) -> Callable[[str], str]:
    """Stripped string that must not be empty."""

    def convert(raw: str) -> str:
        value = raw.strip()
        if not value:
            raise SystemExit(f"{option} must not be empty")
        return value

    return convert
