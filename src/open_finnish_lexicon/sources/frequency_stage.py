import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.frequency_loader import get_frequency_source_kind, iter_frequency_entries
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    upsert_source_file,
    upsert_source_registry,
    upsert_source_release,
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
    entries = list(iter_frequency_entries(input_path))
    if not entries:
        raise ValueError("frequency input contains no rows; refusing to replace existing data")
    source_kind = get_frequency_source_kind(input_path)

    with connect() as conn:
        source_registry_id = upsert_source_registry(
            conn,
            name="frequency",
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

        clear_source_file_documents(conn, source_file_id=source_file_id)
        conn.execute(
            """
            create temporary table tmp_frequency_stage (
                external_id text not null,
                payload jsonb not null,
                subject_key text not null,
                claim_payload jsonb not null
            ) on commit drop
            """
        )

        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_frequency_stage (external_id, payload, subject_key, claim_payload)
                from stdin
                """
            ) as copy:
                for index, entry in enumerate(entries, start=1):
                    payload = {
                        "term": entry.term,
                        "raw_count": entry.raw_count,
                    }
                    if entry.lemma:
                        payload["lemma"] = entry.lemma
                    if entry.pos:
                        payload["pos"] = entry.pos
                    if entry.normalized_score is not None:
                        payload["normalized_score"] = entry.normalized_score

                    claim_payload = {
                        "term": entry.term,
                        "pos": entry.pos,
                        "raw_count": entry.raw_count,
                        "normalized_score": entry.normalized_score,
                    }
                    copy.write_row(
                        (
                            f"frequency:{index}",
                            json.dumps(payload, ensure_ascii=False),
                            entry.lemma or entry.term,
                            json.dumps(claim_payload, ensure_ascii=False),
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
                select d.id, 'frequency', t.subject_key, null, t.claim_payload
                from warehouse.source_document d
                join tmp_frequency_stage t on t.external_id = d.external_id
                where d.source_file_id = %s
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
