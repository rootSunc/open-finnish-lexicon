"""Staging preparation, lemma-flag maintenance, and stale ownership cleanup for Kaikki."""

from __future__ import annotations

from collections.abc import Iterable
import json
import sys

import psycopg
from psycopg import sql

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.source_ownership import clear_kaikki_owned_rows
from open_finnish_lexicon.sources.kaikki_loader import (
    compact_kaikki_entry,
    has_kaikki_projection_data,
)

_FORM_CLEANUP_BATCH_SIZE = 10_000


def refresh_lexeme_is_lemma_flags(conn: psycopg.Connection) -> None:
    """Keep ``lexicon.lexeme.is_lemma`` false for pure ``form-of`` entries and
    true for all canonical/sense-bearing lemmas."""

    conn.execute(
        """
        update lexicon.lexeme l
        set is_lemma = computed.expected_is_lemma
        from (
            select
                lx.id,
                not (
                    exists (
                        select 1
                        from lexicon.lexeme_sense s
                        where s.lexeme_id = lx.id
                    )
                    and not exists (
                        select 1
                        from lexicon.lexeme_sense s
                        where s.lexeme_id = lx.id
                          and not ('form-of' = any(s.labels))
                    )
                ) as expected_is_lemma
            from lexicon.lexeme lx
        ) computed
        where l.id = computed.id
          and l.is_lemma is distinct from computed.expected_is_lemma
        """
    )


