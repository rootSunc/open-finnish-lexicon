"""Set-based projection of a staged Kaikki snapshot."""

from __future__ import annotations

from collections.abc import Iterable
import json
import sys

import psycopg
from psycopg import sql

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.senses import _delete_orphan_kaikki_senses
from open_finnish_lexicon.normalize.source_ownership import clear_kaikki_owned_rows
from open_finnish_lexicon.sources.kaikki_loader import (
    compact_kaikki_entry,
    has_kaikki_projection_data,
)

_FORM_CLEANUP_BATCH_SIZE = 10_000
KAIKKI_EXAMPLE_QUALITY = 0.70


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


def _upsert_lexemes(conn: psycopg.Connection) -> None:
    conn.execute("drop table if exists tmp_kaikki_lexeme_key")
    conn.execute(
        """
        create temporary table tmp_kaikki_lexeme_key (
            lemma text not null,
            part_of_speech text not null,
            primary key (lemma, part_of_speech)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_lexeme_key (lemma, part_of_speech)
        select lemma, part_of_speech from tmp_kaikki_entry
        on conflict do nothing
        """
    )
    conn.execute("drop table if exists tmp_kaikki_lexeme_map")
    conn.execute(
        """
        create temporary table tmp_kaikki_lexeme_map (
            lemma text not null,
            part_of_speech text not null,
            lexeme_id bigint not null,
            primary key (lemma, part_of_speech),
            unique (lexeme_id)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        with upserted as (
            insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
            select lemma, lemma, part_of_speech
            from tmp_kaikki_lexeme_key
            on conflict (lemma, part_of_speech) do update
            set display_lemma = excluded.display_lemma
            returning id, lemma, part_of_speech
        )
        insert into tmp_kaikki_lexeme_map (lemma, part_of_speech, lexeme_id)
        select lemma, part_of_speech, id
        from upserted
        """
    )
    conn.execute(
        """
        update tmp_kaikki_entry e
        set lexeme_id = m.lexeme_id
        from tmp_kaikki_lexeme_map m
        where m.lemma = e.lemma
          and m.part_of_speech = e.part_of_speech
        """
    )


def _upsert_senses(conn: psycopg.Connection, source_file_id: int | None) -> None:
    conn.execute("drop table if exists tmp_kaikki_sense_data")
    conn.execute(
        """
        create temporary table tmp_kaikki_sense_data (
            source_document_id bigint not null,
            lexeme_id bigint not null,
            sense_key text not null,
            gloss_en text not null,
            labels text[] not null,
            sort_order integer not null
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_sense_data (
            source_document_id, lexeme_id, sense_key, gloss_en, labels, sort_order
        )
        select
            e.source_document_id,
            e.lexeme_id,
            raw.sense->>'id',
            gloss.gloss_en,
            coalesce(
                (
                    select array_agg(tag.value order by tag.ordinality)
                    from jsonb_array_elements_text(
                        coalesce(raw.sense->'tags', '[]'::jsonb)
                    ) with ordinality as tag(value, ordinality)
                ),
                '{}'::text[]
            ),
            raw.ordinality::integer
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'senses', '[]'::jsonb)
        ) with ordinality as raw(sense, ordinality)
        cross join lateral (
            select string_agg(values.value, '; ' order by values.first_ord) as gloss_en
            from (
                select distinct on (lower(btrim(items.value)))
                    btrim(items.value) as value,
                    items.ordinality as first_ord
                from jsonb_array_elements_text(
                    coalesce(raw.sense->'glosses', '[]'::jsonb)
                ) with ordinality as items(value, ordinality)
                where btrim(items.value) <> ''
                order by lower(btrim(items.value)), items.ordinality
            ) values
        ) as gloss
        where btrim(raw.sense->>'id') <> ''
          and gloss.gloss_en is not null
        """
    )
    conn.execute("drop table if exists tmp_kaikki_sense_map")
    conn.execute(
        """
        create temporary table tmp_kaikki_sense_map (
            lexeme_id bigint not null,
            sense_key text not null,
            sense_id bigint not null,
            primary key (lexeme_id, sense_key)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        with deduped as (
            select distinct on (lexeme_id, sense_key)
                lexeme_id, sense_key, gloss_en, labels, sort_order
            from tmp_kaikki_sense_data
            order by lexeme_id, sense_key, source_document_id desc, sort_order desc
        ), upserted as (
            insert into lexicon.lexeme_sense (
                lexeme_id, sense_key, gloss_en, labels, sort_order
            )
            select lexeme_id, sense_key, gloss_en, labels, sort_order
            from deduped
            on conflict (lexeme_id, sense_key) do update
            set gloss_en = excluded.gloss_en,
                labels = excluded.labels,
                sort_order = excluded.sort_order
            returning id, lexeme_id, sense_key
        )
        insert into tmp_kaikki_sense_map (lexeme_id, sense_key, sense_id)
        select lexeme_id, sense_key, id
        from upserted
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.sense_source (sense_id, source_file_id)
            select sense_id, %s
            from tmp_kaikki_sense_map
            on conflict do nothing
            """,
            (source_file_id,),
        )
    conn.execute("drop table if exists tmp_kaikki_present_sense")
    conn.execute(
        """
        create temporary table tmp_kaikki_present_sense (
            lexeme_id bigint not null,
            sense_key text not null,
            primary key (lexeme_id, sense_key)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_present_sense (lexeme_id, sense_key)
        select lexeme_id, sense_key from tmp_kaikki_sense_map
        on conflict do nothing
        """
    )


