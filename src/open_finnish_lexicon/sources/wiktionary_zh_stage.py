from __future__ import annotations

from itertools import chain
import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    prepare_pending_source_snapshot,
)
from open_finnish_lexicon.sources.wiktionary_zh_loader import read_wiktionary_zh_entries


def stage_wiktionary_zh_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    entries = read_wiktionary_zh_entries(input_path)
    first_entry = next(entries, None)
    if first_entry is None:
        raise ValueError(
            "Wiktionary-zh input contains no valid Finnish entries; refusing to replace existing data"
        )

    with connect() as conn:
        source_file_id = prepare_pending_source_snapshot(
            conn,
            name="wiktionary_zh",
            source_kind="jsonl",
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
            create temporary table tmp_wiktionary_zh_stage (
                external_id text not null,
                lemma text not null,
                payload jsonb not null
            ) on commit drop
            """
        )
        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_wiktionary_zh_stage (external_id, lemma, payload)
                from stdin
                """
            ) as copy:
                for entry in chain((first_entry,), entries):
                    copy.write_row(
                        (
                            entry["external_id"],
                            entry["lemma"],
                            json.dumps(entry, ensure_ascii=False),
                        )
                    )
            cursor.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                select %s, external_id, payload
                from tmp_wiktionary_zh_stage
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
                select d.id, 'wiktionary_zh_entry', t.lemma, null, t.payload
                from warehouse.source_document d
                join tmp_wiktionary_zh_stage t on t.external_id = d.external_id
                where d.source_file_id = %s
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
