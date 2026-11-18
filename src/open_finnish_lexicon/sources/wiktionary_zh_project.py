from __future__ import annotations

from pathlib import Path
import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.semantic.candidates import (
    upsert_sense_alignment_candidate,
    upsert_zh_gloss_candidate,
)
from open_finnish_lexicon.sources.warehouse import (
    replace_source_claims,
    source_file_id_for_path,
)
from open_finnish_lexicon.zh_script import non_learner_zh_gloss_detail, to_simplified_chinese


def _clean_sense_gloss_groups(raw_groups: object) -> list[str]:
    if not isinstance(raw_groups, list):
        return []
    joined_groups: list[str] = []
    for group in raw_groups:
        if not isinstance(group, list):
            continue
        cleaned = [
            to_simplified_chinese(item.strip())
            for item in group
            if isinstance(item, str) and item.strip()
        ]
        if cleaned:
            joined_groups.append("；".join(dict.fromkeys(cleaned)))
    return joined_groups


def _align_sense_pairs(
    local_senses: list[tuple[int, str]],
    sense_glosses: list[str],
) -> list[tuple[int, str, str, float, str, int]]:
    if not local_senses or not sense_glosses:
        return []

    if len(local_senses) == len(sense_glosses):
        score = 0.95 if len(local_senses) == 1 else 0.82
        return [
            (sense_id, sense_key, sense_glosses[idx], score, "ordered_sense", idx)
            for idx, (sense_id, sense_key) in enumerate(local_senses)
        ]

    # Strip dictionary-metadata slots (such as inflection notes) and retry exact count match.
    learner_glosses = [
        gloss for gloss in sense_glosses if non_learner_zh_gloss_detail(gloss) is None
    ]
    if not learner_glosses:
        return []

    if len(local_senses) == len(learner_glosses):
        score = 0.93 if len(local_senses) == 1 else 0.80
        return [
            (sense_id, sense_key, learner_glosses[idx], score, "ordered_sense", idx)
            for idx, (sense_id, sense_key) in enumerate(local_senses)
        ]

    if len(local_senses) == 1:
        sense_id, sense_key = local_senses[0]
        combined = "；".join(dict.fromkeys(learner_glosses))
        return [(sense_id, sense_key, combined, 0.84, "single_target_sense", 0)]

    if len(learner_glosses) == 1:
        sense_id, sense_key = local_senses[0]
        return [(sense_id, sense_key, learner_glosses[0], 0.80, "primary_sense", 0)]

    return []


def project_wiktionary_zh_rows(
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
            source_name="wiktionary_zh",
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

        for source_document_id, payload in documents:
            if not isinstance(payload, dict):
                continue
            lemma = str(payload.get("lemma", ""))
            part_of_speech = str(payload.get("part_of_speech", ""))
            claims: list[tuple[str, str, str | None, dict[str, object]]] = [
                ("wiktionary_zh_entry", lemma, None, payload)
            ]

            sense_rows = conn.execute(
                """
                select ls.id, ls.sense_key, ('form-of' = any(ls.labels)) as is_form_of
                from lexicon.lexeme lx
                join lexicon.lexeme_sense ls on ls.lexeme_id = lx.id
                where lx.lemma = %s and lx.part_of_speech = %s
                order by ls.sort_order, ls.id
                """,
                (lemma, part_of_speech),
            ).fetchall()
            canonical_senses = [
                (int(sense_id), str(sense_key))
                for sense_id, sense_key, is_form_of in sense_rows
                if not is_form_of
            ]
            local_senses = canonical_senses or [
                (int(sense_id), str(sense_key))
                for sense_id, sense_key, _is_form_of in sense_rows
            ]

            sense_glosses = _clean_sense_gloss_groups(payload.get("sense_glosses"))
            alignments = _align_sense_pairs(local_senses, sense_glosses)
            for sense_id, sense_key, gloss_zh, confidence_score, kind, index in alignments:
                upsert_sense_alignment_candidate(
                    conn,
                    source_name="wiktionary_zh",
                    source_document_id=int(source_document_id),
                    target_sense_id=sense_id,
                    candidate_kind=kind,
                    confidence_score=confidence_score,
                    match_payload={
                        "sense_key": sense_key,
                        "lemma": lemma,
                        "part_of_speech": part_of_speech,
                        "sense_index": index,
                    },
                )
                candidate_id = upsert_zh_gloss_candidate(
                    conn,
                    target_sense_id=sense_id,
                    source_name="wiktionary_zh",
                    source_document_id=int(source_document_id),
                    gloss_zh=gloss_zh,
                    confidence_score=confidence_score,
                    candidate_payload={
                        "sense_key": sense_key,
                        "lemma": lemma,
                        "part_of_speech": part_of_speech,
                        "sense_index": index,
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