def _upsert_forms(
    conn: psycopg.Connection, source_file_id: int | None, replace_snapshot: bool
) -> None:
    conn.execute(
        """
        insert into lexicon.form (
            lexeme_id, surface_form, normalized_form, form_kind, features
        )
        select lexeme_id, surface_form, normalized_form, 'kaikki', features
        from tmp_kaikki_form_key
        on conflict (lexeme_id, normalized_form, form_kind, features) do nothing
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.form_source (form_id, source_file_id)
            select f.id, %s
            from tmp_kaikki_form_key k
            join lexicon.form f
              on f.lexeme_id = k.lexeme_id
             and f.normalized_form = k.normalized_form
             and f.features = k.features
             and f.form_kind = 'kaikki'
            left join lexicon.form_source existing
              on existing.form_id = f.id
             and existing.source_file_id = %s
            where f.form_kind = 'kaikki'
              and existing.form_id is null
            """,
            (source_file_id, source_file_id),
        )
    if replace_snapshot and source_file_id is not None:
        conn.execute(
            """
            delete from lexicon.form f
            where f.form_kind = 'kaikki'
              and not exists (
                  select 1 from lexicon.form_source fs
                  where fs.form_id = f.id
              )
            """
        )


def _upsert_auxiliary_rows(conn: psycopg.Connection, source_file_id: int | None) -> None:
    conn.execute(
        """
        insert into lexicon.pronunciation (lexeme_id, ipa, syllabification, tts_voice)
        select distinct on (e.lexeme_id, btrim(s.sound->>'ipa'))
            e.lexeme_id,
            btrim(s.sound->>'ipa'),
            nullif(
                btrim(coalesce(s.sound->>'syllabification', e.payload->>'syllabification', '')),
                ''
            ),
            'fi'
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'sounds', '[]'::jsonb)
        ) with ordinality as s(sound, ord)
        where btrim(coalesce(s.sound->>'ipa', '')) <> ''
        order by e.lexeme_id, btrim(s.sound->>'ipa'), s.ord
        on conflict (lexeme_id, ipa) do update
        set syllabification = coalesce(
            excluded.syllabification,
            lexicon.pronunciation.syllabification
        )
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.pronunciation_source (pronunciation_id, source_file_id)
            select distinct p.id, %s
            from lexicon.pronunciation p
            join tmp_kaikki_entry e on e.lexeme_id = p.lexeme_id
            cross join lateral jsonb_array_elements(
                coalesce(e.payload->'sounds', '[]'::jsonb)
            ) s(sound)
            where p.tts_voice = 'fi'
              and p.ipa = btrim(s.sound->>'ipa')
            on conflict do nothing
            """,
            (source_file_id,),
        )
    conn.execute(
        """
        insert into lexicon.grammar_note (lexeme_id, note_en, note_kind)
        select distinct e.lexeme_id, btrim(e.payload->>'etymology_text'), 'etymology'
        from tmp_kaikki_entry e
        where btrim(e.payload->>'etymology_text') <> ''
        on conflict (lexeme_id, note_kind, note_en)
        where sense_id is null and note_en is not null
        do nothing
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.grammar_note_source (grammar_note_id, source_file_id)
            select distinct gn.id, %s
            from lexicon.grammar_note gn
            join tmp_kaikki_entry e
              on e.lexeme_id = gn.lexeme_id
             and gn.sense_id is null
             and gn.note_kind = 'etymology'
             and gn.note_en = btrim(e.payload->>'etymology_text')
            on conflict do nothing
            """,
            (source_file_id,),
        )
    conn.execute(
        """
        insert into lexicon.derivation_relation (
            parent_lexeme_id, child_lexeme_id, relation_type, note
        )
        select distinct on (e.lexeme_id, btrim(d.item->>'word'))
            e.lexeme_id,
            child.id,
            'derived-term',
            'kaikki-derived'
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'derived', '[]'::jsonb)
        ) d(item)
        join lexicon.lexeme child
          on child.lemma = btrim(d.item->>'word')
        where btrim(d.item->>'word') <> ''
        order by
            e.lexeme_id,
            btrim(d.item->>'word'),
            child.is_lemma desc,
            exists (
                select 1
                from lexicon.lexeme_sense ls
                where ls.lexeme_id = child.id
                  and coalesce(btrim(ls.gloss_en), '') <> ''
            ) desc,
            (child.part_of_speech = e.part_of_speech) desc,
            child.id
        on conflict (parent_lexeme_id, child_lexeme_id, relation_type, note) do nothing
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.derivation_relation_source (relation_id, source_file_id)
            select distinct dr.id, %s
            from lexicon.derivation_relation dr
            join tmp_kaikki_entry e on e.lexeme_id = dr.parent_lexeme_id
            cross join lateral jsonb_array_elements(
                coalesce(e.payload->'derived', '[]'::jsonb)
            ) d(item)
            join lexicon.lexeme child
              on child.lemma = btrim(d.item->>'word')
             and child.id = dr.child_lexeme_id
            where dr.relation_type = 'derived-term'
              and dr.note = 'kaikki-derived'
              and btrim(d.item->>'word') <> ''
            on conflict do nothing
            """,
            (source_file_id,),
        )
    conn.execute(
        """
        with incoming_relations as (
            select distinct on (e.lexeme_id, btrim(r.item->>'word'), btrim(r.item->>'type'))
                e.lexeme_id as source_lexeme_id,
                target.id as target_lexeme_id,
                btrim(r.item->>'type') as relation_type
            from tmp_kaikki_entry e
            cross join lateral jsonb_array_elements(
                coalesce(e.payload->'relations', '[]'::jsonb)
            ) r(item)
            join lexicon.lexeme target
              on target.lemma = btrim(r.item->>'word')
             and target.id <> e.lexeme_id
            where btrim(coalesce(r.item->>'word', '')) <> ''
              and btrim(coalesce(r.item->>'type', '')) <> ''
            order by
                e.lexeme_id,
                btrim(r.item->>'word'),
                btrim(r.item->>'type'),
                target.is_lemma desc,
                (target.part_of_speech = e.part_of_speech) desc,
                target.id
        )
        insert into lexicon.lexical_relation (
            source_lexeme_id, target_lexeme_id, relation_type, confidence
        )
        select inc.source_lexeme_id, inc.target_lexeme_id, inc.relation_type, 0.95
        from incoming_relations inc
        where not exists (
            select 1
            from lexicon.lexical_relation existing
            where existing.source_lexeme_id = inc.source_lexeme_id
              and existing.target_lexeme_id = inc.target_lexeme_id
              and existing.relation_type = inc.relation_type
        )
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.lexical_relation_source (relation_id, source_file_id)
            select distinct existing.id, %s
            from lexicon.lexical_relation existing
            join tmp_kaikki_entry e on e.lexeme_id = existing.source_lexeme_id
            cross join lateral jsonb_array_elements(
                coalesce(e.payload->'relations', '[]'::jsonb)
            ) r(item)
            join lexicon.lexeme target
              on target.id = existing.target_lexeme_id
             and target.lemma = btrim(r.item->>'word')
            where existing.relation_type = btrim(r.item->>'type')
            on conflict do nothing
            """,
            (source_file_id,),
        )


