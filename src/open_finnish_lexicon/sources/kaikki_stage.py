import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech
from open_finnish_lexicon.sources.kaikki_loader import has_kaikki_projection_data, read_kaikki_entries
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    upsert_source_file,
    upsert_source_registry,
    upsert_source_release,
)


def stage_kaikki_entries(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
    reject_empty_snapshot: bool = False,
) -> int:
    with connect() as conn:
        source_registry_id = upsert_source_registry(
            conn,
            name="kaikki",
            source_kind="jsonl",
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
            create temporary table tmp_kaikki_document (
                entry_order bigint not null,
                external_id text not null,
                payload jsonb not null,
                has_projection boolean not null
            ) on commit drop
            """
        )
        conn.execute(
            """
            create temporary table tmp_kaikki_claim (
                entry_order bigint not null,
                external_id text not null,
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
                copy tmp_kaikki_document (entry_order, external_id, payload, has_projection)
                from stdin
                """
            ) as copy:
                for entry_order, entry in enumerate(read_kaikki_entries(
                    input_path, include_non_projection_entries=True
                ), start=1):
                    part_of_speech = normalize_part_of_speech(entry["pos"])
                    external_id = f"kaikki:{entry['word']}:{part_of_speech}"
                    copy.write_row(
                        (
                            entry_order,
                            external_id,
                            json.dumps(entry, ensure_ascii=False),
                            has_kaikki_projection_data(entry),
                        )
                    )

            with cursor.copy(
                """
                copy tmp_kaikki_claim (
                    entry_order,
                    external_id,
                    claim_type,
                    subject_key,
                    object_key,
                    claim_payload
                )
                from stdin
                """
            ) as copy:
                for entry_order, entry in enumerate(read_kaikki_entries(
                    input_path, include_non_projection_entries=True
                ), start=1):
                    part_of_speech = normalize_part_of_speech(entry["pos"])
                    external_id = f"kaikki:{entry['word']}:{part_of_speech}"
                    copy.write_row(
                        (
                            entry_order,
                            external_id,
                            "lemma",
                            entry["word"],
                            None,
                            json.dumps({"part_of_speech": part_of_speech}, ensure_ascii=False),
                        )
                    )
                    for sense in entry.get("senses", []):
                        copy.write_row(
                            (
                                entry_order,
                                external_id,
                                "sense",
                                external_id,
                                sense["id"],
                                json.dumps({"glosses": sense.get("glosses", [])}, ensure_ascii=False),
                            )
                        )

            if reject_empty_snapshot and not cursor.execute(
                "select exists (select 1 from tmp_kaikki_document where has_projection)"
            ).fetchone()[0]:
                raise RuntimeError("refusing to replace Kaikki source with an empty projected snapshot")

            clear_source_file_documents(conn, source_file_id=source_file_id)

            cursor.execute(
                """
                insert into warehouse.source_document (
                    source_file_id,
                    external_id,
                    payload,
                    projection_eligible
                )
                with numbered as (
                    select
                        entry_order,
                        external_id as base_external_id,
                        payload,
                        has_projection,
                        count(*) over (partition by external_id) as duplicate_count
                    from tmp_kaikki_document
                )
                select
                    %s,
                    case
                        when duplicate_count = 1 then base_external_id
                        else base_external_id || ':entry-' || entry_order::text
                    end,
                    payload,
                    has_projection
                from numbered
                order by entry_order
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
                with document_keys as (
                    select
                        entry_order,
                        external_id as base_external_id,
                        case
                            when count(*) over (partition by external_id) = 1 then external_id
                            else external_id || ':entry-' || entry_order::text
                        end as document_external_id
                    from tmp_kaikki_document
                )
                select
                    d.id,
                    t.claim_type,
                    case
                        when t.claim_type = 'sense' then keys.document_external_id
                        else t.subject_key
                    end,
                    t.object_key,
                    t.claim_payload
                from tmp_kaikki_claim t
                join document_keys keys on keys.entry_order = t.entry_order
                join warehouse.source_document d
                  on d.source_file_id = %s
                 and d.external_id = keys.document_external_id
                where t.external_id = keys.base_external_id
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