def _prepare_staged_entries(conn: psycopg.Connection, source_file_id: int) -> int:
    """Copy compact projectable payloads into a transaction-local table."""

    conn.execute("drop table if exists tmp_kaikki_entry")
    conn.execute(
        """
        create temporary table tmp_kaikki_entry (
            source_document_id bigint primary key,
            lemma text not null,
            part_of_speech text not null,
            payload jsonb not null,
            lexeme_id bigint
        ) on commit preserve rows
        """
    )
    with connect() as read_conn:
        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_kaikki_entry (
                    source_document_id, lemma, part_of_speech, payload
                ) from stdin
                """
            ) as copy:
                last_document_id = 0
                while True:
                    rows = read_conn.execute(
                        """
                        select id, payload
                        from warehouse.source_document
                        where source_file_id = %s
                          and id > %s
                        order by id
                        limit 2000
                        """,
                        (source_file_id, last_document_id),
                    ).fetchall()
                    if not rows:
                        break
                    for document_id, payload in rows:
                        last_document_id = int(document_id)
                        if not isinstance(payload, dict) or not has_kaikki_projection_data(
                            payload
                        ):
                            continue
                        entry = compact_kaikki_entry(payload)
                        copy.write_row(
                            (
                                document_id,
                                entry["word"],
                                entry["pos"],
                                json.dumps(entry, ensure_ascii=False),
                            )
                        )
    row = conn.execute("select count(*) from tmp_kaikki_entry").fetchone()
    return int(row[0]) if row else 0


def _prepare_iterable_entries(conn: psycopg.Connection, entries: Iterable[dict]) -> int:
    """Copy an in-memory/streamed iterable of Kaikki entries into ``tmp_kaikki_entry``."""

    conn.execute("drop table if exists tmp_kaikki_entry")
    conn.execute(
        """
        create temporary table tmp_kaikki_entry (
            source_document_id bigint primary key,
            lemma text not null,
            part_of_speech text not null,
            payload jsonb not null,
            lexeme_id bigint
        ) on commit preserve rows
        """
    )
    with conn.cursor() as cursor:
        with cursor.copy(
            """
            copy tmp_kaikki_entry (
                source_document_id, lemma, part_of_speech, payload
            ) from stdin
            """
        ) as copy:
            synthetic_id = 0
            for raw in entries:
                if not isinstance(raw, dict):
                    continue
                if not raw.get("word") or not raw.get("pos"):
                    continue
                if not has_kaikki_projection_data(raw):
                    continue
                synthetic_id += 1
                entry = compact_kaikki_entry(raw)
                copy.write_row(
                    (
                        synthetic_id,
                        entry["word"],
                        entry["pos"],
                        json.dumps(entry, ensure_ascii=False),
                    )
                )
    row = conn.execute("select count(*) from tmp_kaikki_entry").fetchone()
    return int(row[0]) if row else 0


def _prepare_staged_form_keys(conn: psycopg.Connection) -> None:
    """Materialize the incoming form keys before replacing source ownership."""

    conn.execute("drop table if exists tmp_kaikki_form_key")
    conn.execute(
        """
        create temporary table tmp_kaikki_form_key (
            lexeme_id bigint not null,
            surface_form text not null,
            normalized_form text not null,
            features jsonb not null,
            primary key (lexeme_id, normalized_form, features)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_form_key (
            lexeme_id, surface_form, normalized_form, features
        )
        select
            e.lexeme_id,
            btrim(raw.form->>'form'),
            lower(btrim(raw.form->>'form')),
            coalesce(raw.form->'features', '{}'::jsonb)
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'forms', '[]'::jsonb)
        ) raw(form)
        where btrim(raw.form->>'form') <> ''
        on conflict do nothing
        """
    )
    conn.execute("analyze tmp_kaikki_form_key")
    conn.execute("drop table if exists tmp_kaikki_form_snapshot_key")
    conn.execute(
        """
        create temporary table tmp_kaikki_form_snapshot_key (
            lemma text not null,
            part_of_speech text not null,
            normalized_form text not null,
            features jsonb not null,
            primary key (lemma, part_of_speech, normalized_form, features)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_form_snapshot_key (
            lemma, part_of_speech, normalized_form, features
        )
        select l.lemma, l.part_of_speech, k.normalized_form, k.features
        from tmp_kaikki_form_key k
        join lexicon.lexeme l on l.id = k.lexeme_id
        on conflict do nothing
        """
    )
    conn.execute("analyze tmp_kaikki_form_snapshot_key")


def _clear_owned_forms_and_senses(
    conn: psycopg.Connection, source_file_id: int, replace_snapshot: bool
) -> None:
    """Clear source ownership while retaining rows shared by another source."""

    source_ids_sql = (
        sql.SQL(
            """
            select sf.id
            from warehouse.source_file sf
            join warehouse.source_registry sr on sr.id = sf.source_registry_id
            where sr.name = 'kaikki'
            """
        )
        if replace_snapshot
        else sql.SQL("select %s")
    )
    params: tuple[object, ...] = () if replace_snapshot else (source_file_id,)

    conn.execute("drop table if exists tmp_kaikki_sense_cleanup")
    conn.execute(
        """
        create temporary table tmp_kaikki_sense_cleanup (
            sense_id bigint primary key
        ) on commit preserve rows
        """
    )
    conn.execute(
        sql.SQL(
            """
            insert into tmp_kaikki_sense_cleanup (sense_id)
            select distinct sense_id
            from lexicon.sense_source
            where source_file_id in ({source_ids_sql})
            on conflict do nothing
            """
        ).format(source_ids_sql=source_ids_sql),
        params,
    )
    conn.execute(
        sql.SQL(
            """
            delete from lexicon.sense_source
            where source_file_id in ({source_ids_sql})
            """
        ).format(source_ids_sql=source_ids_sql),
        params,
    )

    conn.execute("drop table if exists tmp_kaikki_form_cleanup")
    conn.execute(
        """
        create temporary table tmp_kaikki_form_cleanup (
            form_id bigint primary key
        ) on commit preserve rows
        """
    )
    conn.execute(
        sql.SQL(
            """
            insert into tmp_kaikki_form_cleanup (form_id)
            select distinct ownership.form_id
            from lexicon.form_source ownership
            join lexicon.form f on f.id = ownership.form_id
            join lexicon.lexeme l on l.id = f.lexeme_id
            where ownership.source_file_id in ({source_ids_sql})
              and not exists (
                  select 1
                  from tmp_kaikki_form_snapshot_key incoming
                  where incoming.lemma = l.lemma
                    and incoming.part_of_speech = l.part_of_speech
                    and incoming.normalized_form = f.normalized_form
                    and incoming.features = f.features
              )
            on conflict do nothing
            """
        ).format(source_ids_sql=source_ids_sql),
        params,
    )
    conn.execute("analyze tmp_kaikki_form_cleanup")
    conn.execute(
        sql.SQL(
            """
            delete from lexicon.form_source ownership
            using tmp_kaikki_form_cleanup stale
            where ownership.form_id = stale.form_id
              and ownership.source_file_id in ({source_ids_sql})
            """
        ).format(source_ids_sql=source_ids_sql),
        params,
    )
    if replace_snapshot:
        conn.execute(
            sql.SQL(
                """
                delete from lexicon.form_source
                where source_file_id in ({source_ids_sql})
                  and source_file_id <> %s
                """
            ).format(source_ids_sql=source_ids_sql),
            (source_file_id,),
        )
    _delete_stale_forms_in_batches(conn)
    clear_kaikki_owned_rows(
        conn,
        source_file_id=source_file_id,
        replace_snapshot=replace_snapshot,
    )


def _delete_stale_forms_in_batches(conn: psycopg.Connection) -> int:
    """Delete stale forms in bounded statements instead of one huge cascade."""

    conn.execute("drop table if exists tmp_kaikki_form_batch")
    conn.execute(
        """
        create temporary table tmp_kaikki_form_batch (
            form_id bigint primary key
        ) on commit preserve rows
        """
    )
    deleted_total = 0
    last_form_id = 0
    while True:
        conn.execute("truncate tmp_kaikki_form_batch")
        conn.execute(
            """
            insert into tmp_kaikki_form_batch (form_id)
            select stale.form_id
            from tmp_kaikki_form_cleanup stale
            join lexicon.form f on f.id = stale.form_id
            where stale.form_id > %s
              and not exists (
                select 1
                from lexicon.form_source remaining
                where remaining.form_id = f.id
            )
            order by stale.form_id
            limit %s
            """,
            (last_form_id, _FORM_CLEANUP_BATCH_SIZE),
        )
        count_row = conn.execute("select count(*) from tmp_kaikki_form_batch").fetchone()
        batch_size = int(count_row[0]) if count_row else 0
        if batch_size == 0:
            break
        max_row = conn.execute("select max(form_id) from tmp_kaikki_form_batch").fetchone()
        last_form_id = int(max_row[0]) if max_row and max_row[0] is not None else last_form_id

        conn.execute(
            """
            delete from lexicon.form_validation validation
            using tmp_kaikki_form_batch batch
            where validation.form_id = batch.form_id
            """
        )
        conn.execute(
            """
            delete from lexicon.form form
            using tmp_kaikki_form_batch batch
            where form.id = batch.form_id
            """
        )
        deleted_total += batch_size
        if deleted_total % 100_000 < batch_size:
            print(
                f"[kaikki] deleted stale forms: {deleted_total}",
                flush=True,
                file=sys.stderr,
            )

    conn.execute("drop table tmp_kaikki_form_batch")
    return deleted_total