def _upsert_sense_metadata(conn: psycopg.Connection, source_file_id: int | None) -> None:
    conn.execute("drop table if exists tmp_kaikki_sense_text")
    conn.execute(
        """
        create temporary table tmp_kaikki_sense_text (
            sense_id bigint not null,
            text_en text not null,
            note_kind text not null,
            primary key (sense_id, text_en, note_kind)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_sense_text (sense_id, text_en, note_kind)
        select distinct sm.sense_id, btrim(raw.sense->>'note'), 'usage-note'
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'senses', '[]'::jsonb)
        ) raw(sense)
        join tmp_kaikki_sense_map sm
          on sm.lexeme_id = e.lexeme_id
         and sm.sense_key = raw.sense->>'id'
        where btrim(raw.sense->>'note') <> ''
        union
        select distinct sm.sense_id, btrim(raw.sense->>'qualifier'), 'usage-note'
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'senses', '[]'::jsonb)
        ) raw(sense)
        join tmp_kaikki_sense_map sm
          on sm.lexeme_id = e.lexeme_id
         and sm.sense_key = raw.sense->>'id'
        where btrim(raw.sense->>'qualifier') <> ''
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.grammar_note (sense_id, note_en, note_kind)
        select sense_id, text_en, note_kind
        from tmp_kaikki_sense_text
        on conflict (sense_id, note_kind, note_en)
        where lexeme_id is null and note_en is not null
        do nothing
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.grammar_note_source (grammar_note_id, source_file_id)
            select distinct gn.id, %s
            from lexicon.grammar_note gn
            join tmp_kaikki_sense_text t
              on t.sense_id = gn.sense_id
             and t.text_en = gn.note_en
             and t.note_kind = gn.note_kind
            on conflict do nothing
            """,
            (source_file_id,),
        )
    conn.execute("drop table if exists tmp_kaikki_warning")
    conn.execute(
        """
        create temporary table tmp_kaikki_warning (
            sense_id bigint not null,
            warning_en text not null,
            warning_kind text not null,
            primary key (sense_id, warning_en, warning_kind)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_warning (sense_id, warning_en, warning_kind)
        select distinct sm.sense_id, btrim(raw.sense->>'warning'), 'sense-warning'
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'senses', '[]'::jsonb)
        ) raw(sense)
        join tmp_kaikki_sense_map sm
          on sm.lexeme_id = e.lexeme_id
         and sm.sense_key = raw.sense->>'id'
        where btrim(raw.sense->>'warning') <> ''
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.usage_warning (sense_id, warning_en, warning_kind)
        select sense_id, warning_en, warning_kind
        from tmp_kaikki_warning
        on conflict (sense_id, warning_kind, warning_en)
        where lexeme_id is null and warning_en is not null
        do nothing
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.usage_warning_source (usage_warning_id, source_file_id)
            select distinct uw.id, %s
            from lexicon.usage_warning uw
            join tmp_kaikki_warning t
              on t.sense_id = uw.sense_id
             and t.warning_en = uw.warning_en
             and t.warning_kind = uw.warning_kind
            on conflict do nothing
            """,
            (source_file_id,),
        )
    conn.execute("drop table if exists tmp_kaikki_topic")
    conn.execute(
        """
        create temporary table tmp_kaikki_topic (
            lexeme_id bigint not null,
            sense_id bigint not null,
            topic_id text not null,
            label_en text not null,
            source_payload jsonb not null,
            primary key (lexeme_id, sense_id, topic_id)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_topic (
            lexeme_id, sense_id, topic_id, label_en, source_payload
        )
        select distinct
            e.lexeme_id,
            sm.sense_id,
            normalized.topic_id,
            initcap(replace(normalized.topic_id, '-', ' ')),
            jsonb_build_object('raw_topic', topics.value, 'sense_key', sm.sense_key)
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'senses', '[]'::jsonb)
        ) raw(sense)
        join tmp_kaikki_sense_map sm
          on sm.lexeme_id = e.lexeme_id
         and sm.sense_key = raw.sense->>'id'
        cross join lateral jsonb_array_elements_text(
            coalesce(raw.sense->'topics', '[]'::jsonb)
        ) topics(value)
        cross join lateral (
            select trim(
                both '-' from regexp_replace(lower(btrim(topics.value)), '[^a-z0-9]+', '-', 'g')
            ) as topic_id
        ) normalized
        where normalized.topic_id <> ''
        on conflict do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.topic_taxonomy (id, label_en, source)
        select topic_id, label_en, 'kaikki'
        from tmp_kaikki_topic
        on conflict (id) do nothing
        """
    )
    conn.execute(
        """
        insert into lexicon.lexeme_topic (
            lexeme_id, sense_id, topic_id, confidence, source, source_payload
        )
        select lexeme_id, sense_id, topic_id, 0.70000, 'kaikki-topic', source_payload
        from tmp_kaikki_topic
        on conflict (lexeme_id, sense_id, topic_id, source)
        where sense_id is not null
        do update set
            confidence = greatest(lexicon.lexeme_topic.confidence, excluded.confidence),
            source_payload = excluded.source_payload,
            status = 'active',
            updated_at = now()
        """
    )
    if source_file_id is not None:
        conn.execute(
            """
            insert into lexicon.lexeme_topic_source (lexeme_topic_id, source_file_id)
            select distinct lt.id, %s
            from lexicon.lexeme_topic lt
            join tmp_kaikki_topic t
              on t.lexeme_id = lt.lexeme_id
             and t.sense_id = lt.sense_id
             and t.topic_id = lt.topic_id
             and lt.source = 'kaikki-topic'
            on conflict do nothing
            """,
            (source_file_id,),
        )


