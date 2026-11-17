"""Bulk merge lexemes that have no senses."""


from open_finnish_lexicon.normalize.lexemes.merge.batch import _delete_lexeme_ids_in_batches

def _merge_no_sense_lexemes_bulk(conn, merge_pairs: list[tuple[int, int]]) -> None:
    if not merge_pairs:
        return
    source_ids = [source_id for source_id, _target_id in merge_pairs]

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
        cursor.executemany(
            "insert into tmp_lexeme_merge (source_id, target_id) values (%s, %s)",
            merge_pairs,
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
        on conflict do nothing
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
         and target.syllabification is not distinct from source.syllabification
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
        update lexicon.grammar_note gn
        set lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where gn.lexeme_id = m.source_id
        """
    )
    conn.execute(
        """
        update lexicon.usage_warning uw
        set lexeme_id = m.target_id
        from tmp_lexeme_merge m
        where uw.lexeme_id = m.source_id
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
        insert into lexicon.derivation_relation (parent_lexeme_id, child_lexeme_id, relation_type, note)
        select distinct
            coalesce(parent_map.target_id, d.parent_lexeme_id),
            coalesce(child_map.target_id, d.child_lexeme_id),
            d.relation_type,
            d.note
        from lexicon.derivation_relation d
        left join tmp_lexeme_merge parent_map on parent_map.source_id = d.parent_lexeme_id
        left join tmp_lexeme_merge child_map on child_map.source_id = d.child_lexeme_id
        where parent_map.source_id is not null
           or child_map.source_id is not null
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.derivation_relation_source (relation_id, source_file_id)
        select distinct target.id, ownership.source_file_id
        from lexicon.derivation_relation source
        join lexicon.derivation_relation_source ownership
          on ownership.relation_id = source.id
        left join tmp_lexeme_merge parent_map on parent_map.source_id = source.parent_lexeme_id
        left join tmp_lexeme_merge child_map on child_map.source_id = source.child_lexeme_id
        join lexicon.derivation_relation target
          on target.parent_lexeme_id = coalesce(parent_map.target_id, source.parent_lexeme_id)
         and target.child_lexeme_id = coalesce(child_map.target_id, source.child_lexeme_id)
         and target.relation_type = source.relation_type
         and target.note is not distinct from source.note
        where parent_map.source_id is not null
           or child_map.source_id is not null
        on conflict do nothing
        """
    )
    conn.execute("delete from lexicon.form where lexeme_id in (select source_id from tmp_lexeme_merge)")
    conn.execute("delete from lexicon.form_analysis where lexeme_id in (select source_id from tmp_lexeme_merge)")
    conn.execute("delete from lexicon.pronunciation where lexeme_id in (select source_id from tmp_lexeme_merge)")
    conn.execute(
        """
        delete from lexicon.derivation_relation
        where parent_lexeme_id in (select source_id from tmp_lexeme_merge)
           or child_lexeme_id in (select source_id from tmp_lexeme_merge)
        """
    )
    conn.execute(
        """
        delete from lexicon.lexeme_topic
        where lexeme_id in (select source_id from tmp_lexeme_merge)
        """
    )
    _delete_lexeme_ids_in_batches(conn, source_ids)
