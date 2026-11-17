from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys

from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connect, connection_scope
from open_finnish_lexicon.enrich.zh import rebuild_chinese_glosses, select_zh_glosses
from open_finnish_lexicon.morphology.validator import validate_forms_with_rules
from open_finnish_lexicon.normalize.collocations import rebuild_collocations
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
from open_finnish_lexicon.sources.tatoeba_project import project_tatoeba_rows
from open_finnish_lexicon.sources.tatoeba_stage import stage_tatoeba_rows
from open_finnish_lexicon.sources.wiktionary_zh_project import project_wiktionary_zh_rows
from open_finnish_lexicon.sources.wiktionary_zh_stage import stage_wiktionary_zh_rows
from open_finnish_lexicon.sources.warehouse import (
    clear_retired_source_registry_documents_in_batches,
    finalize_source_registry_snapshot,
)

StageFn = Callable[..., int]
ProjectFn = Callable[..., int]


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
    }
)


def get_source_pipeline(source_name: str) -> SourcePipeline:
    pipelines = {
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
    }
    return pipelines[source_name]


FIXTURE_INPUTS: tuple[tuple[str, Path], ...] = (
    ("omorfi", Path("tests/fixtures/omorfi.tsv")),
    ("kaikki", Path("tests/fixtures/kaikki-juosta.jsonl")),
    ("finnwordnet", Path("tests/fixtures/finnwordnet.tsv")),
    ("tatoeba", Path("tests/fixtures/tatoeba.tsv")),
    ("frequency", Path("tests/fixtures/frequency.csv")),
    ("wiktionary_zh", Path("tests/fixtures/wiktionary-zh-fixture.jsonl")),
    ("dbnary_zh", Path("tests/fixtures/dbnary-zh-exolex.ttl")),
)

SYNC_SOURCE_ORDER = (
    "kaikki",
    "omorfi",
    "tatoeba",
    "frequency",
    "finnwordnet",
    "dbnary_zh",
    "wiktionary_zh",
)

CHINESE_CANDIDATE_SOURCES = {"wiktionary_zh", "dbnary_zh"}


def _is_fixture_input_path(input_path: Path) -> bool:
    """Recognize repository fixture paths before they can enter the real DB."""

    parts = {part.casefold() for part in input_path.resolve().parts}
    return any(part == "fixtures" or part.startswith("fixture-") for part in parts)


def _assert_manual_ingest_profile(input_path: Path) -> None:
    """Keep fixture data out of a real-profile database.

    Manual ingest is intentionally still available for real source snapshots,
    but a common typo is running an ``ingest-*`` command with a test fixture
    while OFL_PROFILE is real.  That can replace a source's
    provenance and, for full-replacement sources such as frequency, its live
    data.  Fail before the stage function opens a write transaction.
    """

    settings = get_pipeline_settings()
    if settings.data_profile == "real" and _is_fixture_input_path(input_path):
        raise RuntimeError(
            "manual ingest refuses fixture input while OFL_PROFILE=real; "
            "use OFL_PROFILE=fixture for test data"
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

    # Publish the replacement snapshot before deleting retired warehouse rows.
    # Large real-world sources can have millions of dependent claims; cleanup
    # must not keep a valid new snapshot invisible for the duration of that
    # maintenance transaction.
    try:
        with connect() as cleanup_conn:
            source_registry_id = cleanup_conn.execute(
                "select id from warehouse.source_registry where name = %s",
                (source_name,),
            ).fetchone()[0]
        clear_retired_source_registry_documents_in_batches(
            source_registry_id=source_registry_id,
        )
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
    connection=None,
) -> None:
    """Activate the successfully projected file and retire older release paths."""

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        if source_file_id is None:
            row = conn.execute(
                """
                select sf.id, sf.source_registry_id
                from warehouse.source_file sf
                join warehouse.source_registry sr on sr.id = sf.source_registry_id
                where sr.name = %s
                  and sf.local_path = %s
                  and sf.snapshot_state = 'pending'
                order by sf.imported_at desc, sf.id desc
                limit 1
                """,
                (source_name, str(input_path)),
            ).fetchone()
        else:
            row = conn.execute(
                """
                select sf.id, sf.source_registry_id
                from warehouse.source_file sf
                join warehouse.source_registry sr on sr.id = sf.source_registry_id
                where sr.name = %s
                  and sf.local_path = %s
                  and sf.id = %s
                  and sf.snapshot_state = 'pending'
                """,
                (source_name, str(input_path), source_file_id),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"source file is not staged: {source_name} {input_path}")
        source_file_id, source_registry_id = row
        finalize_source_registry_snapshot(
            conn,
            source_registry_id=source_registry_id,
            active_source_file_id=source_file_id,
            cleanup_superseded_documents=cleanup_superseded_documents,
        )
        if owns_connection:
            conn.commit()


def refresh_runtime_views(*, refresh_forms: bool = True) -> None:
    """Rebuild derived tables after a source sync.

    ``refresh_forms`` re-runs rule-based form validation, which scans every
    ``lexicon.form`` row. Skip it when only examples or glosses changed.
    """

    rebuild_collocations()
    select_zh_glosses()
    rebuild_chinese_glosses()
    if refresh_forms:
        validate_forms_with_rules()
