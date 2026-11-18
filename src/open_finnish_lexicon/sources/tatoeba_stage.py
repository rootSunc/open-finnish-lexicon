from __future__ import annotations

import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.tatoeba_loader import (
    attach_tatoeba_translations,
    get_tatoeba_source_kind,
    iter_tatoeba_entries,
    load_tatoeba_translations,
)
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    prepare_pending_source_snapshot,
)


def stage_tatoeba_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    source_kind = get_tatoeba_source_kind(input_path)
    entries = list(iter_tatoeba_entries(input_path))
    if not entries:
        raise ValueError(
            "Tatoeba input contains no valid Finnish entries; refusing to replace existing examples"
        )
    sentence_ids = {entry.sentence_id for entry in entries if entry.sentence_id is not None}
    translations_by_sentence_id = load_tatoeba_translations(input_path, sentence_ids)

    with connect() as conn:
        source_file_id = prepare_pending_source_snapshot(
            conn,
            name="tatoeba",
            source_kind=source_kind,
            version=version,
            source_url=source_url,
            input_path=input_path,
            archive_path=archive_path,
            unpacked_path=unpacked_path,
            checksum_sha256=checksum_sha256,
        )
        conn.execute(
            """
            create temporary table tmp_tatoeba_stage (
                external_id text not null,
                payload jsonb not null,
                claim_type text not null,
                subject_key text not null,
                object_key text,
                claim_payload jsonb not null
            ) on commit drop
            """
        )

        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_tatoeba_stage (
                    external_id,
                    payload,
                    claim_type,
                    subject_key,
                    object_key,
                    claim_payload
                )
                from stdin
                """
            ) as copy:
                for index, raw_entry in enumerate(entries, start=1):
                    entry = attach_tatoeba_translations(
                        raw_entry, translations_by_sentence_id.get(raw_entry.sentence_id or "", {}),
                    )
                    text_zh, text_en = entry.text_zh, entry.text_en
                    payload: dict[str, object] = {
                        "source_external_id": entry.external_id,
                        "text_fi": entry.text_fi,
                        "quality": entry.quality_score,
                    }
                    if entry.sense_key:
                        payload["sense_key"] = entry.sense_key
                    if text_en:
                        payload["text_en"] = text_en
                    if text_zh:
                        payload["text_zh"] = text_zh
                    if entry.username:
                        payload["username"] = entry.username
                    if entry.created_at:
                        payload["created_at"] = entry.created_at
                    if entry.updated_at:
                        payload["updated_at"] = entry.updated_at
                    if entry.provenance:
                        payload["provenance"] = entry.provenance

                    subject_key = entry.sense_key or entry.external_id
                    claim_payload = {
                        "text_en": text_en,
                        "text_zh": text_zh,
                        "quality": entry.quality_score,
                    }
                    copy.write_row(
                        (
                            f"tatoeba:{index}",
                            json.dumps(payload, ensure_ascii=False),
                            "example",
                            subject_key,
                            entry.text_fi,
                            json.dumps(claim_payload, ensure_ascii=False),
                        )
                    )

            clear_source_file_documents(conn, source_file_id=source_file_id)

            cursor.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                select %s, external_id, payload
                from tmp_tatoeba_stage
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
                select d.id, t.claim_type, t.subject_key, t.object_key, t.claim_payload
                from warehouse.source_document d
                join tmp_tatoeba_stage t on t.external_id = d.external_id
                where d.source_file_id = %s
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
