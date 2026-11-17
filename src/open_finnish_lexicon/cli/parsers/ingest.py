"""Source ingest CLI argument parsers."""

from open_finnish_lexicon.cli.parsers.spec import opt, parse_options

_STALE_BUILD_RUN_USAGE = "usage: archive-stale-build-runs [--older-than-hours <n>]"


def _parse_stale_build_run_args(argv: list[str]) -> int:
    values = parse_options(
        argv,
        _STALE_BUILD_RUN_USAGE,
        defaults={"older_than_hours": 6},
        options=(opt("--older-than-hours", "older_than_hours", int),),
    )
    if values["older_than_hours"] <= 0:
        raise SystemExit("usage: --older-than-hours must be > 0")
    return values["older_than_hours"]


__all__ = ["_parse_stale_build_run_args"]
