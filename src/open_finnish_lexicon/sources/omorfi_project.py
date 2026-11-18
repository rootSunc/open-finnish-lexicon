from __future__ import annotations

from pathlib import Path
import psycopg

from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.forms import upsert_omorfi_rows
from open_finnish_lexicon.sources.omorfi_loader import (
    OmorfiRow,
    find_omorfi_generation_models,
    generate_omorfi_paradigm_rows,
)
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path


def _omorfi_source_file_id(
    input_path: Path,
    source_file_id: int | None = None,
    connection: psycopg.Connection | None = None,
) -> int:
    with connection_scope(connection) as conn:
        return source_file_id_for_path(
            conn,
            source_name="omorfi",
            local_path=input_path,
            source_file_id=source_file_id,
        )


def _supplement_missing_paradigms_from_models(
    conn: psycopg.Connection, data_dir: str | Path
) -> list[OmorfiRow]:
    """Use Omorfi's generator + analyser round-trip to fill noun/adjective
    lexemes that still lack inflected forms when HFST models are installed."""

    if find_omorfi_generation_models(data_dir) is None:
        return []
    missing_lexemes = [
        (int(lex_id), str(lemma), str(pos), ())
        for lex_id, lemma, pos in conn.execute(
            """
            select l.id, l.lemma, l.part_of_speech
            from lexicon.lexeme l
            where l.is_lemma = true
              and l.part_of_speech in ('noun', 'adj')
              and not exists (
                  select 1 from lexicon.form f where f.lexeme_id = l.id
              )
            order by l.id
            """
        ).fetchall()
    ]
    if not missing_lexemes:
        return []
    generated = generate_omorfi_paradigm_rows(missing_lexemes, data_dir=data_dir)
    return [row for _lexeme_id, row in generated]


def project_omorfi_rows(
    input_path: Path,
    *,
    source_file_id: int | None = None,
    connection: psycopg.Connection | None = None,
    **_kwargs: object,
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        resolved_file_id = _omorfi_source_file_id(input_path, source_file_id, conn)
        payload_rows = conn.execute(
            """
            select d.payload
            from warehouse.source_document d
            where d.source_file_id = %s
            order by d.id
            """,
            (resolved_file_id,),
        ).fetchall()

        rows = [
            OmorfiRow(
                surface_form=str(payload["surface_form"]),
                lemma=str(payload["lemma"]),
                part_of_speech=str(payload["part_of_speech"]),
                features=dict(payload["features"]),
                analysis_rank=int(payload.get("analysis_rank", 1)),
                confidence=float(payload.get("confidence", 1.0)),
            )
            for (payload,) in payload_rows
            if isinstance(payload, dict)
        ]
        if input_path.suffix == ".hfst":
            rows.extend(
                _supplement_missing_paradigms_from_models(
                    conn, get_pipeline_settings().data_dir
                )
            )

        upsert_omorfi_rows(
            rows,
            source_file_id=resolved_file_id,
            replace_snapshot=True,
            connection=conn,
        )
        if owns_connection:
            conn.commit()
    return resolved_file_id
