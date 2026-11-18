from __future__ import annotations

from itertools import chain
import json
from pathlib import Path
import re
import unicodedata

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.dbnary_zh_loader import read_dbnary_zh_candidates
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    prepare_pending_source_snapshot,
)


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    normalized = "".join(char if char.isalnum() else " " for char in without_marks)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalized_gloss_variants(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    variants = [value, *re.split(r"\s*;\s*", value)]
    return {normalized for variant in variants if (normalized := _normalize_text(variant))}


def _find_enhancement_path(base_dir: Path) -> Path:
    for candidate in (
        "fi_dbnary_enhancement.ttl",
        "en_dbnary_enhancement.ttl",
        "dbnary-zh-enhancement.ttl",
    ):
        path = base_dir / candidate
        if path.exists():
            return path
    raise FileNotFoundError("dbnary enhancement TTL not found")


def stage_dbnary_zh_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    base_dir = unpacked_path or input_path.parent
    enhancement_path = _find_enhancement_path(base_dir)
    entries = iter(read_dbnary_zh_candidates(input_path, enhancement_path))
    first_entry = next(entries, None)
    if first_entry is None:
        raise ValueError(
            "DBnary-zh input contains no valid Chinese candidates; refusing to replace existing data"
        )

    with connect() as conn:
        source_file_id = prepare_pending_source_snapshot(
            conn,
            name="dbnary_zh",
            source_kind="ttl",
            version=version,
            source_url=source_url,
            input_path=input_path,
            archive_path=archive_path,
            unpacked_path=base_dir,
            checksum_sha256=checksum_sha256,
        )
        clear_source_file_documents(conn, source_file_id=source_file_id)
        conn.execute(
            """
            create temporary table tmp_dbnary_zh_stage (
                external_id text not null,
                lemma text not null,
                payload jsonb not null
            ) on commit drop
            """
        )
        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_dbnary_zh_stage (external_id, lemma, payload)
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
                from tmp_dbnary_zh_stage
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
                select d.id, 'dbnary_zh_entry', t.lemma, null, t.payload
                from warehouse.source_document d
                join tmp_dbnary_zh_stage t on t.external_id = d.external_id
                where d.source_file_id = %s
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
