"""Bulk merge lexemes that have no senses."""

from open_finnish_lexicon.normalize.lexemes.merge.batch import _delete_lexeme_ids_in_batches


def _merge_no_sense_lexemes_bulk(conn, merge_pairs: list[tuple[int, int]]) -> None:
    if not merge_pairs:
        return
    deduped_pairs = list(dict.fromkeys(merge_pairs))
    source_ids = [source_id for source_id, _target_id in deduped_pairs]

    with conn.cursor() as cursor:
        cursor.execute(
            """
            create temporary table if not exists tmp_lexeme_merge (
                source_id bigint primary key,
                target_id bigint not null
            ) on commit drop
            """
        )
        cursor.execute("truncate tmp_lexeme_merge")
        with cursor.copy("copy tmp_lexeme_merge (source_id, target_id) from stdin") as copy:
            for source_id, target_id in deduped_pairs:
                copy.write_row((source_id, target_id))

    conn.execute(
        """
        with agg as (
            select
                m.target_id,
                min(src.frequency_rank) as min_rank,
                bool_or(src.is_lemma) as any_is_lemma
            from tmp_lexeme_merge m
            join lexicon.lexeme src on src.id = m.source_id
            group by m.target_id
        )
        update lexicon.lexeme tgt
        set frequency_rank = case
                when agg.min_rank is null then tgt.frequency_rank
                when tgt.frequency_rank is null then agg.min_rank
                else least(tgt.frequency_rank, agg.min_rank)
            end,
            is_lemma = tgt.is_lemma or coalesce(agg.any_is_lemma, false)
        from agg
        where tgt.id = agg.target_id
        """
    )

    conn.execute(
        """
        insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
        select distinct
            m.target_id,
            f.surface_form,
            f.normalized_form,
            f.form_kind,
            f.features
        from lexicon.form f
        join tmp_lexeme_merge m on m.source_id = f.lexeme_id
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
        select distinct
            fa.normalized_query,
            m.target_id,
            fa.analysis_rank,
            fa.confidence,
            fa.features
        from lexicon.form_analysis fa
        join tmp_lexeme_merge m on m.source_id = fa.lexeme_id
        where not exists (
            select 1
            from lexicon.form_analysis existing
            where existing.lexeme_id = m.target_id
              and existing.normalized_query = fa.normalized_query
              and existing.analysis_rank = fa.analysis_rank
              and existing.confidence = fa.confidence
              and existing.features = fa.features
        )
        """
    )
    conn.execute(
        """
        insert into lexicon.form_source (form_id, source_file_id)
        select distinct target.id, ownership.source_file_id
        from lexicon.form source
        join lexicon.form_source ownership on ownership.form_id = source.id
        join tmp_lexeme_merge m on m.source_id = source.lexeme_id
        join lexicon.form target
          on target.lexeme_id = m.target_id
         and target.surface_form = source.surface_form
         and target.normalized_form = source.normalized_form
         and target.form_kind = source.form_kind
         and target.features = source.features
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.pronunciation (lexeme_id, ipa, syllabification, tts_voice)
        select distinct
            m.target_id,
            p.ipa,
            p.syllabification,
            p.tts_voice
        from lexicon.pronunciation p
        join tmp_lexeme_merge m on m.source_id = p.lexeme_id
        on conflict (lexeme_id, ipa) do update
        set syllabification = coalesce(
            lexicon.pronunciation.syllabification,
            excluded.syllabification
        )
        """
    )
    conn.execute(
        """
        insert into lexicon.pronunciation_source (pronunciation_id, source_file_id)
        select distinct target.id, ownership.source_file_id
        from lexicon.pronunciation source
        join lexicon.pronunciation_source ownership
          on ownership.pronunciation_id = source.id
        join tmp_lexeme_merge m on m.source_id = source.lexeme_id
        join lexicon.pronunciation target
          on target.lexeme_id = m.target_id
         and target.ipa is not distinct from source.ipa
         and target.tts_voice = source.tts_voice
        on conflict do nothing
        """
    )
    conn.execute(
        """
        update lexicon.collocation c
        set lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where c.lexeme_id = m.source_id
        """
    )
    conn.execute(
        """
        update zh_layer.zh_note zn
        set lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where zn.lexeme_id = m.source_id
        """
    )
    conn.execute(
        """
        update zh_layer.zh_warning zw
        set lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where zw.lexeme_id = m.source_id
        """
    )
    conn.execute(
        """
        update lexicon.frequency_signal fs
        set lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where fs.lexeme_id = m.source_id
        """
    )
    conn.execute(
        """
        insert into lexicon.grammar_note (lexeme_id, sense_id, note_fi, note_en, note_kind)
        select distinct m.target_id, gn.sense_id, gn.note_fi, gn.note_en, gn.note_kind
        from lexicon.grammar_note gn
        join tmp_lexeme_merge m on m.source_id = gn.lexeme_id
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.grammar_note_source (grammar_note_id, source_file_id)
        select distinct target.id, ownership.source_file_id
        from lexicon.grammar_note source
        join lexicon.grammar_note_source ownership
          on ownership.grammar_note_id = source.id
        join tmp_lexeme_merge m on m.source_id = source.lexeme_id
        join lexicon.grammar_note target
          on target.lexeme_id = m.target_id
         and target.sense_id is not distinct from source.sense_id
         and target.note_fi is not distinct from source.note_fi
         and target.note_en is not distinct from source.note_en
         and target.note_kind = source.note_kind
        on conflict do nothing
        """
    )
    conn.execute(
        """
        delete from lexicon.grammar_note
        where lexeme_id in (select source_id from tmp_lexeme_merge)
        """
    )
    conn.execute(
        """
        insert into lexicon.usage_warning (lexeme_id, sense_id, warning_fi, warning_en, warning_kind)
        select distinct m.target_id, uw.sense_id, uw.warning_fi, uw.warning_en, uw.warning_kind
        from lexicon.usage_warning uw
        join tmp_lexeme_merge m on m.source_id = uw.lexeme_id
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.usage_warning_source (usage_warning_id, source_file_id)
        select distinct target.id, ownership.source_file_id
        from lexicon.usage_warning source
        join lexicon.usage_warning_source ownership
          on ownership.usage_warning_id = source.id
        join tmp_lexeme_merge m on m.source_id = source.lexeme_id
        join lexicon.usage_warning target
          on target.lexeme_id = m.target_id
         and target.sense_id is not distinct from source.sense_id
         and target.warning_fi is not distinct from source.warning_fi
         and target.warning_en is not distinct from source.warning_en
         and target.warning_kind = source.warning_kind
        on conflict do nothing
        """
    )
    conn.execute(
        """
        delete from lexicon.usage_warning
        where lexeme_id in (select source_id from tmp_lexeme_merge)
        """
    )
    conn.execute(
        """
        insert into lexicon.lexeme_topic (
            lexeme_id, sense_id, topic_id, confidence, source, source_payload, status
        )
        select
            m.target_id,
            topic.sense_id,
            topic.topic_id,
            topic.confidence,
            topic.source,
            topic.source_payload,
            topic.status
        from lexicon.lexeme_topic topic
        join tmp_lexeme_merge m on m.source_id = topic.lexeme_id
        where topic.sense_id is null
        on conflict (lexeme_id, topic_id, source)
        where sense_id is null
        do update set
            confidence = greatest(lexicon.lexeme_topic.confidence, excluded.confidence),
            source_payload = excluded.source_payload,
            status = excluded.status,
            updated_at = now()
        """
    )
    conn.execute(
        """
        insert into lexicon.lexeme_topic_source (lexeme_topic_id, source_file_id)
        select target.id, ownership.source_file_id
        from lexicon.lexeme_topic source
        join lexicon.lexeme_topic_source ownership
          on ownership.lexeme_topic_id = source.id
        join tmp_lexeme_merge m on m.source_id = source.lexeme_id
        join lexicon.lexeme_topic target
          on target.lexeme_id = m.target_id
         and target.sense_id is null
         and target.topic_id = source.topic_id
         and target.source = source.source
        where source.sense_id is null
        on conflict do nothing
        """
    )
    conn.execute(
        """
        update lexicon.lexical_relation r
        set source_lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where r.source_lexeme_id = m.source_id
        """
    )
    conn.execute(
        """
        update lexicon.lexical_relation r
        set target_lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where r.target_lexeme_id = m.source_id
        """
    )
    conn.execute(
        """
        with affected_derivations as (
            select id, parent_lexeme_id, child_lexeme_id, relation_type, note
            from lexicon.derivation_relation
            where parent_lexeme_id in (select source_id from tmp_lexeme_merge)
            union
            select id, parent_lexeme_id, child_lexeme_id, relation_type, note
            from lexicon.derivation_relation
            where child_lexeme_id in (select source_id from tmp_lexeme_merge)
        )
        insert into lexicon.derivation_relation (parent_lexeme_id, child_lexeme_id, relation_type, note)
        select distinct
            coalesce(parent_map.target_id, d.parent_lexeme_id),
            coalesce(child_map.target_id, d.child_lexeme_id),
            d.relation_type,
            d.note
        from affected_derivations d
        left join tmp_lexeme_merge parent_map on parent_map.source_id = d.parent_lexeme_id
        left join tmp_lexeme_merge child_map on child_map.source_id = d.child_lexeme_id
        on conflict do nothing
        """
    )
    conn.execute(
        """
        with affected_derivations as (
            select id, parent_lexeme_id, child_lexeme_id, relation_type, note
            from lexicon.derivation_relation
            where parent_lexeme_id in (select source_id from tmp_lexeme_merge)
            union
            select id, parent_lexeme_id, child_lexeme_id, relation_type, note
            from lexicon.derivation_relation
            where child_lexeme_id in (select source_id from tmp_lexeme_merge)
        )
        insert into lexicon.derivation_relation_source (relation_id, source_file_id)
        select distinct target.id, ownership.source_file_id
        from affected_derivations source
        join lexicon.derivation_relation_source ownership
          on ownership.relation_id = source.id
        left join tmp_lexeme_merge parent_map on parent_map.source_id = source.parent_lexeme_id
        left join tmp_lexeme_merge child_map on child_map.source_id = source.child_lexeme_id
        join lexicon.derivation_relation target
          on target.parent_lexeme_id = coalesce(parent_map.target_id, source.parent_lexeme_id)
         and target.child_lexeme_id = coalesce(child_map.target_id, source.child_lexeme_id)
         and target.relation_type = source.relation_type
         and target.note is not distinct from source.note
        on conflict do nothing
        """
    )
    conn.execute(
        "delete from lexicon.form where lexeme_id in (select source_id from tmp_lexeme_merge)"
    )
    conn.execute(
        "delete from lexicon.form_analysis where lexeme_id in (select source_id from tmp_lexeme_merge)"
    )
    conn.execute(
        "delete from lexicon.pronunciation where lexeme_id in (select source_id from tmp_lexeme_merge)"
    )
    conn.execute(
        "delete from lexicon.derivation_relation where parent_lexeme_id in (select source_id from tmp_lexeme_merge)"
    )
    conn.execute(
        "delete from lexicon.derivation_relation where child_lexeme_id in (select source_id from tmp_lexeme_merge)"
    )
    conn.execute(
        "delete from lexicon.lexeme_topic where lexeme_id in (select source_id from tmp_lexeme_merge)"
    )
    _delete_lexeme_ids_in_batches(conn, source_ids)
