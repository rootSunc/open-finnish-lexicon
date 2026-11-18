from __future__ import annotations

from itertools import chain
import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.frequency_loader import (
    get_frequency_source_kind,
    iter_frequency_entries,
)
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    prepare_pending_source_snapshot,
)


def stage_frequency_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    entries = iter(iter_frequency_entries(input_path))
    first_entry = next(entries, None)
    if first_entry is None:
        raise ValueError("frequency input contains no rows; refusing to replace existing data")
    source_kind = get_frequency_source_kind(input_path)

    with connect() as conn:
        source_file_id = prepare_pending_source_snapshot(
            conn,
            name="frequency",
            source_kind=source_kind,
            version=version,
            source_url=source_url,
            input_path=input_path,
            archive_path=archive_path,
            unpacked_path=unpacked_path,
            checksum_sha256=checksum_sha256,
        )
        clear_source_file_documents(conn, source_file_id=source_file_id)
        conn.execute(
            """
            create temporary table tmp_frequency_stage (
                external_id text not null,
                term text not null,
                payload jsonb not null
            ) on commit drop
            """
        )

        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_frequency_stage (external_id, term, payload)
                from stdin
                """
            ) as copy:
                for index, entry in enumerate(chain((first_entry,), entries), start=1):
                    payload = {
                        "term": entry.term,
                        "raw_count": entry.raw_count,
                        "lemma": entry.lemma,
                        "pos": entry.pos,
                        "normalized_score": entry.normalized_score,
                    }
                    copy.write_row(
                        (
                            f"frequency:{index}:{entry.term}",
                            entry.term,
                            json.dumps(payload, ensure_ascii=False),
                        )
                    )

            cursor.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                select %s, external_id, payload
                from tmp_frequency_stage
                """,
                (source_file_id,),
            )
            cursor.execute(
                """
                insert into warehouse.source_claim (
                    source_document_id,
                    claim_type,
                    subject_key,
                    object_key,
                    payload
                )
                select d.id, 'frequency', t.term, null, t.payload
                from warehouse.source_document d
                join tmp_frequency_stage t on t.external_id = d.external_id
                where d.source_file_id = %s
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
