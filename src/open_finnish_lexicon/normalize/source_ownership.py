"""Small helpers for source ownership of normalized rows."""

from __future__ import annotations

from collections.abc import Sequence

import psycopg
from psycopg import sql

_OWNED_ROW_TABLES: tuple[tuple[str, str, str], ...] = (
    ("lexicon.pronunciation_source", "pronunciation_id", "lexicon.pronunciation"),
    (
        "lexicon.derivation_relation_source",
        "relation_id",
        "lexicon.derivation_relation",
    ),
    (
        "lexicon.lexical_relation_source",
        "relation_id",
        "lexicon.lexical_relation",
    ),
    ("lexicon.grammar_note_source", "grammar_note_id", "lexicon.grammar_note"),
    ("lexicon.usage_warning_source", "usage_warning_id", "lexicon.usage_warning"),
    ("lexicon.lexeme_topic_source", "lexeme_topic_id", "lexicon.lexeme_topic"),
)


def link_source_row(
    conn: psycopg.Connection,
    *,
    ownership_table: str,
    row_id_column: str,
    row_id: int,
    source_file_id: int,
) -> None:
    """Record that one normalized row was produced by a source file."""

    conn.execute(
        sql.SQL(
            """
            insert into {ownership_table} ({row_id_column}, source_file_id)
            values (%s, %s)
            on conflict do nothing
            """
        ).format(
            ownership_table=sql.Identifier(*ownership_table.split(".")),
            row_id_column=sql.Identifier(row_id_column),
        ),
        (row_id, source_file_id),
    )


def clear_kaikki_owned_rows(
    conn: psycopg.Connection, *, source_file_id: int, replace_snapshot: bool
) -> None:
    """Remove Kaikki-owned normalized metadata for a file or full registry."""

    if replace_snapshot:
        source_ids_sql = sql.SQL(
            """
            select sf.id
            from warehouse.source_file sf
            join warehouse.source_registry sr on sr.id = sf.source_registry_id
            where sr.name = 'kaikki'
            """
        )
        params: Sequence[object] = ()
    else:
        source_ids_sql = sql.SQL("select %s")
        params = (source_file_id,)

    for index, (ownership_table, row_id_column, row_table) in enumerate(_OWNED_ROW_TABLES):
        temp_ident = sql.Identifier(f"tmp_kaikki_owned_row_{index}")
        own_ident = sql.Identifier(*ownership_table.split("."))
        row_col_ident = sql.Identifier(row_id_column)
        row_tbl_ident = sql.Identifier(*row_table.split("."))

        conn.execute(sql.SQL("drop table if exists {}").format(temp_ident))
        conn.execute(
            sql.SQL(
                """
                create temporary table {} (
                    row_id bigint primary key
                ) on commit preserve rows
                """
            ).format(temp_ident)
        )
        conn.execute(
            sql.SQL(
                """
                insert into {temp_table} (row_id)
                select distinct {row_id_column}
                from {ownership_table}
                where source_file_id in ({source_ids_sql})
                on conflict do nothing
                """
            ).format(
                temp_table=temp_ident,
                row_id_column=row_col_ident,
                ownership_table=own_ident,
                source_ids_sql=source_ids_sql,
            ),
            params,
        )
        conn.execute(
            sql.SQL(
                """
                delete from {ownership_table}
                where source_file_id in ({source_ids_sql})
                """
            ).format(
                ownership_table=own_ident,
                source_ids_sql=source_ids_sql,
            ),
            params,
        )
        conn.execute(
            sql.SQL(
                """
                delete from {row_table} row_to_delete
                using {temp_table} stale
                where row_to_delete.id = stale.row_id
                  and not exists (
                      select 1
                      from {ownership_table} remaining
                      where remaining.{row_id_column} = row_to_delete.id
                  )
                """
            ).format(
                row_table=row_tbl_ident,
                temp_table=temp_ident,
                ownership_table=own_ident,
                row_id_column=row_col_ident,
            )
        )
