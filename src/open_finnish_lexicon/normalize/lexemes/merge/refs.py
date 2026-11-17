"""Merge direct lexeme references and dedupe relation rows."""


def _merge_direct_lexeme_refs(conn, source_lexeme_id: int, target_lexeme_id: int) -> None:
    conn.execute(
        """
        update lexicon.collocation
        set lexeme_id = %s
        where lexeme_id = %s
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        insert into lexicon.lexeme_topic (
            lexeme_id, sense_id, topic_id, confidence, source, source_payload, status
        )
        select
            %s,
            sense_id,
            topic_id,
            confidence,
            source,
            source_payload,
            status
        from lexicon.lexeme_topic
        where lexeme_id = %s
          and sense_id is null
        on conflict (lexeme_id, topic_id, source)
        where sense_id is null
        do update set
            confidence = greatest(lexicon.lexeme_topic.confidence, excluded.confidence),
            source_payload = excluded.source_payload,
            status = excluded.status,
            updated_at = now()
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        insert into lexicon.lexeme_topic_source (lexeme_topic_id, source_file_id)
        select target.id, ownership.source_file_id
        from lexicon.lexeme_topic source
        join lexicon.lexeme_topic_source ownership
          on ownership.lexeme_topic_id = source.id
        join lexicon.lexeme_topic target
          on target.lexeme_id = %s
         and target.sense_id is null
         and target.topic_id = source.topic_id
         and target.source = source.source
        where source.lexeme_id = %s
          and source.sense_id is null
        on conflict do nothing
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        delete from lexicon.lexeme_topic
        where lexeme_id = %s and sense_id is null
        """,
        (source_lexeme_id,),
    )
    conn.execute(
        """
        insert into lexicon.grammar_note (lexeme_id, sense_id, note_fi, note_en, note_kind)
        select %s, sense_id, note_fi, note_en, note_kind
        from lexicon.grammar_note
        where lexeme_id = %s
        on conflict do nothing
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        insert into lexicon.grammar_note_source (grammar_note_id, source_file_id)
        select target.id, ownership.source_file_id
        from lexicon.grammar_note source
        join lexicon.grammar_note_source ownership
          on ownership.grammar_note_id = source.id
        join lexicon.grammar_note target
          on target.lexeme_id = %s
         and target.sense_id is not distinct from source.sense_id
         and target.note_fi is not distinct from source.note_fi
         and target.note_en is not distinct from source.note_en
         and target.note_kind = source.note_kind
        where source.lexeme_id = %s
        on conflict do nothing
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute("delete from lexicon.grammar_note where lexeme_id = %s", (source_lexeme_id,))
    conn.execute(
        """
        update lexicon.usage_warning
        set lexeme_id = %s
        where lexeme_id = %s
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        update lexicon.frequency_signal
        set lexeme_id = %s
        where lexeme_id = %s
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        update zh_layer.zh_note
        set lexeme_id = %s
        where lexeme_id = %s
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        update zh_layer.zh_warning
        set lexeme_id = %s
        where lexeme_id = %s
        """,
        (target_lexeme_id, source_lexeme_id),
    )

    conn.execute(
        """
        update lexicon.lexical_relation
        set source_lexeme_id = %s
        where source_lexeme_id = %s
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        update lexicon.lexical_relation
        set target_lexeme_id = %s
        where target_lexeme_id = %s
        """,
        (target_lexeme_id, source_lexeme_id),
    )
    conn.execute(
        """
        insert into lexicon.derivation_relation (parent_lexeme_id, child_lexeme_id, relation_type, note)
        select
            case when parent_lexeme_id = %s then %s else parent_lexeme_id end,
            case when child_lexeme_id = %s then %s else child_lexeme_id end,
            relation_type,
            note
        from lexicon.derivation_relation
        where parent_lexeme_id = %s or child_lexeme_id = %s
        on conflict do nothing
        """,
        (
            source_lexeme_id,
            target_lexeme_id,
            source_lexeme_id,
            target_lexeme_id,
            source_lexeme_id,
            source_lexeme_id,
        ),
    )
    conn.execute(
        """
        insert into lexicon.derivation_relation_source (relation_id, source_file_id)
        select target.id, ownership.source_file_id
        from lexicon.derivation_relation source
        join lexicon.derivation_relation_source ownership
          on ownership.relation_id = source.id
        join lexicon.derivation_relation target
          on target.parent_lexeme_id = case
                when source.parent_lexeme_id = %s then %s
                else source.parent_lexeme_id
             end
         and target.child_lexeme_id = case
                when source.child_lexeme_id = %s then %s
                else source.child_lexeme_id
             end
         and target.relation_type = source.relation_type
         and target.note is not distinct from source.note
        where source.parent_lexeme_id = %s or source.child_lexeme_id = %s
        on conflict do nothing
        """,
        (
            source_lexeme_id,
            target_lexeme_id,
            source_lexeme_id,
            target_lexeme_id,
            source_lexeme_id,
            source_lexeme_id,
        ),
    )
    conn.execute(
        """
        delete from lexicon.derivation_relation
        where parent_lexeme_id = %s or child_lexeme_id = %s
        """,
        (source_lexeme_id, source_lexeme_id),
    )


def _cleanup_relation_duplicates(conn) -> None:
    conn.execute(
        """
        insert into lexicon.derivation_relation_source (relation_id, source_file_id)
        select survivor.id, ownership.source_file_id
        from (
            select
                id,
                min(id) over (
                    partition by parent_lexeme_id, child_lexeme_id, relation_type, coalesce(note, '')
                ) as survivor_id,
                row_number() over (
                    partition by parent_lexeme_id, child_lexeme_id, relation_type, coalesce(note, '')
                    order by id
                ) as row_num
            from lexicon.derivation_relation
        ) duplicate
        join lexicon.derivation_relation survivor on survivor.id = duplicate.survivor_id
        join lexicon.derivation_relation_source ownership
          on ownership.relation_id = duplicate.id
        where duplicate.row_num > 1
        on conflict do nothing
        """
    )
    conn.execute(
        """
        delete from lexicon.lexical_relation doomed
        using (
            select id
            from (
                select id,
                       row_number() over (
                           partition by source_lexeme_id, target_lexeme_id, relation_type, confidence
                           order by id
                       ) as row_num
                       ,
                       source_lexeme_id,
                       target_lexeme_id
                from lexicon.lexical_relation
            ) ranked
            where row_num > 1 or ranked.source_lexeme_id = ranked.target_lexeme_id
        ) duplicates
        where doomed.id = duplicates.id
        """
    )
    conn.execute(
        """
        delete from lexicon.derivation_relation doomed
        using (
            select id
            from (
                select id,
                       row_number() over (
                           partition by parent_lexeme_id, child_lexeme_id, relation_type, coalesce(note, '')
                           order by id
                       ) as row_num
                       ,
                       parent_lexeme_id,
                       child_lexeme_id
                from lexicon.derivation_relation
            ) ranked
            where row_num > 1 or ranked.parent_lexeme_id = ranked.child_lexeme_id
        ) duplicates
        where doomed.id = duplicates.id
        """
    )
