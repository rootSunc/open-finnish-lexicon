"""CLI handler for the one-command build."""

from __future__ import annotations

from pathlib import Path

from open_finnish_lexicon.build import BuildOptions, build
from open_finnish_lexicon.cli.parsers.spec import flag, non_empty, opt, parse_options

_BUILD_USAGE = "usage: build --output <file.sqlite|file.jsonl> [--manifest <path>] [--skip-sync] [--no-report]"


def _parse_build_args(argv: list[str]) -> BuildOptions:
    values = parse_options(
        argv,
        _BUILD_USAGE,
        defaults={"output": None, "manifest": None, "skip_sync": False, "no_report": False},
        options=(
            opt("--output", "output", non_empty("--output")),
            opt("--manifest", "manifest", non_empty("--manifest")),
            flag("--skip-sync", "skip_sync"),
            flag("--no-report", "no_report"),
        ),
    )
    if values["output"] is None:
        raise SystemExit(_BUILD_USAGE)
    return BuildOptions(
        output=Path(values["output"]),
        manifest=Path(values["manifest"]) if values["manifest"] else None,
        skip_sync=values["skip_sync"],
        report=not values["no_report"],
    )


def dispatch(argv: list[str]) -> int | None:
    if argv and argv[0] == "build":
        result = build(_parse_build_args(argv))
        print(f"build: output={result.output}" + (f" report={result.report_path}" if result.report_path else ""))
        return 0
    return None
