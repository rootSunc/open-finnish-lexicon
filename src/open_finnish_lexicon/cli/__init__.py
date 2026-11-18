"""open-finnish-lexicon command line interface."""

from importlib.metadata import PackageNotFoundError, version
import sys

import psycopg

from open_finnish_lexicon.cli.parsers import HelpRequestedError
from open_finnish_lexicon.cli.usage import USAGE


def _package_version() -> str:
    try:
        return version("open-finnish-lexicon")
    except PackageNotFoundError:
        return "1.0.0"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if not argv or argv[0] in {"help", "--help", "-h"}:
        print(USAGE)
        return 0
    if argv[0] in {"--version", "-V"}:
        print(f"open-finnish-lexicon {_package_version()}")
        return 0

    from open_finnish_lexicon.cli.commands import DISPATCHERS

    try:
        for dispatch in DISPATCHERS:
            result = dispatch(argv)
            if result is not None:
                return result
    except HelpRequestedError:
        return 0
    except psycopg.OperationalError as exc:
        detail = str(exc).splitlines()[0].strip()
        raise SystemExit(
            "Database connection failed"
            + (f": {detail}" if detail else ".")
            + " Check OFL_DATABASE_URL."
        ) from None
    raise SystemExit(USAGE)


__all__ = ["USAGE", "main"]
