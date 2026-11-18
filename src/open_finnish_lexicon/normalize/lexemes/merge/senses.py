"""Merge lexicon sense rows between lexemes."""

from psycopg import sql

from open_finnish_lexicon.normalize.lexemes.merge.semantic_senses import _merge_semantic_sense_rows


def _merge_topic_rows(conn, source_sense_id: int, target_sense_id: int) -> None:
    target_lexeme_id = conn.execute(
        "select lexeme_id from lexicon.lexeme_sense where id = %s",
        (target_sense_id,),
    ).fetchone()[0]
    conn.execute(
        """
        insert into lexicon.lexeme_topic (
            lexeme_id, sense_id, topic_id, confidence, source, source_payload, status
        )
        select
            %s,
            %s,
            topic_id,
            confidence,
            source,
            source_payload,
            status
        from lexicon.lexeme_topic
        where sense_id = %s
        on conflict (lexeme_id, sense_id, topic_id, source)
        where sense_id is not null
        do update set
            confidence = greatest(lexicon.lexeme_topic.confidence, excluded.confidence),
            source_payload = excluded.source_payload,
            status = excluded.status,
            updated_at = now()
        """,
        (target_lexeme_id, target_sense_id, source_sense_id),
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
         and target.sense_id = %s
         and target.topic_id = source.topic_id
         and target.source = source.source
        where source.sense_id = %s
        on conflict do nothing
        """,
        (target_lexeme_id, target_sense_id, source_sense_id),
    )
    conn.execute(
        "delete from lexicon.lexeme_topic where sense_id = %s",
        (source_sense_id,),
    )

def _merge_sense_rows(conn, source_lexeme_id: int, target_lexeme_id: int) -> None:
    sense_rows = conn.execute(
        """
        select id, sense_key
        from lexicon.lexeme_sense
        where lexeme_id = %s
        order by id
        """,
        (source_lexeme_id,),
    ).fetchall()
    for source_sense_id, sense_key in sense_rows:
        existing_target_row = conn.execute(
            """
            select id
            from lexicon.lexeme_sense
            where lexeme_id = %s and sense_key = %s
            """,
            (target_lexeme_id, sense_key),
        ).fetchone()
        if existing_target_row is None:
            conn.execute(
                """
                update lexicon.lexeme_sense
                set lexeme_id = %s
                where id = %s
                """,
                (target_lexeme_id, source_sense_id),
            )
            conn.execute(
                """
                update lexicon.lexeme_topic
                set lexeme_id = %s,
                    updated_at = now()
                where sense_id = %s
                """,
                (target_lexeme_id, source_sense_id),
            )
            continue

        target_sense_id = existing_target_row[0]
        _merge_semantic_sense_rows(conn, source_sense_id, target_sense_id)
        _merge_topic_rows(conn, source_sense_id, target_sense_id)
        conn.execute(
            """
            insert into lexicon.sense_example (sense_id, example_id, is_core, sort_order)
            select %s, example_id, is_core, sort_order
            from lexicon.sense_example
            where sense_id = %s
            on conflict (sense_id, example_id) do update
            set is_core = lexicon.sense_example.is_core or excluded.is_core,
                sort_order = least(lexicon.sense_example.sort_order, excluded.sort_order)
            """,
            (target_sense_id, source_sense_id),
        )
        conn.execute(
            """
            update lexicon.collocation
            set sense_id = %s
            where sense_id = %s
            """,
            (target_sense_id, source_sense_id),
        )
        conn.execute(
            """
            insert into lexicon.grammar_note (lexeme_id, sense_id, note_fi, note_en, note_kind)
            select lexeme_id, %s, note_fi, note_en, note_kind
            from lexicon.grammar_note
            where sense_id = %s
            on conflict do nothing
            """,
            (target_sense_id, source_sense_id),
        )
        conn.execute(
            """
            insert into lexicon.grammar_note_source (grammar_note_id, source_file_id)
            select target.id, ownership.source_file_id
            from lexicon.grammar_note source
            join lexicon.grammar_note_source ownership
              on ownership.grammar_note_id = source.id
            join lexicon.grammar_note target
              on target.sense_id = %s
             and target.lexeme_id is not distinct from source.lexeme_id
             and target.note_fi is not distinct from source.note_fi
             and target.note_en is not distinct from source.note_en
             and target.note_kind = source.note_kind
            where source.sense_id = %s
            on conflict do nothing
            """,
            (target_sense_id, source_sense_id),
        )
        conn.execute("delete from lexicon.grammar_note where sense_id = %s", (source_sense_id,))
        conn.execute(
            """
            insert into lexicon.usage_warning (lexeme_id, sense_id, warning_fi, warning_en, warning_kind)
            select lexeme_id, %s, warning_fi, warning_en, warning_kind
            from lexicon.usage_warning
            where sense_id = %s
            on conflict do nothing
            """,
            (target_sense_id, source_sense_id),
        )
        conn.execute(
            """
            insert into lexicon.usage_warning_source (usage_warning_id, source_file_id)
            select target.id, ownership.source_file_id
            from lexicon.usage_warning source
            join lexicon.usage_warning_source ownership
              on ownership.usage_warning_id = source.id
            join lexicon.usage_warning target
              on target.sense_id = %s
             and target.lexeme_id is not distinct from source.lexeme_id
             and target.warning_fi is not distinct from source.warning_fi
             and target.warning_en is not distinct from source.warning_en
             and target.warning_kind = source.warning_kind
            where source.sense_id = %s
            on conflict do nothing
            """,
            (target_sense_id, source_sense_id),
        )
        conn.execute("delete from lexicon.usage_warning where sense_id = %s", (source_sense_id,))
        for schema_name, table_name in (
            ("zh_layer", "zh_gloss"),
            ("zh_layer", "zh_note"),
            ("zh_layer", "zh_warning"),
        ):
            conn.execute(
                sql.SQL("update {}.{} set sense_id = %s where sense_id = %s").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                ),
                (target_sense_id, source_sense_id),
            )
        conn.execute("delete from lexicon.lexeme_sense where id = %s", (source_sense_id,))
