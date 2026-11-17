"""Data quality maintenance CLI argument parsers."""

from open_finnish_lexicon.cli.parsers.spec import (
    flag,
    ignored,
    non_empty,
    opt,
    parse_options,
    positive_int,
)

_ZH_GLOSS_SANITIZE_USAGE = "usage: sanitize-invalid-zh-glosses [--apply]"
_EXAMPLE_MORPHOLOGY_USAGE = (
    "usage: validate-example-morphology [--limit <n>] [--source <family>] "
    "[--revalidate] [--dry-run]"
)


def _parse_zh_gloss_sanitize_args(argv: list[str]) -> bool:
    values = parse_options(
        argv,
        _ZH_GLOSS_SANITIZE_USAGE,
        defaults={"apply": False},
        options=(
            flag("--apply", "apply"),
            # Accepted so callers can spell out the default explicitly.
            ignored("--dry-run"),
        ),
    )
    return values["apply"]


def _parse_example_morphology_args(
    argv: list[str],
) -> tuple[int | None, str | None, bool, bool]:
    values = parse_options(
        argv,
        _EXAMPLE_MORPHOLOGY_USAGE,
        defaults={
            "limit": None,
            "source_family": None,
            "revalidate": False,
            "dry_run": False,
        },
        options=(
            opt("--limit", "limit", positive_int("--limit", _EXAMPLE_MORPHOLOGY_USAGE)),
            opt("--source", "source_family", non_empty("--source")),
            flag("--revalidate", "revalidate"),
            flag("--dry-run", "dry_run"),
        ),
    )
    return (
        values["limit"],
        values["source_family"],
        values["revalidate"],
        values["dry_run"],
    )


__all__ = [
    "_parse_example_morphology_args",
    "_parse_zh_gloss_sanitize_args",
]
