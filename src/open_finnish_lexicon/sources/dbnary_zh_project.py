from __future__ import annotations

from pathlib import Path
import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.semantic.candidates import (
    upsert_sense_alignment_candidate,
    upsert_zh_gloss_candidate,
)
from open_finnish_lexicon.sources.dbnary_zh_stage import _normalized_gloss_variants
from open_finnish_lexicon.sources.warehouse import (
    replace_source_claims,
    source_file_id_for_path,
)
from open_finnish_lexicon.zh_script import to_simplified_chinese


def project_dbnary_zh_rows(
    input_path: Path,
    *,
    source_file_id: int | None = None,
    connection: psycopg.Connection | None = None,
    **_kwargs: object,
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        resolved_file_id = source_file_id_for_path(
            conn,
            source_name="dbnary_zh",
            local_path=input_path,
            source_file_id=source_file_id,
            allow_active=source_file_id is not None,
        )
        conn.execute(
            """
            delete from semantic.sense_alignment_candidate
            where source_document_id in (
                select id from warehouse.source_document where source_file_id = %s
            )
            """,
            (resolved_file_id,),
        )
        conn.execute(
            """
            delete from semantic.zh_gloss_candidate c
            where c.source_document_id in (
                select id from warehouse.source_document where source_file_id = %s
            )
              and not exists (
                  select 1
                  from semantic.zh_gloss_selection sel
                  where sel.zh_gloss_candidate_id = c.id
              )
            """,
            (resolved_file_id,),
        )
        documents = conn.execute(
            """
            select id, payload
            from warehouse.source_document
            where source_file_id = %s
            order by id
            """,
            (resolved_file_id,),
        ).fetchall()

        for source_document_id, entry in documents:
            if not isinstance(entry, dict):
                continue
            lemma = str(entry.get("lemma", ""))
            part_of_speech = str(entry.get("part_of_speech", ""))
            claims: list[tuple[str, str, str | None, dict[str, object]]] = [
                ("dbnary_zh_entry", lemma, None, entry)
            ]

            sense_rows = conn.execute(
                """
                select ls.id, ls.sense_key, ls.gloss_en, ls.gloss_fi,
                       ('form-of' = any(ls.labels)) as is_form_of
                from lexicon.lexeme lx
                join lexicon.lexeme_sense ls on ls.lexeme_id = lx.id
                where lx.lemma = %s and lx.part_of_speech = %s
                order by ls.sort_order, ls.id
                """,
                (lemma, part_of_speech),
            ).fetchall()
            canonical_senses = [row[:4] for row in sense_rows if not row[4]]
            candidate_senses = canonical_senses or [row[:4] for row in sense_rows]

            source_gloss_en = entry.get("gloss_en")
            source_gloss_fi = entry.get("gloss_fi")
            source_en_variants = _normalized_gloss_variants(source_gloss_en)
            source_fi_variants = _normalized_gloss_variants(source_gloss_fi)
            matching = [
                (int(sense_id), str(sense_key))
                for sense_id, sense_key, gloss_en, gloss_fi in candidate_senses
                if (
                    source_en_variants
                    and source_en_variants & _normalized_gloss_variants(gloss_en)
                )
                or (
                    source_fi_variants
                    and source_fi_variants & _normalized_gloss_variants(gloss_fi)
                )
            ]
            candidate_kind = "exact_gloss"
            confidence_score = 0.88
            if len(matching) != 1:
                sense_index = int(entry.get("sense_index", -1))
                source_sense_count = int(entry.get("source_sense_count", -1))
                if source_sense_count == 1 and len(candidate_senses) == 1:
                    sense_id, sense_key, _gloss_en, _gloss_fi = candidate_senses[0]
                    matching = [(int(sense_id), str(sense_key))]
                    candidate_kind = "single_sense"
                    confidence_score = 0.85
                elif source_sense_count == len(candidate_senses) and 0 <= sense_index < len(
                    candidate_senses
                ):
                    sense_id, sense_key, _gloss_en, _gloss_fi = candidate_senses[sense_index]
                    matching = [(int(sense_id), str(sense_key))]
                    candidate_kind = "ordered_sense"
                    confidence_score = 0.78
                elif source_sense_count == 1 and len(candidate_senses) > 1:
                    sense_id, sense_key, _gloss_en, _gloss_fi = candidate_senses[0]
                    matching = [(int(sense_id), str(sense_key))]
                    candidate_kind = "primary_sense"
                    confidence_score = 0.75
                else:
                    replace_source_claims(
                        conn, source_document_id=int(source_document_id), claims=claims
                    )
                    continue

            sense_id, sense_key = matching[0]
            raw_terms = entry.get("zh_terms") or []
            converted_terms = list(
                dict.fromkeys(
                    to_simplified_chinese(str(term).strip())
                    for term in raw_terms
                    if str(term).strip()
                )
            )
            if not converted_terms:
                replace_source_claims(
                    conn, source_document_id=int(source_document_id), claims=claims
                )
                continue

            gloss_zh = "；".join(converted_terms)
            upsert_sense_alignment_candidate(
                conn,
                source_name="dbnary_zh",
                source_document_id=int(source_document_id),
                target_sense_id=sense_id,
                candidate_kind=candidate_kind,
                confidence_score=confidence_score,
                match_payload={
                    "sense_key": sense_key,
                    "lemma": lemma,
                    "part_of_speech": part_of_speech,
                    "source_gloss_en": source_gloss_en,
                    "source_gloss_fi": source_gloss_fi,
                    "source_gloss_language": entry.get("source_gloss_language"),
                    "source_gloss": entry.get("source_gloss"),
                    "sense_index": entry.get("sense_index"),
                    "match_kind": candidate_kind,
                },
            )
            candidate_id = upsert_zh_gloss_candidate(
                conn,
                target_sense_id=sense_id,
                source_name="dbnary_zh",
                source_document_id=int(source_document_id),
                gloss_zh=gloss_zh,
                confidence_score=confidence_score,
                candidate_payload={
                    "sense_key": sense_key,
                    "lemma": lemma,
                    "part_of_speech": part_of_speech,
                    "source_gloss_en": source_gloss_en,
                    "source_gloss_fi": source_gloss_fi,
                    "source_gloss_language": entry.get("source_gloss_language"),
                    "source_gloss": entry.get("source_gloss"),
                    "sense_index": entry.get("sense_index"),
                    "match_kind": candidate_kind,
                    "requires_llm_review": False,
                },
            )
            claims.append(
                (
                    "zh_gloss_candidate",
                    sense_key,
                    None,
                    {"candidate_id": candidate_id, "gloss_zh": gloss_zh},
                )
            )
            replace_source_claims(conn, source_document_id=int(source_document_id), claims=claims)

        if owns_connection:
            conn.commit()
    return resolved_file_id