def _write_kaikki_examples(conn: psycopg.Connection, tmp_table: str) -> None:
    table_ident = sql.Identifier(tmp_table)
    conn.execute(
        sql.SQL(
            """
            insert into lexicon.example (text_fi, text_en, source_label, quality_score)
            select distinct incoming.text_fi, incoming.text_en, 'kaikki', %s
            from {} incoming
            where not exists (
                select 1
                from lexicon.example existing
                where existing.source_label = 'kaikki'
                  and existing.text_fi = incoming.text_fi
            )
            """
        ).format(table_ident),
        (KAIKKI_EXAMPLE_QUALITY,),
    )
    conn.execute(
        sql.SQL(
            """
            update lexicon.example existing
            set text_en = incoming.text_en
            from {} incoming
            where existing.source_label = 'kaikki'
              and existing.text_fi = incoming.text_fi
              and existing.text_en is null
              and incoming.text_en is not null
            """
        ).format(table_ident)
    )
    conn.execute(
        sql.SQL(
            """
            insert into lexicon.sense_example (sense_id, example_id, is_core, sort_order)
            select incoming.sense_id, example.id, false, incoming.sort_order
            from {} incoming
            join lexicon.example example
              on example.source_label = 'kaikki'
             and example.text_fi = incoming.text_fi
            where not exists (
                select 1
                from lexicon.sense_example existing
                join lexicon.example existing_example on existing_example.id = existing.example_id
                where existing.sense_id = incoming.sense_id
                  and existing_example.text_fi = incoming.text_fi
            )
            on conflict (sense_id, example_id) do update
            set sort_order = least(lexicon.sense_example.sort_order, excluded.sort_order)
            """
        ).format(table_ident)
    )


