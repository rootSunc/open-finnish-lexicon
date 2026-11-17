"""One command from an empty database to an exported lexicon file."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import time

from open_finnish_lexicon.cli.ingest import init_db
from open_finnish_lexicon.export import export_jsonl, export_sqlite
from open_finnish_lexicon.normalize.lexemes import reconcile_lexemes
from open_finnish_lexicon.quality.report import collect_data_quality_metrics
from open_finnish_lexicon.sources.registry import refresh_runtime_views
from open_finnish_lexicon.sync_all import sync_all

SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
JSONL_SUFFIXES = {".jsonl"}


@dataclass(frozen=True)
class BuildOptions:
    output: Path
    manifest: Path | None = None
    skip_sync: bool = False
    report: bool = True


@dataclass
class BuildResult:
    output: Path
    report_path: Path | None
    steps: dict[str, float] = field(default_factory=dict)


def output_format(output: Path) -> str:
    suffix = output.suffix.lower()
    if suffix in SQLITE_SUFFIXES:
        return "sqlite"
    if suffix in JSONL_SUFFIXES:
        return "jsonl"
    raise ValueError(f"cannot tell the export format from {output.name!r}; use .sqlite or .jsonl")


def report_path_for(output: Path) -> Path:
    return output.with_name(output.name + ".report.json")


def _log(message: str) -> None:
    print(f"[build] {message}", flush=True, file=sys.stderr)


def build(options: BuildOptions) -> BuildResult:
    """Schema → sync every source → reconcile → refresh → export (+ report).

    Fails before touching the database when the output already exists or its
    format is unknown, so a long sync never ends in a refused export.
    """

    fmt = output_format(options.output)
    report_path = report_path_for(options.output) if options.report else None
    for path in (options.output, report_path):
        if path is not None and path.exists():
            raise FileExistsError(f"{path} already exists")
    options.output.parent.mkdir(parents=True, exist_ok=True)

    result = BuildResult(output=options.output, report_path=report_path)

    def step(name: str, fn) -> None:
        _log(f"{name}: starting")
        started = time.monotonic()
        fn()
        result.steps[name] = round(time.monotonic() - started, 1)
        _log(f"{name}: done in {result.steps[name]}s")

    step("init-db", init_db)
    if not options.skip_sync:
        step("sync", lambda: sync_all(manifest_path=options.manifest, refresh=False))
    step("reconcile", reconcile_lexemes)
    step("refresh", refresh_runtime_views)
    if fmt == "sqlite":
        step("export", lambda: export_sqlite(options.output))
    else:
        step("export", lambda: export_jsonl(options.output))
    if report_path is not None:
        metrics = collect_data_quality_metrics()
        metrics["build_steps_seconds"] = result.steps
        report_path.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        _log(f"report written to {report_path}")
    return result
