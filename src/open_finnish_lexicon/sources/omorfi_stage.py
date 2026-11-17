import json
import re
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.forms import normalize_surface_form
from open_finnish_lexicon.sources.omorfi_loader import (
    analyse_omorfi_model_rows,
    get_omorfi_source_kind,
    _is_usable_omorfi_surface,
    read_omorfi_rows,
)
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    upsert_source_file,
    upsert_source_registry,
    upsert_source_release,
)

TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)


def _tokenize_omorfi_candidates(text: str) -> list[str]:
    return [normalize_surface_form(match.group(0)) for match in TOKEN_RE.finditer(text)]


def load_omorfi_candidate_tokens(conn) -> list[str]:
    tokens: set[str] = set()
    for (lemma,) in conn.execute(
        """
        select l.lemma
        from lexicon.lexeme l
        where not exists (
            select 1
            from lexicon.form f
            where f.lexeme_id = l.id
              and f.normalized_form = lower(l.lemma)
        )
        """
    ).fetchall():
        normalized = normalize_surface_form(lemma)
        if normalized:
            tokens.add(normalized)

    for (text_fi,) in conn.execute("select text_fi from lexicon.example").fetchall():
        tokens.update(_tokenize_omorfi_candidates(text_fi))

    for (term,) in conn.execute(
        """
        select d.payload->>'term'
        from warehouse.source_document d
        join warehouse.source_file f on f.id = d.source_file_id
        join warehouse.source_registry r on r.id = f.source_registry_id
        where r.name = 'frequency'
          and f.snapshot_state = 'active'
          and d.payload ? 'term'
        """
    ).fetchall():
        if term:
            tokens.add(normalize_surface_form(term))

    return sorted(
        token
        for token in tokens
        if token and _is_usable_omorfi_surface(token)
    )


def stage_omorfi_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    source_kind = get_omorfi_source_kind(input_path)
    with connect() as conn:
        source_registry_id = upsert_source_registry(
            conn,
            name="omorfi",
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

        rows = (
            read_omorfi_rows(input_path)
            if source_kind == "tsv"
            else analyse_omorfi_model_rows(input_path, load_omorfi_candidate_tokens(conn))
        )

        conn.execute(
            """
            create temporary table tmp_omorfi_stage (
                external_id text not null,
                payload jsonb not null,
                lemma_payload jsonb not null,
                surface_payload jsonb not null
            ) on commit drop
            """
        )

        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_omorfi_stage (external_id, payload, lemma_payload, surface_payload)
                from stdin
                """
            ) as copy:
                for index, row in enumerate(rows, start=1):
                    copy.write_row(
                        (
                            f"omorfi:{index}",
                            json.dumps(
                                {
                                    "surface_form": row.surface_form,
                                    "lemma": row.lemma,
                                    "part_of_speech": row.part_of_speech,
                                    "features": row.features,
                                    "analysis_rank": row.analysis_rank,
                                    "confidence": row.confidence,
                                },
                                ensure_ascii=False,
                            ),
                            json.dumps(
                                {
                                    "part_of_speech": row.part_of_speech,
                                    "confidence": row.confidence,
                                },
                                ensure_ascii=False,
                            ),
                            json.dumps(
                                {
                                    "features": row.features,
                                    "analysis_rank": row.analysis_rank,
                                    "confidence": row.confidence,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )

            if not cursor.execute(
                "select exists (select 1 from tmp_omorfi_stage)"
            ).fetchone()[0]:
                raise ValueError("Omorfi input contains no rows; refusing to replace existing analyses")

            clear_source_file_documents(conn, source_file_id=source_file_id)

            cursor.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                select %s, external_id, payload
                from tmp_omorfi_stage
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
                select d.id, 'lemma', d.payload->>'lemma', null, s.lemma_payload
                from warehouse.source_document d
                join tmp_omorfi_stage s on s.external_id = d.external_id
                where d.source_file_id = %s
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
                select d.id, 'surface_form', d.payload->>'surface_form', d.payload->>'lemma', s.surface_payload
                from warehouse.source_document d
                join tmp_omorfi_stage s on s.external_id = d.external_id
                where d.source_file_id = %s
                """,
                (source_file_id,),
            )
        conn.commit()
    return source_file_id
