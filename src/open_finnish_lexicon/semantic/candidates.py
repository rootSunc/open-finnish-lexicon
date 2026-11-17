from __future__ import annotations

from psycopg.types.json import Jsonb

from open_finnish_lexicon.confidence import normalize_confidence_score


def upsert_sense_alignment_candidate(
    conn,
    *,
    source_name: str,
    source_document_id: int,
    target_sense_id: int,
    candidate_kind: str,
    confidence_score: float,
    match_payload: dict,
) -> int:
    normalized_confidence = normalize_confidence_score(confidence_score)
    return conn.execute(
        """
        insert into semantic.sense_alignment_candidate (
            source_name,
            source_document_id,
            target_sense_id,
            candidate_kind,
            confidence_score,
            match_payload
        )
        values (%s, %s, %s, %s, %s, %s)
        on conflict (source_name, source_document_id, target_sense_id, candidate_kind)
        do update set
            confidence_score = excluded.confidence_score,
            match_payload = excluded.match_payload
        returning id
        """,
        (
            source_name,
            source_document_id,
            target_sense_id,
            candidate_kind,
            normalized_confidence,
            Jsonb(match_payload),
        ),
    ).fetchone()[0]


def upsert_zh_gloss_candidate(
    conn,
    *,
    target_sense_id: int,
    source_name: str,
    source_document_id: int,
    gloss_zh: str,
    confidence_score: float,
    candidate_payload: dict,
) -> int:
    normalized_confidence = normalize_confidence_score(confidence_score)
    return conn.execute(
        """
        insert into semantic.zh_gloss_candidate (
            target_sense_id,
            source_name,
            source_document_id,
            gloss_zh,
            confidence_score,
            candidate_payload
        )
        values (%s, %s, %s, %s, %s, %s)
        on conflict (target_sense_id, source_name, source_document_id, gloss_zh)
        do update set
            confidence_score = excluded.confidence_score,
            candidate_payload = excluded.candidate_payload
        returning id
        """,
        (
            target_sense_id,
            source_name,
            source_document_id,
            gloss_zh,
            normalized_confidence,
            Jsonb(candidate_payload),
        ),
    ).fetchone()[0]
