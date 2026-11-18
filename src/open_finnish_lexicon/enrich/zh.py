"""Build the Chinese layer from source candidates.

Candidates come from the Chinese Wiktionary and DBnary sources
(``semantic.zh_gloss_candidate``). Selection is deterministic: per sense, the
highest-confidence candidate that meets its source threshold and passes the
Simplified Chinese check (after Traditional-to-Simplified conversion) wins.
"""

from __future__ import annotations

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.zh_script import (
    normalize_and_validate_zh_gloss,
    normalize_and_validate_zh_sentence,
)

DEFAULT_ACCEPT_THRESHOLD = 0.88
SOURCE_ACCEPT_THRESHOLDS = {
    "wiktionary_zh": 0.78,
    "dbnary_zh": 0.75,
}
SELECTION_REASON = "rule confidence threshold met"


def _pick_candidate(rows, *, default_threshold: float) -> tuple[int, str, float] | None:
    """Return the first acceptable row; ``rows`` are ordered best-first."""

    for candidate_id, source_name, gloss_zh, confidence_score, payload in rows:
        threshold = SOURCE_ACCEPT_THRESHOLDS.get(source_name, default_threshold)
        if (payload or {}).get("requires_llm_review"):
            continue
        if float(confidence_score) < threshold:
            continue
        normalized_zh = normalize_and_validate_zh_gloss(gloss_zh)
        if normalized_zh is not None:
            return int(candidate_id), normalized_zh, float(confidence_score)
    return None


def select_zh_glosses(*, default_threshold: float = DEFAULT_ACCEPT_THRESHOLD) -> int:
    """Rebuild ``semantic.zh_gloss_selection`` from active candidates."""

    with connect() as conn:
        rows = conn.execute(
            """
            select candidate.target_sense_id,
                   candidate.id,
                   candidate.source_name,
                   candidate.gloss_zh,
                   candidate.confidence_score,
                   candidate.candidate_payload
            from semantic.zh_gloss_candidate candidate
            join warehouse.source_document document
              on document.id = candidate.source_document_id
            join warehouse.source_file file on file.id = document.source_file_id
            where file.snapshot_state = 'active'
            order by candidate.target_sense_id, candidate.confidence_score desc, candidate.id
            """
        ).fetchall()
        by_sense: dict[int, list[tuple]] = {}
        for sense_id, *candidate in rows:
            by_sense.setdefault(int(sense_id), []).append(tuple(candidate))

        selections: list[tuple[int, int, str, float]] = []
        for sense_id, candidates in by_sense.items():
            picked = _pick_candidate(candidates, default_threshold=default_threshold)
            if picked is not None:
                candidate_id, gloss_zh, score = picked
                selections.append((sense_id, candidate_id, gloss_zh, score))

        conn.execute("delete from semantic.zh_gloss_selection")
        if selections:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into semantic.zh_gloss_selection (
                        target_sense_id, zh_gloss_candidate_id, gloss_zh,
                        selected_by, confidence_score, selection_reason
                    )
                    values (%s, %s, %s, 'rule', %s, %s)
                    """,
                    [(*row, SELECTION_REASON) for row in selections],
                )
        conn.commit()
    return len(selections)


def rebuild_chinese_glosses() -> None:
    """Rebuild ``zh_layer.zh_gloss`` and normalize/flag example translations
    non-destructively via ``is_usable``."""

    with connect() as conn:
        conn.execute("delete from zh_layer.zh_gloss")
        conn.execute(
            """
            insert into zh_layer.zh_gloss (
                sense_id, gloss_zh, generation_method, generation_version, is_primary
            )
            select selection.target_sense_id,
                   selection.gloss_zh,
                   candidate.source_name || '-' || selection.selected_by,
                   'v1',
                   true
            from semantic.zh_gloss_selection selection
            join semantic.zh_gloss_candidate candidate
              on candidate.id = selection.zh_gloss_candidate_id
            order by selection.target_sense_id
            """
        )
        translation_rows = conn.execute(
            "select id, text_zh, is_usable from zh_layer.zh_example_translation"
        ).fetchall()
        updates: list[tuple[str, bool, int]] = []
        for row_id, text_zh, current_usable in translation_rows:
            cleaned = normalize_and_validate_zh_sentence(text_zh)
            if cleaned is None:
                if current_usable:
                    updates.append((text_zh, False, int(row_id)))
            elif cleaned != text_zh or not current_usable:
                updates.append((cleaned, True, int(row_id)))
        if updates:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    update zh_layer.zh_example_translation
                    set text_zh = %s,
                        is_usable = %s
                    where id = %s
                    """,
                    updates,
                )
        conn.commit()
