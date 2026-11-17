"""CLI command handlers for ingest."""

from __future__ import annotations

from pathlib import Path

from open_finnish_lexicon.cli.ingest import init_db, refresh_projections, seed_fixtures
from open_finnish_lexicon.cli.parsers import _parse_stale_build_run_args
from open_finnish_lexicon.cli.usage import USAGE
from open_finnish_lexicon.sources.registry import SOURCE_PIPELINES, run_manual_ingest
from open_finnish_lexicon.sync_all import archive_stale_build_runs, sync_all


def dispatch(argv: list[str]) -> int | None:
    if len(argv) == 1 and argv[0] == "init-db":
        return init_db()
    if len(argv) == 3 and argv[0].startswith("ingest-") and argv[1] == "--input":
        source_name = argv[0].removeprefix("ingest-").replace("-", "_")
        if source_name not in SOURCE_PIPELINES:
            raise SystemExit(USAGE)
        input_path = Path(argv[2])
        run_manual_ingest(source_name, input_path)
        return 0
    if len(argv) == 1 and argv[0] == "seed-fixtures":
        return seed_fixtures()
    if len(argv) == 1 and argv[0] == "sync-all":
        return sync_all()
    if len(argv) == 3 and argv[0] == "sync-all" and argv[1] == "--manifest":
        return sync_all(manifest_path=Path(argv[2]))
    if argv and argv[0] == "archive-stale-build-runs":
        archived = archive_stale_build_runs(
            older_than_hours=_parse_stale_build_run_args(argv)
        )
        print(f"archive stale build runs: archived={archived}")
        return 0
    if len(argv) == 1 and argv[0] == "refresh":
        return refresh_projections()
    return None