def _upsert_examples(conn: psycopg.Connection) -> None:
    conn.execute("drop table if exists tmp_kaikki_example")
    conn.execute(
        """
        create temporary table tmp_kaikki_example (
            sense_id bigint not null,
            text_fi text not null,
            text_en text,
            sort_order integer not null,
            primary key (sense_id, text_fi)
        ) on commit preserve rows
        """
    )
    conn.execute(
        """
        insert into tmp_kaikki_example (sense_id, text_fi, text_en, sort_order)
        select distinct on (sm.sense_id, btrim(ex.example->>'text'))
            sm.sense_id,
            btrim(ex.example->>'text'),
            nullif(
                btrim(coalesce(ex.example->>'english', ex.example->>'english_text')),
                ''
            ),
            ex.ordinality::integer
        from tmp_kaikki_entry e
        cross join lateral jsonb_array_elements(
            coalesce(e.payload->'senses', '[]'::jsonb)
        ) raw(sense)
        join tmp_kaikki_sense_map sm
          on sm.lexeme_id = e.lexeme_id
         and sm.sense_key = raw.sense->>'id'
        cross join lateral jsonb_array_elements(
            coalesce(raw.sense->'examples', '[]'::jsonb)
        ) with ordinality as ex(example, ordinality)
        where btrim(coalesce(ex.example->>'text', '')) <> ''
        order by
            sm.sense_id,
            btrim(ex.example->>'text'),
            e.source_document_id desc,
            ex.ordinality
        on conflict do nothing
        """
    )
    _write_kaikki_examples(conn, "tmp_kaikki_example")


