from __future__ import annotations

from collections import defaultdict

import psycopg


def load_canonical_case_variant_ids(
    conn: psycopg.Connection, lexeme_ids: set[int]
) -> dict[int, int]:
    if not lexeme_ids:
        return {}

    seed_rows = conn.execute(
        """
        select id, lemma, part_of_speech
        from lexicon.lexeme
        where id = any(%s)
        """,
        (list(lexeme_ids),),
    ).fetchall()
    if not seed_rows:
        return {}

    id_to_key = {
        int(lexeme_id): (str(lemma).casefold(), str(part_of_speech).casefold())
        for lexeme_id, lemma, part_of_speech in seed_rows
    }
    lemma_keys = sorted({lemma_key for lemma_key, _part_of_speech_key in id_to_key.values()})
    candidate_rows = conn.execute(
        """
        select l.id, l.lemma, l.part_of_speech, l.is_lemma, count(ls.id) as sense_count
        from lexicon.lexeme l
        left join lexicon.lexeme_sense ls on ls.lexeme_id = l.id
        where lower(l.lemma) = any(%s)
        group by l.id, l.lemma, l.part_of_speech, l.is_lemma
        """,
        (lemma_keys,),
    ).fetchall()

    best_by_key: dict[tuple[str, str], tuple[int, tuple[int, int, int, int]]] = {}
    valid_keys = set(id_to_key.values())
    for lexeme_id, lemma, part_of_speech, is_lemma, sense_count in candidate_rows:
        key = (str(lemma).casefold(), str(part_of_speech).casefold())
        if key not in valid_keys:
            continue
        score = (
            1 if is_lemma else 0,
            int(sense_count),
            1 if str(part_of_speech).islower() else 0,
            -int(lexeme_id),
        )
        current = best_by_key.get(key)
        if current is None or score > current[1]:
            best_by_key[key] = (int(lexeme_id), score)

    return {
        lexeme_id: best_by_key[id_to_key[lexeme_id]][0]
        for lexeme_id in lexeme_ids
        if lexeme_id in id_to_key and id_to_key[lexeme_id] in best_by_key
    }


def load_unique_analysis_matches(
    conn: psycopg.Connection, normalized_terms: set[str]
) -> dict[str, int]:
    if not normalized_terms:
        return {}

    analysis_rows = conn.execute(
        """
        select fa.normalized_query, fa.lexeme_id
        from lexicon.form_analysis fa
        join lexicon.lexeme l on l.id = fa.lexeme_id
        where fa.normalized_query = any(%s)
          and l.is_lemma = true
        order by fa.normalized_query, fa.analysis_rank, fa.confidence desc
        """,
        (sorted(normalized_terms),),
    ).fetchall()
    canonical_ids = load_canonical_case_variant_ids(
        conn, {int(lexeme_id) for _normalized_query, lexeme_id in analysis_rows}
    )

    grouped: dict[str, set[int]] = defaultdict(set)
    for normalized_query, lexeme_id in analysis_rows:
        grouped[str(normalized_query)].add(canonical_ids.get(int(lexeme_id), int(lexeme_id)))
    return {
        normalized_query: next(iter(lexeme_ids))
        for normalized_query, lexeme_ids in grouped.items()
        if len(lexeme_ids) == 1
    }


def load_unique_lemma_matches(conn: psycopg.Connection, lemmas: set[str]) -> dict[str, int]:
    if not lemmas:
        return {}

    rows = conn.execute(
        """
        select id, lemma, part_of_speech
        from lexicon.lexeme
        where lemma = any(%s)
          and is_lemma = true
        """,
        (sorted(lemmas),),
    ).fetchall()
    canonical_ids = load_canonical_case_variant_ids(
        conn, {int(lexeme_id) for lexeme_id, _lemma, _part_of_speech in rows}
    )

    grouped: dict[str, set[int]] = defaultdict(set)
    for lexeme_id, lemma, _part_of_speech in rows:
        grouped[str(lemma)].add(canonical_ids.get(int(lexeme_id), int(lexeme_id)))
    return {
        lemma: next(iter(lexeme_ids))
        for lemma, lexeme_ids in grouped.items()
        if len(lexeme_ids) == 1
    }


def load_unique_form_matches(
    conn: psycopg.Connection, normalized_forms: set[str]
) -> dict[str, int]:
    if not normalized_forms:
        return {}

    rows = conn.execute(
        """
        select f.lexeme_id, f.normalized_form
        from lexicon.form f
        join lexicon.lexeme l on l.id = f.lexeme_id
        where f.normalized_form = any(%s)
          and l.is_lemma = true
        """,
        (sorted(normalized_forms),),
    ).fetchall()
    canonical_ids = load_canonical_case_variant_ids(
        conn, {int(lexeme_id) for lexeme_id, _normalized_form in rows}
    )

    grouped: dict[str, set[int]] = defaultdict(set)
    for lexeme_id, normalized_form in rows:
        grouped[str(normalized_form)].add(canonical_ids.get(int(lexeme_id), int(lexeme_id)))
    return {
        normalized_form: next(iter(lexeme_ids))
        for normalized_form, lexeme_ids in grouped.items()
        if len(lexeme_ids) == 1
    }


def load_single_sense_ids(conn: psycopg.Connection, lexeme_ids: set[int]) -> dict[int, int]:
    if not lexeme_ids:
        return {}

    rows = conn.execute(
        """
        select lexeme_id, min(id) as sense_id, count(*) as sense_count
        from lexicon.lexeme_sense
        where lexeme_id = any(%s)
          and not ('form-of' = any(labels))
        group by lexeme_id
        """,
        (sorted(lexeme_ids),),
    ).fetchall()
    return {
        int(lexeme_id): int(sense_id)
        for lexeme_id, sense_id, sense_count in rows
        if int(sense_count) == 1
    }


def load_sense_candidates(
    conn: psycopg.Connection, lexeme_ids: set[int]
) -> dict[int, list[tuple[int, str]]]:
    if not lexeme_ids:
        return {}

    rows = conn.execute(
        """
        select lexeme_id, id, coalesce(gloss_en, '')
        from lexicon.lexeme_sense
        where lexeme_id = any(%s)
          and not ('form-of' = any(labels))
        order by lexeme_id, sort_order, id
        """,
        (sorted(lexeme_ids),),
    ).fetchall()
    grouped: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for lexeme_id, sense_id, gloss_en in rows:
        grouped[int(lexeme_id)].append((int(sense_id), str(gloss_en)))
    return dict(grouped)
