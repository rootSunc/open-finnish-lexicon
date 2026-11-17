"""Small helpers for source ownership of normalized rows."""

from collections.abc import Sequence


_OWNED_ROW_TABLES: tuple[tuple[str, str, str], ...] = (
    ("lexicon.pronunciation_source", "pronunciation_id", "lexicon.pronunciation"),
    (
        "lexicon.derivation_relation_source",
        "relation_id",
        "lexicon.derivation_relation",
    ),
    ("lexicon.grammar_note_source", "grammar_note_id", "lexicon.grammar_note"),
    ("lexicon.usage_warning_source", "usage_warning_id", "lexicon.usage_warning"),
    ("lexicon.lexeme_topic_source", "lexeme_topic_id", "lexicon.lexeme_topic"),
)


def link_source_row(
    conn,
    *,
    ownership_table: str,
    row_id_column: str,
    row_id: int,
    source_file_id: int,
) -> None:
    """Record that one normalized row was produced by a source file."""

    conn.execute(
        f"""
        insert into {ownership_table} ({row_id_column}, source_file_id)
        values (%s, %s)
        on conflict do nothing
        """,
        (row_id, source_file_id),
    )


def clear_kaikki_owned_rows(conn, *, source_file_id: int, replace_snapshot: bool) -> None:
    """Remove Kaikki-owned normalized metadata for a file or full registry.

    The normalized rows themselves are removed only when no other source still
    owns them. This keeps manually curated and multi-source rows intact.
    """

    if replace_snapshot:
        source_ids_sql = """
            select sf.id
            from warehouse.source_file sf
            join warehouse.source_registry sr on sr.id = sf.source_registry_id
            where sr.name = 'kaikki'
        """
        params: Sequence[object] = ()
    else:
        source_ids_sql = "select %s"
        params = (source_file_id,)

    for index, (ownership_table, row_id_column, row_table) in enumerate(_OWNED_ROW_TABLES):
        temp_table = f"tmp_kaikki_owned_row_{index}"
        conn.execute(f"drop table if exists {temp_table}")
        conn.execute(
            f"""
            create temporary table {temp_table} (
                row_id bigint primary key
            ) on commit preserve rows
            """
        )
        conn.execute(
            f"""
            insert into {temp_table} (row_id)
            select distinct {row_id_column}
            from {ownership_table}
            where source_file_id in ({source_ids_sql})
            on conflict do nothing
            """,
            params,
        )
        conn.execute(
            f"""
            delete from {ownership_table}
            where source_file_id in ({source_ids_sql})
            """,
            params,
        )
        conn.execute(
            f"""
            delete from {row_table} row_to_delete
            using {temp_table} stale
            where row_to_delete.id = stale.row_id
              and not exists (
                  select 1
                  from {ownership_table} remaining
                  where remaining.{row_id_column} = row_to_delete.id
              )
            """
        )
