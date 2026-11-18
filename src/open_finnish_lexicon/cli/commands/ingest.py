"""CLI command handlers for ingest."""

from __future__ import annotations

from pathlib import Path

from open_finnish_lexicon.cli.ingest import init_db, refresh_projections, seed_fixtures
from open_finnish_lexicon.cli.parsers import (
    OflArgumentParser,
    non_empty_str,
    parse_source_list,
    positive_int,
)
from open_finnish_lexicon.cli.usage import USAGE
from open_finnish_lexicon.sources.registry import SOURCE_PIPELINES, run_manual_ingest
from open_finnish_lexicon.sync_all import archive_stale_build_runs, sync_all


def _parse_no_arg_command(argv: list[str], prog: str, description: str) -> None:
    parser = OflArgumentParser(prog=prog, description=description)
    parser.parse_args(argv[1:])


def dispatch(argv: list[str]) -> int | None:
    if not argv:
        return None
    cmd = argv[0]

    if cmd == "init-db":
        _parse_no_arg_command(argv, "ofl init-db", "Apply pending PostgreSQL migrations.")
        return init_db()

    if cmd.startswith("ingest-"):
        source_name = cmd.removeprefix("ingest-").replace("-", "_")
        if source_name not in SOURCE_PIPELINES:
            raise SystemExit(USAGE)
        parser = OflArgumentParser(
            prog=f"ofl {cmd}",
            description=f"Stage and project one local {source_name} file.",
        )
        parser.add_argument(
            "--input",
            required=True,
            type=non_empty_str,
            help="Local input file or directory to ingest",
        )
        ns = parser.parse_args(argv[1:])
        run_manual_ingest(source_name, Path(ns.input))
        return 0

    if cmd == "seed-fixtures":
        _parse_no_arg_command(
            argv,
            "ofl seed-fixtures",
            "Ingest bundled fixture datasets (requires OFL_PROFILE=fixture).",
        )
        return seed_fixtures()

    if cmd == "sync-all":
        parser = OflArgumentParser(
            prog="ofl sync-all",
            description="Download pinned releases and ingest sources into PostgreSQL.",
        )
        parser.add_argument(
            "--manifest",
            type=non_empty_str,
            default=None,
            help="Path to an alternative source_releases.toml manifest",
        )
        parser.add_argument(
            "--sources",
            action="append",
            default=None,
            help="Comma-separated list of sources to sync",
        )
        parser.add_argument(
            "--exclude-sources",
            action="append",
            default=None,
            help="Comma-separated list of sources to skip",
        )
        parser.add_argument(
            "--force-download",
            action="store_true",
            help="Re-download rolling sources even if cached locally",
        )
        parser.add_argument(
            "--no-refresh",
            action="store_true",
            help="Skip post-sync runtime view refresh",
        )
        ns = parser.parse_args(argv[1:])
        sources = parse_source_list(ns.sources)
        exclude_sources = parse_source_list(ns.exclude_sources)
        has_extended_opts = bool(
            sources or exclude_sources or ns.force_download or ns.no_refresh
        )
        if not has_extended_opts:
            if ns.manifest is None:
                return sync_all()
            return sync_all(manifest_path=Path(ns.manifest))
        return sync_all(
            manifest_path=Path(ns.manifest) if ns.manifest else None,
            refresh=not ns.no_refresh,
            sources=sources,
            exclude_sources=exclude_sources,
            force_download=ns.force_download,
        )

    if cmd == "archive-stale-build-runs":
        parser = OflArgumentParser(
            prog="ofl archive-stale-build-runs",
            description="Mark stale 'running' build_run rows as failed.",
        )
        parser.add_argument(
            "--older-than-hours",
            type=positive_int,
            default=6,
            help="Age threshold in hours (default: 6)",
        )
        ns = parser.parse_args(argv[1:])
        archived = archive_stale_build_runs(older_than_hours=ns.older_than_hours)
        print(f"archive stale build runs: archived={archived}")
        return 0

    if cmd == "refresh":
        _parse_no_arg_command(
            argv,
            "ofl refresh",
            "Rebuild collocations, Chinese layer, and rule-based morphology checks.",
        )
        return refresh_projections()

    return None
