from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys

import psycopg

from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connect, connection_scope
from open_finnish_lexicon.enrich.zh import rebuild_chinese_glosses, select_zh_glosses
from open_finnish_lexicon.morphology.validator import validate_forms_with_rules
from open_finnish_lexicon.normalize.collocations import rebuild_collocations
from open_finnish_lexicon.sources.cedict_zh_project import project_cedict_zh_rows
from open_finnish_lexicon.sources.cedict_zh_stage import stage_cedict_zh_rows
from open_finnish_lexicon.sources.dbnary_zh_project import project_dbnary_zh_rows
from open_finnish_lexicon.sources.dbnary_zh_stage import stage_dbnary_zh_rows
from open_finnish_lexicon.sources.finnwordnet_project import project_finnwordnet_rows
from open_finnish_lexicon.sources.finnwordnet_stage import stage_finnwordnet_rows
from open_finnish_lexicon.sources.frequency_project import project_frequency_rows
from open_finnish_lexicon.sources.frequency_stage import stage_frequency_rows
from open_finnish_lexicon.sources.kaikki_project import project_kaikki_entries
from open_finnish_lexicon.sources.kaikki_stage import stage_kaikki_entries
from open_finnish_lexicon.sources.omorfi_project import project_omorfi_rows
from open_finnish_lexicon.sources.omorfi_stage import stage_omorfi_rows
from open_finnish_lexicon.sources.omw_zh_project import project_omw_zh_rows
from open_finnish_lexicon.sources.omw_zh_stage import stage_omw_zh_rows
from open_finnish_lexicon.sources.tatoeba_project import project_tatoeba_rows
from open_finnish_lexicon.sources.tatoeba_stage import stage_tatoeba_rows
from open_finnish_lexicon.sources.warehouse import (
    active_source_file_for_name,
    clear_retired_source_registry_documents_in_batches,
    finalize_source_registry_snapshot,
    source_file_id_for_path,
)
from open_finnish_lexicon.sources.wiktionary_zh_project import project_wiktionary_zh_rows
from open_finnish_lexicon.sources.wiktionary_zh_stage import stage_wiktionary_zh_rows


type StageFn = Callable[..., int]
type ProjectFn = Callable[..., int]


@dataclass(frozen=True)
class SourcePipeline:
    stage: StageFn
    project: ProjectFn


SOURCE_PIPELINES = frozenset(
    {
        "omorfi",
        "kaikki",
        "finnwordnet",
        "frequency",
        "tatoeba",
        "wiktionary_zh",
        "dbnary_zh",
        "omw_zh",
        "cedict_zh",
    }
)


def get_source_pipeline(source_name: str) -> SourcePipeline:
    pipelines: dict[str, SourcePipeline] = {
        "omorfi": SourcePipeline(stage=stage_omorfi_rows, project=project_omorfi_rows),
        "kaikki": SourcePipeline(stage=stage_kaikki_entries, project=project_kaikki_entries),
        "finnwordnet": SourcePipeline(
            stage=stage_finnwordnet_rows, project=project_finnwordnet_rows
        ),
        "frequency": SourcePipeline(stage=stage_frequency_rows, project=project_frequency_rows),
        "tatoeba": SourcePipeline(stage=stage_tatoeba_rows, project=project_tatoeba_rows),
        "wiktionary_zh": SourcePipeline(
            stage=stage_wiktionary_zh_rows, project=project_wiktionary_zh_rows
        ),
        "dbnary_zh": SourcePipeline(stage=stage_dbnary_zh_rows, project=project_dbnary_zh_rows),
        "omw_zh": SourcePipeline(stage=stage_omw_zh_rows, project=project_omw_zh_rows),
        "cedict_zh": SourcePipeline(stage=stage_cedict_zh_rows, project=project_cedict_zh_rows),
    }
    return pipelines[source_name]


FIXTURE_INPUTS: tuple[tuple[str, Path], ...] = (
    ("omorfi", Path("tests/fixtures/omorfi.tsv")),
    ("kaikki", Path("tests/fixtures/kaikki-juosta.jsonl")),
    ("finnwordnet", Path("tests/fixtures/finnwordnet.tsv")),
    ("tatoeba", Path("tests/fixtures/tatoeba.tsv")),
    ("frequency", Path("tests/fixtures/frequency.csv")),
    ("omw_zh", Path("tests/fixtures/omw-zh-fixture.tab")),
    ("cedict_zh", Path("tests/fixtures/cedict-zh-fixture.txt")),
    ("wiktionary_zh", Path("tests/fixtures/wiktionary-zh-fixture.jsonl")),
    ("dbnary_zh", Path("tests/fixtures/dbnary-zh-exolex.ttl")),
)

