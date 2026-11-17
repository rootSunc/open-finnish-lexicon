"""Merge lexeme form and pronunciation rows."""


def _merge_form_rows(conn, source_lexeme_id: int, target_lexeme_id: int) -> None:
    conn.execute(
        """
        insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
        select %s, surface_form, normalized_form, form_kind, features
        from lexicon.form
        where lexeme_id = %s
        on conflict do nothing
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        insert into lexicon.form_source (form_id, source_file_id)
        select distinct target.id, ownership.source_file_id
        from lexicon.form source
        join lexicon.form_source ownership on ownership.form_id = source.id
        join lexicon.form target
          on target.lexeme_id = %s
         and target.surface_form = source.surface_form
         and target.normalized_form = source.normalized_form
         and target.form_kind = source.form_kind
         and target.features = source.features
        where source.lexeme_id = %s
        on conflict do nothing
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute("delete from lexicon.form where lexeme_id = %s", (source_lexeme_id,))


def _merge_form_analysis_rows(conn, source_lexeme_id: int, target_lexeme_id: int) -> None:
    conn.execute(
        """
        insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
        select normalized_query, %s, analysis_rank, confidence, features
        from (
            select distinct normalized_query, analysis_rank, confidence, features
            from lexicon.form_analysis
            where lexeme_id = %s
        ) source_rows
        where not exists (
            select 1
            from lexicon.form_analysis existing
            where existing.lexeme_id = %s
              and existing.normalized_query = source_rows.normalized_query
              and existing.analysis_rank = source_rows.analysis_rank
              and existing.confidence = source_rows.confidence
              and existing.features = source_rows.features
        )
        """,
        (target_lexeme_id, source_lexeme_id, target_lexeme_id),
    )
    conn.execute("delete from lexicon.form_analysis where lexeme_id = %s", (source_lexeme_id,))


def _merge_pronunciations(conn, source_lexeme_id: int, target_lexeme_id: int) -> None:
    conn.execute(
        """
        insert into lexicon.pronunciation (lexeme_id, ipa, syllabification, tts_voice)
        select %s, ipa, syllabification, tts_voice
        from lexicon.pronunciation
        where lexeme_id = %s
        on conflict do nothing
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        insert into lexicon.pronunciation_source (pronunciation_id, source_file_id)
        select target.id, ownership.source_file_id
        from lexicon.pronunciation source
        join lexicon.pronunciation_source ownership
          on ownership.pronunciation_id = source.id
        join lexicon.pronunciation target
          on target.lexeme_id = %s
         and target.ipa is not distinct from source.ipa
         and target.syllabification is not distinct from source.syllabification
         and target.tts_voice = source.tts_voice
        where source.lexeme_id = %s
        on conflict do nothing
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute("delete from lexicon.pronunciation where lexeme_id = %s", (source_lexeme_id,))
