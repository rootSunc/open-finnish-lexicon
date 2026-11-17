import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.tatoeba_loader import (
    get_tatoeba_source_kind,
    iter_tatoeba_entries,
    load_tatoeba_translations,
)
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    upsert_source_file,
    upsert_source_registry,
    upsert_source_release,
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
    if next(iter_tatoeba_entries(input_path), None) is None:
        raise ValueError("Tatoeba input contains no valid Finnish entries; refusing to replace existing examples")
    with connect() as conn:
        source_registry_id = upsert_source_registry(
            conn,
            name="tatoeba",
            source_kind=source_kind,
            version=version,
            source_url=source_url,
            defer_activation=True,
        )
        upsert_source_release(
            conn,
            source_registry_id=source_registry_id,
            version=version,
            source_url=source_url,
            archive_path=archive_path or input_path,
            unpacked_path=unpacked_path or input_path.parent,
            checksum_sha256=checksum_sha256,
        )
        source_file_id = upsert_source_file(
            conn,
            source_registry_id=source_registry_id,
            local_path=input_path,
            checksum_sha256=checksum_sha256,
            snapshot_state="pending",
            source_version=version,
            source_url=source_url,
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

        sentence_ids = {
            entry.sentence_id
            for entry in iter_tatoeba_entries(input_path)
            if entry.sentence_id is not None
        }
        translations_by_sentence_id = load_tatoeba_translations(input_path, sentence_ids)

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
                for index, entry in enumerate(iter_tatoeba_entries(input_path), start=1):
                    translation_entry = translations_by_sentence_id.get(entry.sentence_id or "", {})
                    text_zh = entry.text_zh or translation_entry.get("zh")
                    text_en = entry.text_en or translation_entry.get("en")
                    payload = {
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

                    claim_type = "example"
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
                            claim_type,
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