# Run Tatoeba and Frequency before Omorfi so Omorfi's candidate token harvester
# sees all example and frequency surface tokens on the very first build.
SYNC_SOURCE_ORDER = (
    "kaikki",
    "tatoeba",
    "frequency",
    "omorfi",
    "finnwordnet",
    "omw_zh",
    "cedict_zh",
    "dbnary_zh",
    "wiktionary_zh",
)

CHINESE_CANDIDATE_SOURCES = {"wiktionary_zh", "dbnary_zh", "omw_zh", "cedict_zh"}


def _is_fixture_input_path(input_path: Path) -> bool:
    """Recognize repository fixture paths before they can enter the real DB."""

    parts = {part.casefold() for part in input_path.resolve().parts}
    return any(part == "fixtures" or part.startswith("fixture-") for part in parts)


def _assert_manual_ingest_profile(input_path: Path) -> None:
    """Keep fixture data out of a real-profile database."""

    settings = get_pipeline_settings()
    if settings.data_profile == "real" and _is_fixture_input_path(input_path):
        raise RuntimeError(
            "manual ingest refuses fixture input while OFL_PROFILE=real; "
            "use OFL_PROFILE=fixture for test data"
        )


def cleanup_retired_source_documents(source_name: str) -> int:
    """Refresh dependent Chinese selections if needed, then purge retired warehouse rows."""

    if source_name in CHINESE_CANDIDATE_SOURCES:
        select_zh_glosses()
        rebuild_chinese_glosses()
    with connect() as cleanup_conn:
        row = cleanup_conn.execute(
            "select id from warehouse.source_registry where name = %s",
            (source_name,),
        ).fetchone()
    if row is None:
        return 0
    return clear_retired_source_registry_documents_in_batches(
        source_registry_id=int(row[0]),
    )


def run_manual_ingest(source_name: str, input_path: Path) -> None:
    settings = get_pipeline_settings()
    _assert_manual_ingest_profile(input_path)
    pipeline = get_source_pipeline(source_name)
    stage_kwargs: dict[str, object] = {
        "version": "manual",
        "source_url": str(input_path.resolve()),
    }
    if source_name == "kaikki" and settings.data_profile == "real":
        stage_kwargs["reject_empty_snapshot"] = True
    source_file_id = pipeline.stage(input_path, **stage_kwargs)
    with connect() as conn:
        pipeline.project(input_path, source_file_id=source_file_id, connection=conn)
        finalize_source_snapshot(
            source_name,
            input_path,
            source_file_id=source_file_id,
            cleanup_superseded_documents=False,
            connection=conn,
        )
        conn.commit()

    try:
        cleanup_retired_source_documents(source_name)
    except Exception as exc:
        print(
            f"[{source_name}] retired warehouse cleanup deferred: {exc}",
            flush=True,
            file=sys.stderr,
        )


def finalize_source_snapshot(
    source_name: str,
    input_path: Path,
    *,
    source_file_id: int | None = None,
    cleanup_superseded_documents: bool = True,
    connection: psycopg.Connection | None = None,
) -> None:
    """Activate the successfully projected file and retire older release paths."""

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        resolved_file_id = source_file_id_for_path(
            conn,
            source_name=source_name,
            local_path=input_path,
            source_file_id=source_file_id,
        )
        registry_row = conn.execute(
            "select source_registry_id from warehouse.source_file where id = %s",
            (resolved_file_id,),
        ).fetchone()
        if registry_row is None:
            raise RuntimeError(f"source file is not staged: {source_name} {input_path}")
        finalize_source_registry_snapshot(
            conn,
            source_registry_id=int(registry_row[0]),
            active_source_file_id=resolved_file_id,
            cleanup_superseded_documents=cleanup_superseded_documents,
        )
        if owns_connection:
            conn.commit()


def reproject_active_chinese_sources() -> None:
    """Re-align active Chinese candidate sources after lexeme reconciliation."""

    for source_name in ("omw_zh", "cedict_zh", "dbnary_zh", "wiktionary_zh"):
        with connect() as conn:
            active = active_source_file_for_name(conn, source_name=source_name)
            if active is None:
                continue
            source_file_id, local_path = active
            pipeline = get_source_pipeline(source_name)
            pipeline.project(local_path, source_file_id=source_file_id, connection=conn)
            conn.commit()


def refresh_runtime_views(*, refresh_forms: bool = True, reproject_zh: bool = False) -> None:
    """Rebuild derived tables after a source sync."""

    if reproject_zh:
        reproject_active_chinese_sources()
    rebuild_collocations()
    select_zh_glosses()
    rebuild_chinese_glosses()
    if refresh_forms:
        validate_forms_with_rules()