def _run_prepared_kaikki_projection(
    conn: psycopg.Connection,
    *,
    entry_count: int,
    source_file_id: int | None,
    replace_snapshot: bool,
    allow_empty_snapshot: bool,
) -> None:
    if replace_snapshot and source_file_id is None:
        raise ValueError("replace_snapshot requires a Kaikki source_file_id")
    if replace_snapshot and not allow_empty_snapshot and entry_count == 0:
        raise RuntimeError("refusing to replace Kaikki forms from an empty projected snapshot")

    if entry_count:
        _upsert_lexemes(conn)
    _prepare_staged_form_keys(conn)
    if source_file_id is not None:
        _clear_owned_forms_and_senses(conn, source_file_id, replace_snapshot)
    if entry_count == 0:
        if replace_snapshot and source_file_id is not None:
            conn.execute(
                """
                delete from lexicon.form f
                where f.form_kind = 'kaikki'
                  and not exists (
                      select 1 from lexicon.form_source fs
                      where fs.form_id = f.id
                  )
                """
            )
            _delete_orphan_kaikki_senses(conn)
            refresh_lexeme_is_lemma_flags(conn)
        return

    _upsert_senses(conn, source_file_id)
    refresh_lexeme_is_lemma_flags(conn)
    _upsert_examples(conn)
    _upsert_forms(conn, source_file_id, replace_snapshot)
    _upsert_auxiliary_rows(conn, source_file_id)
    _upsert_sense_metadata(conn, source_file_id)

    if source_file_id is not None:
        _delete_orphan_kaikki_senses(conn)
    refresh_lexeme_is_lemma_flags(conn)


def upsert_staged_kaikki_entries(
    conn: psycopg.Connection,
    *,
    source_file_id: int,
    replace_snapshot: bool,
    allow_empty_snapshot: bool = False,
) -> None:
    """Project one staged snapshot with bounded round trips."""

    entry_count = _prepare_staged_entries(conn, source_file_id)
    _run_prepared_kaikki_projection(
        conn,
        entry_count=entry_count,
        source_file_id=source_file_id,
        replace_snapshot=replace_snapshot,
        allow_empty_snapshot=allow_empty_snapshot,
    )


def upsert_kaikki_entry_iterable(
    conn: psycopg.Connection,
    entries: Iterable[dict],
    *,
    source_file_id: int | None = None,
    replace_snapshot: bool = False,
    allow_empty_snapshot: bool = False,
) -> None:
    """Project an iterable of Kaikki entries through the unified bulk projector."""

    entry_count = _prepare_iterable_entries(conn, entries)
    _run_prepared_kaikki_projection(
        conn,
        entry_count=entry_count,
        source_file_id=source_file_id,
        replace_snapshot=replace_snapshot,
        allow_empty_snapshot=allow_empty_snapshot,
    )
