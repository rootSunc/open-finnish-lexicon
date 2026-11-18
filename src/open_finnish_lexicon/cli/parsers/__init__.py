"""Standard-library ``argparse`` helpers for ``ofl`` subcommands."""

from __future__ import annotations

import argparse
from typing import NoReturn


class HelpRequestedError(Exception):
    """Raised internally when ``-h`` / ``--help`` prints subcommand usage."""


class _HelpAction(argparse.Action):
    def __init__(
        self,
        option_strings: list[str],
        dest: str = argparse.SUPPRESS,
        default: str = argparse.SUPPRESS,
        help: str | None = "show this help message and exit",
    ) -> None:
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        print(parser.format_help().rstrip())
        raise HelpRequestedError


class OflArgumentParser(argparse.ArgumentParser):
    """``ArgumentParser`` with clean ``SystemExit`` errors and return-0 help."""

    def __init__(self, prog: str, description: str = "") -> None:
        super().__init__(
            prog=prog,
            description=description,
            add_help=False,
            allow_abbrev=False,
        )
        self.add_argument("-h", "--help", action=_HelpAction)

    def error(self, message: str) -> NoReturn:
        raise SystemExit(f"{self.format_usage().strip()}\nerror: {message}")


def positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected positive integer, got {raw!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {value}")
    return value


def non_empty_str(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        raise argparse.ArgumentTypeError("value must not be empty")
    return cleaned


def parse_source_list(values: list[str] | None) -> tuple[str, ...] | None:
    if not values:
        return None
    items: list[str] = []
    for chunk in values:
        for part in chunk.split(","):
            normalized = part.strip().replace("-", "_")
            if normalized and normalized not in items:
                items.append(normalized)
    return tuple(items) if items else None


__all__ = [
    "HelpRequestedError",
    "OflArgumentParser",
    "non_empty_str",
    "parse_source_list",
    "positive_int",
]
