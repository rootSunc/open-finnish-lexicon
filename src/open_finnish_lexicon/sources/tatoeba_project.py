from __future__ import annotations

from pathlib import Path
import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.tatoeba_loader import TatoebaEntry, ingest_tatoeba
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path


def project_tatoeba_rows(
    input_path: Path,
    *,
    source_file_id: int | None = None,
    connection: psycopg.Connection | None = None,
    **_kwargs: object,
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        resolved_file_id = source_file_id_for_path(
            conn,
            source_name="tatoeba",
            local_path=input_path,
            source_file_id=source_file_id,
            allow_active=source_file_id is not None,
        )
        kind_row = conn.execute(
            """
            select sr.source_kind
            from warehouse.source_file sf
            join warehouse.source_registry sr on sr.id = sf.source_registry_id
            where sf.id = %s
            """,
            (resolved_file_id,),
        ).fetchone()
        source_kind = str(kind_row[0]) if kind_row else "tsv"
        staged_entries: list[TatoebaEntry] = []
        for external_id, payload in conn.execute(
            """
            select external_id, payload
            from warehouse.source_document
            where source_file_id = %s
            order by id
            """,
            (resolved_file_id,),
        ).fetchall():
            if not isinstance(payload, dict):
                continue
            text_fi = payload.get("text_fi")
            if not isinstance(text_fi, str) or not text_fi.strip():
                continue
            source_external_id = str(payload.get("source_external_id") or external_id or "")
            sentence_id = (
                None
                if source_kind == "tsv"
                else source_external_id.removeprefix("tatoeba:") or None
            )
            staged_entries.append(
                TatoebaEntry(
                    external_id=source_external_id,
                    sentence_id=sentence_id,
                    text_fi=text_fi,
                    quality_score=float(payload.get("quality") or 0.0),
                    text_en=(
                        payload["text_en"]
                        if isinstance(payload.get("text_en"), str)
                        else None
                    ),
                    text_zh=(
                        payload["text_zh"]
                        if isinstance(payload.get("text_zh"), str)
                        else None
                    ),
                    sense_key=(
                        payload["sense_key"]
                        if isinstance(payload.get("sense_key"), str)
                        else None
                    ),
                    username=(
                        payload["username"]
                        if isinstance(payload.get("username"), str)
                        else None
                    ),
                    created_at=(
                        payload["created_at"]
                        if isinstance(payload.get("created_at"), str)
                        else None
                    ),
                    updated_at=(
                        payload["updated_at"]
                        if isinstance(payload.get("updated_at"), str)
                        else None
                    ),
                )
            )
        ingest_tatoeba(input_path, entries=staged_entries, connection=conn)
        if owns_connection:
            conn.commit()
    return resolved_file_id
