"""CLI handler for the one-command build."""

from __future__ import annotations

from pathlib import Path

from open_finnish_lexicon.build import BuildOptions, build
from open_finnish_lexicon.cli.parsers import (
    OflArgumentParser,
    non_empty_str,
    parse_source_list,
)


def _parse_build_args(argv: list[str]) -> BuildOptions:
    parser = OflArgumentParser(
        prog="ofl build",
        description="Apply migrations, sync sources, reconcile, refresh, and export.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=non_empty_str,
        help="Target output file (.sqlite, .db, or .jsonl)",
    )
    parser.add_argument(
        "--manifest",
        type=non_empty_str,
        default=None,
        help="Path to an alternative source_releases.toml manifest",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip downloading and syncing sources; use existing database state",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write the sidecar <output>.report.json file",
    )
    parser.add_argument(
        "--overwrite",
        "--force",
        dest="overwrite",
        action="store_true",
        help="Replace an existing output/report file atomically",
    )
    parser.add_argument(
        "--sources",
        action="append",
        default=None,
        help="Comma-separated list of sources to sync (e.g. kaikki,frequency)",
    )
    parser.add_argument(
        "--exclude-sources",
        action="append",
        default=None,
        help="Comma-separated list of sources to skip (e.g. tatoeba)",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download rolling sources even if cached locally",
    )
    parser.add_argument(
        "--pure-jsonl",
        "--no-sources-header",
        dest="pure_jsonl",
        action="store_true",
        help="Omit the leading _sources metadata line when exporting .jsonl",
    )
    ns = parser.parse_args(argv[1:])
    return BuildOptions(
        output=Path(ns.output),
        manifest=Path(ns.manifest) if ns.manifest else None,
        skip_sync=ns.skip_sync,
        report=not ns.no_report,
        overwrite=ns.overwrite,
        sources=parse_source_list(ns.sources),
        exclude_sources=parse_source_list(ns.exclude_sources),
        force_download=ns.force_download,
        pure_jsonl=ns.pure_jsonl,
    )


def dispatch(argv: list[str]) -> int | None:
    if argv and argv[0] == "build":
        result = build(_parse_build_args(argv))
        print(
            f"build: output={result.output}"
            + (f" report={result.report_path}" if result.report_path else "")
        )
        return 0
    return None
