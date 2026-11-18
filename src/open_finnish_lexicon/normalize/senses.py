from collections.abc import Iterable

from psycopg import sql

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.lexemes.types import normalize_part_of_speech
from open_finnish_lexicon.sources.kaikki_loader import has_kaikki_projection_data

_SENSE_DEPENDENCIES = (
    ("lexicon", "collocation", "sense_id"),
    ("lexicon", "grammar_note", "sense_id"),
    ("lexicon", "sense_example", "sense_id"),
    ("lexicon", "usage_warning", "sense_id"),
    ("semantic", "sense_alignment", "target_sense_id"),
    ("semantic", "sense_alignment_candidate", "target_sense_id"),
    ("semantic", "zh_gloss_selection", "target_sense_id"),
    ("semantic", "zh_gloss_candidate", "target_sense_id"),
    ("zh_layer", "zh_gloss", "sense_id"),
    ("zh_layer", "zh_note", "sense_id"),
    ("zh_layer", "zh_warning", "sense_id"),
)


def _delete_orphan_kaikki_senses(conn) -> None:
    """Delete stale senses whose last Kaikki ownership disappeared.

    Source ownership is deliberately conservative: an unowned sense may have
    been added by an editor or another content workflow, so it is not included
    in the cleanup set. Non-cascading dependants are removed explicitly first;
    topic rows cascade, while source and Chinese-layer tables keep their
    constraints strict.
    """

    conn.execute("drop table if exists tmp_kaikki_orphan_sense")
    conn.execute(
        """
        create temporary table tmp_kaikki_orphan_sense (
            sense_id bigint primary key
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_orphan_sense (sense_id)
        select cleanup.sense_id
        from tmp_kaikki_sense_cleanup cleanup
        where not exists (
            select 1
            from lexicon.sense_source ownership
            where ownership.sense_id = cleanup.sense_id
        )
        on conflict do nothing
        """
    )
    for schema, table, column in _SENSE_DEPENDENCIES:
        conn.execute(
            sql.SQL(
                "delete from {}.{} where {} in (select sense_id from tmp_kaikki_orphan_sense)"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(column),
            )
        )
    conn.execute(
        """
        delete from lexicon.lexeme_sense
        where id in (select sense_id from tmp_kaikki_orphan_sense)
        """
    )


def upsert_kaikki_entries(
    entries: Iterable[dict],
    *,
    source_file_id: int | None = None,
    replace_snapshot: bool = False,
    allow_empty_snapshot: bool = False,
    connection=None,
) -> None:
    """Delegate iterable Kaikki projection to the unified set-based projector."""

    if replace_snapshot and source_file_id is None:
        raise ValueError("replace_snapshot requires a Kaikki source_file_id")
    from open_finnish_lexicon.sources.kaikki_bulk import upsert_kaikki_entry_iterable

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        upsert_kaikki_entry_iterable(
            conn,
            entries,
            source_file_id=source_file_id,
            replace_snapshot=replace_snapshot,
            allow_empty_snapshot=allow_empty_snapshot,
        )
        if owns_connection:
            conn.commit()


def clear_kaikki_stale_data_for_non_projection_entries(
    entries: Iterable[dict] | None = None, *, source_file_id: int, connection=None
) -> None:
    """Remove source-owned data for valid Kaikki entries no longer projected."""

    from open_finnish_lexicon.sources.kaikki_bulk import refresh_lexeme_is_lemma_flags

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        conn.execute("drop table if exists tmp_kaikki_projection_state")
        conn.execute("drop table if exists tmp_kaikki_sense_cleanup")
        conn.execute("drop table if exists tmp_kaikki_form_cleanup")
        conn.execute(
            """
            create temporary table tmp_kaikki_projection_state (
                lemma text not null,
                part_of_speech text not null,
                has_projection boolean not null
            ) on commit drop
            """
        )
        conn.execute(
            """
            create temporary table tmp_kaikki_sense_cleanup (
                sense_id bigint primary key
            ) on commit preserve rows
            """
        )
        conn.execute(
            """
            create temporary table tmp_kaikki_form_cleanup (
                form_id bigint primary key
            ) on commit preserve rows
            """
        )
        if entries is None:
            conn.execute(
                """
                insert into tmp_kaikki_projection_state (
                    lemma,
                    part_of_speech,
                    has_projection
                )
                select
                    payload->>'word',
                    btrim(lower(payload->>'pos')),
                    projection_eligible
                from warehouse.source_document
                where source_file_id = %s
                  and jsonb_typeof(payload) = 'object'
                  and btrim(coalesce(payload->>'word', '')) <> ''
                  and btrim(coalesce(payload->>'pos', '')) <> ''
                """,
                (source_file_id,),
            )
        else:
            with conn.cursor() as cursor:
                with cursor.copy(
                    """
                    copy tmp_kaikki_projection_state (lemma, part_of_speech, has_projection)
                    from stdin
                    """
                ) as copy:
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        word = entry.get("word")
                        raw_pos = entry.get("pos")
                        if not isinstance(word, str) or not isinstance(raw_pos, str):
                            continue
                        copy.write_row(
                            (
                                word,
                                normalize_part_of_speech(raw_pos),
                                has_kaikki_projection_data(entry),
                            )
                        )

        conn.execute(
            """
            insert into tmp_kaikki_form_cleanup (form_id)
            select distinct fs.form_id
            from lexicon.form_source fs
            join lexicon.form f on f.id = fs.form_id
            join lexicon.lexeme l on l.id = f.lexeme_id
            where fs.source_file_id = %s
              and not exists (
                  select 1
                  from tmp_kaikki_projection_state s
                  where s.lemma = l.lemma
                    and s.part_of_speech = l.part_of_speech
                    and s.has_projection
              )
            on conflict do nothing
            """,
            (source_file_id,),
        )
        conn.execute(
            """
            delete from lexicon.form_source fs
            using tmp_kaikki_form_cleanup cleanup
            where fs.form_id = cleanup.form_id
              and fs.source_file_id = %s
            """,
            (source_file_id,),
        )
        conn.execute(
            """
            delete from lexicon.form f
            using tmp_kaikki_form_cleanup cleanup
            where f.id = cleanup.form_id
              and not exists (
                  select 1
                  from lexicon.form_source fs
                  where fs.form_id = f.id
              )
            """,
        )
        conn.execute(
            """
            insert into tmp_kaikki_sense_cleanup (sense_id)
            select ss.sense_id
            from lexicon.sense_source ss
            join lexicon.lexeme_sense ls on ls.id = ss.sense_id
            join lexicon.lexeme l on l.id = ls.lexeme_id
            where ss.source_file_id = %s
              and not exists (
                  select 1
                  from tmp_kaikki_projection_state s
                  where s.lemma = l.lemma
                    and s.part_of_speech = l.part_of_speech
                    and s.has_projection
              )
            on conflict do nothing
            """,
            (source_file_id,),
        )
        conn.execute(
            """
            delete from lexicon.sense_source ss
            using tmp_kaikki_sense_cleanup cleanup
            where ss.sense_id = cleanup.sense_id
              and ss.source_file_id = %s
            """,
            (source_file_id,),
        )
        _delete_orphan_kaikki_senses(conn)
        refresh_lexeme_is_lemma_flags(conn)
        if owns_connection:
            conn.commit()
