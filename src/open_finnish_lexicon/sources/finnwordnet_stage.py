import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.finnwordnet_loader import (
    iter_finnwordnet_relations,
    iter_finnwordnet_word_senses,
)
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    upsert_source_file,
    upsert_source_registry,
    upsert_source_release,
)


def stage_finnwordnet_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    word_senses = list(iter_finnwordnet_word_senses(input_path))
    relations = list(iter_finnwordnet_relations(input_path))
    if not word_senses and not relations:
        raise ValueError("FinnWordNet input contains no rows; refusing to replace existing relations")

    with connect() as conn:
        source_registry_id = upsert_source_registry(
            conn,
            name="finnwordnet",
            source_kind="tsv",
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
            create temporary table tmp_finnwordnet_stage (
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
                copy tmp_finnwordnet_stage (
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
                for index, row in enumerate(word_senses, start=1):
                    payload = {
                        "kind": "wsense",
                        "synset_id": row.synset_id,
                        "word": row.word,
                        "part_of_speech": row.part_of_speech,
                    }
                    copy.write_row(
                        (
                            f"finnwordnet:wsense:{index}",
                            json.dumps(payload, ensure_ascii=False),
                            "synset-member",
                            row.synset_id,
                            row.word,
                            json.dumps({"part_of_speech": row.part_of_speech}, ensure_ascii=False),
                        )
                    )

                offset = len(word_senses)
                for index, row in enumerate(relations, start=1):
                    payload = {
                        "kind": "lexrel",
                        "source_lemma": row.source_lemma,
                        "source_pos": row.source_pos,
                        "target_lemma": row.target_lemma,
                        "target_pos": row.target_pos,
                        "relation_type": row.relation_type,
                    }
                    copy.write_row(
                        (
                            f"finnwordnet:lexrel:{offset + index}",
                            json.dumps(payload, ensure_ascii=False),
                            "relation",
                            row.source_lemma,
                            row.target_lemma,
                            json.dumps(
                                {
                                    "source_pos": row.source_pos,
                                    "target_pos": row.target_pos,
                                    "relation_type": row.relation_type,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )

            cursor.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                select %s, external_id, payload
                from tmp_finnwordnet_stage
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
                join tmp_finnwordnet_stage t on t.external_id = d.external_id
                where d.source_file_id = %s
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
