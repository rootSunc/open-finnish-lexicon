from collections import defaultdict


def load_canonical_case_variant_ids(conn, lexeme_ids: set[int]) -> dict[int, int]:
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
        lexeme_id: (lemma.casefold(), part_of_speech.casefold())
        for lexeme_id, lemma, part_of_speech in seed_rows
    }
    lemma_keys = sorted({lemma_key for lemma_key, _part_of_speech_key in id_to_key.values()})
    candidate_rows = conn.execute(
        """
        select l.id, l.lemma, l.part_of_speech, count(ls.id) as sense_count
        from lexicon.lexeme l
        left join lexicon.lexeme_sense ls on ls.lexeme_id = l.id
        where lower(l.lemma) = any(%s)
        group by l.id, l.lemma, l.part_of_speech
        """,
        (lemma_keys,),
    ).fetchall()

    best_by_key: dict[tuple[str, str], tuple[int, tuple[int, int, int]]] = {}
    for lexeme_id, lemma, part_of_speech, sense_count in candidate_rows:
        key = (lemma.casefold(), part_of_speech.casefold())
        if key not in id_to_key.values():
            continue
        score = (sense_count, 1 if part_of_speech.islower() else 0, -lexeme_id)
        current = best_by_key.get(key)
        if current is None or score > current[1]:
            best_by_key[key] = (lexeme_id, score)

    return {
        lexeme_id: best_by_key[id_to_key[lexeme_id]][0]
        for lexeme_id in lexeme_ids
        if id_to_key[lexeme_id] in best_by_key
    }


def load_unique_analysis_matches(conn, normalized_terms: set[str]) -> dict[str, int]:
    if not normalized_terms:
        return {}

    analysis_rows = conn.execute(
        """
        select normalized_query, lexeme_id
        from lexicon.form_analysis
        where normalized_query = any(%s)
        order by normalized_query, analysis_rank, confidence desc
        """,
        (sorted(normalized_terms),),
    ).fetchall()
    canonical_ids = load_canonical_case_variant_ids(conn, {lexeme_id for _normalized_query, lexeme_id in analysis_rows})

    grouped: dict[str, set[int]] = defaultdict(set)
    for normalized_query, lexeme_id in analysis_rows:
        grouped[normalized_query].add(canonical_ids.get(lexeme_id, lexeme_id))
    return {
        normalized_query: next(iter(lexeme_ids))
        for normalized_query, lexeme_ids in grouped.items()
        if len(lexeme_ids) == 1
    }


def load_unique_lemma_matches(conn, lemmas: set[str]) -> dict[str, int]:
    if not lemmas:
        return {}

    rows = conn.execute(
        """
        select id, lemma, part_of_speech
        from lexicon.lexeme
        where lemma = any(%s)
        """,
        (sorted(lemmas),),
    ).fetchall()
    canonical_ids = load_canonical_case_variant_ids(conn, {lexeme_id for lexeme_id, _lemma, _part_of_speech in rows})

    grouped: dict[str, set[int]] = defaultdict(set)
    for lexeme_id, lemma, _part_of_speech in rows:
        grouped[lemma].add(canonical_ids.get(lexeme_id, lexeme_id))
    return {
        lemma: next(iter(lexeme_ids))
        for lemma, lexeme_ids in grouped.items()
        if len(lexeme_ids) == 1
    }


def load_unique_form_matches(conn, normalized_forms: set[str]) -> dict[str, int]:
    if not normalized_forms:
        return {}

    rows = conn.execute(
        """
        select lexeme_id, normalized_form
        from lexicon.form
        where normalized_form = any(%s)
        """,
        (sorted(normalized_forms),),
    ).fetchall()
    canonical_ids = load_canonical_case_variant_ids(conn, {lexeme_id for lexeme_id, _normalized_form in rows})

    grouped: dict[str, set[int]] = defaultdict(set)
    for lexeme_id, normalized_form in rows:
        grouped[normalized_form].add(canonical_ids.get(lexeme_id, lexeme_id))
    return {
        normalized_form: next(iter(lexeme_ids))
        for normalized_form, lexeme_ids in grouped.items()
        if len(lexeme_ids) == 1
    }


def load_single_sense_ids(conn, lexeme_ids: set[int]) -> dict[int, int]:
    if not lexeme_ids:
        return {}

    rows = conn.execute(
        """
        select lexeme_id, min(id) as sense_id, count(*) as sense_count
        from lexicon.lexeme_sense
        where lexeme_id = any(%s)
        group by lexeme_id
        """,
        (sorted(lexeme_ids),),
    ).fetchall()
    return {
        lexeme_id: sense_id
        for lexeme_id, sense_id, sense_count in rows
        if sense_count == 1
    }


def load_sense_candidates(conn, lexeme_ids: set[int]) -> dict[int, list[tuple[int, str]]]:
    if not lexeme_ids:
        return {}

    rows = conn.execute(
        """
        select lexeme_id, id, coalesce(gloss_en, '')
        from lexicon.lexeme_sense
        where lexeme_id = any(%s)
        order by lexeme_id, sort_order, id
        """,
        (sorted(lexeme_ids),),
    ).fetchall()
    grouped: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for lexeme_id, sense_id, gloss_en in rows:
        grouped[lexeme_id].append((sense_id, gloss_en))
    return dict(grouped)
