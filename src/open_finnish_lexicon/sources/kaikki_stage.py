from __future__ import annotations

import json
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech
from open_finnish_lexicon.sources.kaikki_loader import (
    has_kaikki_projection_data,
    read_kaikki_entries,
)
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    prepare_pending_source_snapshot,
)

MIN_KAIKKI_REPLACEMENT_RATIO = 0.25
LARGE_KAIKKI_SNAPSHOT_THRESHOLD = 1_000


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
        source_file_id = prepare_pending_source_snapshot(
            conn,
            name="kaikki",
            source_kind="jsonl",
            version=version,
            source_url=source_url,
            input_path=input_path,
            archive_path=archive_path,
            unpacked_path=unpacked_path,
            checksum_sha256=checksum_sha256,
        )

        conn.execute(
            """
            create temporary table tmp_kaikki_document (
                entry_order bigint primary key,
                external_id text not null,
                word text not null,
                part_of_speech text not null,
                payload jsonb not null,
                has_projection boolean not null
            ) on commit drop
            """
        )

        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_kaikki_document (
                    entry_order, external_id, word, part_of_speech, payload, has_projection
                )
                from stdin
                """
            ) as copy:
                for entry_order, entry in enumerate(
                    read_kaikki_entries(
                        input_path,
                        include_non_projection_entries=True,
                        reject_corrupt_stream=reject_empty_snapshot,
                    ),
                    start=1,
                ):
                    part_of_speech = normalize_part_of_speech(entry["pos"])
                    external_id = f"kaikki:{entry['word']}:{part_of_speech}"
                    copy.write_row(
                        (
                            entry_order,
                            external_id,
                            entry["word"],
                            part_of_speech,
                            json.dumps(entry, ensure_ascii=False),
                            has_kaikki_projection_data(entry),
                        )
                    )

            if reject_empty_snapshot:
                projected_row = cursor.execute(
                    "select count(*) from tmp_kaikki_document where has_projection"
                ).fetchone()
                projected_count = int(projected_row[0] or 0) if projected_row else 0
                if projected_count == 0:
                    raise RuntimeError(
                        "refusing to replace Kaikki source with an empty projected snapshot"
                    )
                existing_row = cursor.execute(
                    """
                    select count(*)
                    from warehouse.source_document d
                    join warehouse.source_file sf on sf.id = d.source_file_id
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'kaikki'
                      and sf.snapshot_state = 'active'
                      and d.projection_eligible
                    """
                ).fetchone()
                existing_count = int(existing_row[0] or 0) if existing_row else 0
                if (
                    existing_count >= LARGE_KAIKKI_SNAPSHOT_THRESHOLD
                    and projected_count < existing_count * MIN_KAIKKI_REPLACEMENT_RATIO
                ):
                    raise RuntimeError(
                        f"refusing truncated Kaikki snapshot: {projected_count} projected entries "
                        f"vs {existing_count} active entries"
                    )

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
                        word,
                        part_of_speech,
                        payload,
                        case
                            when count(*) over (partition by external_id) = 1 then external_id
                            else external_id || ':entry-' || entry_order::text
                        end as document_external_id
                    from tmp_kaikki_document
                ),
                resolved_docs as (
                    select
                        d.id as source_document_id,
                        keys.entry_order,
                        keys.document_external_id,
                        keys.word,
                        keys.part_of_speech,
                        keys.payload
                    from document_keys keys
                    join warehouse.source_document d
                      on d.source_file_id = %s
                     and d.external_id = keys.document_external_id
                )
                select
                    rd.source_document_id,
                    'lemma',
                    rd.word,
                    null,
                    jsonb_build_object('part_of_speech', rd.part_of_speech)
                from resolved_docs rd
                union all
                select
                    rd.source_document_id,
                    'sense',
                    rd.document_external_id,
                    sense.item->>'id',
                    jsonb_build_object(
                        'glosses',
                        coalesce(sense.item->'glosses', '[]'::jsonb)
                    )
                from resolved_docs rd
                cross join lateral jsonb_array_elements(
                    coalesce(rd.payload->'senses', '[]'::jsonb)
                ) sense(item)
                where btrim(coalesce(sense.item->>'id', '')) <> ''
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
