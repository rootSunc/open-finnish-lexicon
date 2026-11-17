"""open-finnish-lexicon command line interface."""

import sys

import psycopg

from open_finnish_lexicon.cli.usage import USAGE


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"help", "--help", "-h"}:
        print(USAGE)
        return 0
    from open_finnish_lexicon.cli.commands import DISPATCHERS

    try:
        for dispatch in DISPATCHERS:
            result = dispatch(argv)
            if result is not None:
                return result
    except psycopg.OperationalError as exc:
        detail = str(exc).splitlines()[0].strip()
        raise SystemExit(
            "Database connection failed"
            + (f": {detail}" if detail else ".")
            + " Check OFL_DATABASE_URL."
        ) from None
    raise SystemExit(USAGE)


__all__ = ["USAGE", "main"]
