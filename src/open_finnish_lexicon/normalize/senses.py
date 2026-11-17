from collections.abc import Iterable
from itertools import chain
import re

from psycopg.types.json import Jsonb

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.forms import normalize_surface_form
from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech
from open_finnish_lexicon.normalize.source_ownership import (
    clear_kaikki_owned_rows,
    link_source_row,
)
from open_finnish_lexicon.sources.kaikki_loader import has_kaikki_projection_data

KAIIKKI_PROJECT_FLUSH_INTERVAL = 500
KAIIKKI_TOPIC_CONFIDENCE = 0.70000


def _normalize_topic_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold())
    normalized = normalized.strip("-")
    return normalized or None


def _topic_label_en(topic_id: str) -> str:
    return " ".join(part.capitalize() for part in topic_id.split("-") if part)


def _sense_topic_rows(
    lexeme_id: int, sense_id: int, sense: dict
) -> list[tuple[str, str, int, int, float, str, Jsonb]]:
    topics = sense.get("topics")
    if not isinstance(topics, list):
        return []
    rows: list[tuple[str, str, int, int, float, str, Jsonb]] = []
    seen: set[str] = set()
    for raw_topic in topics:
        topic_id = _normalize_topic_id(raw_topic)
        if topic_id is None or topic_id in seen:
            continue
        seen.add(topic_id)
        rows.append(
            (
                topic_id,
                _topic_label_en(topic_id),
                lexeme_id,
                sense_id,
                KAIIKKI_TOPIC_CONFIDENCE,
                "kaikki-topic",
                Jsonb({"raw_topic": raw_topic, "sense_key": sense.get("id")}),
            )
        )
    return rows


def _sense_usage_notes(sense: dict) -> list[str]:
    notes: list[str] = []
    for value in [sense.get("note"), sense.get("qualifier")]:
        if isinstance(value, str):
            value = value.strip()
            if value and value not in notes:
                notes.append(value)
    return notes


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
            f"delete from {schema}.{table} where {column} in "
            "(select sense_id from tmp_kaikki_orphan_sense)"
        )
    conn.execute(
        """
        delete from lexicon.lexeme_sense
        where id in (select sense_id from tmp_kaikki_orphan_sense)
        """
    )


def _join_glosses(glosses: object) -> str | None:
    if not isinstance(glosses, list):
        return None

    values: list[str] = []
    seen: set[str] = set()
    for value in glosses:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        values.append(normalized)
    return "; ".join(values) or None


def upsert_kaikki_entries(
    entries: Iterable[dict],
    *,
    source_file_id: int | None = None,
    replace_snapshot: bool = False,
    allow_empty_snapshot: bool = False,
    connection=None,
) -> None:
    if replace_snapshot and source_file_id is None:
        raise ValueError("replace_snapshot requires a Kaikki source_file_id")
    if replace_snapshot and not allow_empty_snapshot:
        entries = iter(entries)
        first_entry = next(entries, None)
        if first_entry is None:
            raise RuntimeError("refusing to replace Kaikki forms from an empty projected snapshot")
        entries = chain((first_entry,), entries)
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        note_rows: list[tuple[int, str, str]] = []
        warning_rows: list[tuple[int, str, str]] = []
        topic_rows: list[tuple[str, str, int, int, float, str, Jsonb]] = []
        form_rows: list[tuple[int, str, str, Jsonb]] = []
        reset_form_lexeme_ids: list[int] = []
        reset_form_lexeme_id_set: set[int] = set()

        if source_file_id is not None:
            conn.execute(
                """
                create temporary table tmp_kaikki_form_batch (
                    lexeme_id bigint not null,
                    normalized_form text not null,
                    features jsonb not null,
                    primary key (lexeme_id, normalized_form, features)
                ) on commit preserve rows
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
                create temporary table tmp_kaikki_seen_lexeme (
                    lexeme_id bigint primary key
                ) on commit preserve rows
                """
            )
            conn.execute(
                """
                create temporary table tmp_kaikki_present_sense (
                    lexeme_id bigint not null,
                    sense_key text not null,
                    primary key (lexeme_id, sense_key)
                ) on commit preserve rows
                """
            )
            clear_kaikki_owned_rows(
                conn,
                source_file_id=source_file_id,
                replace_snapshot=replace_snapshot,
            )
            if replace_snapshot:
                conn.execute(
                    """
                    insert into tmp_kaikki_sense_cleanup (sense_id)
                    select ss.sense_id
                    from lexicon.sense_source ss
                    join warehouse.source_file sf on sf.id = ss.source_file_id
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'kaikki'
                    on conflict do nothing
                    """
                )
                conn.execute(
                    """
                    delete from lexicon.sense_source ss
                    using warehouse.source_file sf
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where ss.source_file_id = sf.id
                      and sr.name = 'kaikki'
                    """
                )
            else:
                conn.execute(
                    """
                    insert into tmp_kaikki_sense_cleanup (sense_id)
                    select sense_id
                    from lexicon.sense_source
                    where source_file_id = %s
                    on conflict do nothing
                    """,
                    (source_file_id,),
                )
            if replace_snapshot:
                conn.execute(
                    """
                    delete from lexicon.form_source fs
                    using warehouse.source_file sf
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where fs.source_file_id = sf.id
                      and sr.name = 'kaikki'
                    """
                )

        def flush_kaikki_forms() -> None:
            """Replace source-owned forms for the current batch atomically."""

            if reset_form_lexeme_ids:
                if source_file_id is None:
                    conn.execute(
                        """
                        delete from lexicon.form
                        where form_kind = 'kaikki'
                          and lexeme_id = any(%s)
                        """,
                        (reset_form_lexeme_ids,),
                    )
                else:
                    conn.execute(
                        """
                        delete from lexicon.form f
                        where f.form_kind = 'kaikki'
                          and f.lexeme_id = any(%s)
                          and exists (
                              select 1
                              from lexicon.form_source fs
                              where fs.form_id = f.id
                                and fs.source_file_id = %s
                          )
                        """,
                        (reset_form_lexeme_ids, source_file_id),
                    )
                reset_form_lexeme_ids.clear()
            if form_rows:
                with conn.cursor() as cursor:
                    if source_file_id is not None:
                        cursor.executemany(
                            """
                            insert into tmp_kaikki_form_batch (
                                lexeme_id, normalized_form, features
                            )
                            values (%s, %s, %s)
                            on conflict do nothing
                            """,
                            [
                                (lexeme_id, normalized_form, features)
                                for lexeme_id, _surface_form, normalized_form, features in form_rows
                            ],
                        )
                    cursor.executemany(
                        """
                        insert into lexicon.form (
                            lexeme_id, surface_form, normalized_form, form_kind, features
                        )
                        values (%s, %s, %s, 'kaikki', %s)
                        on conflict (lexeme_id, normalized_form, form_kind, features) do nothing
                        """,
                        form_rows,
                    )
                if source_file_id is not None:
                    conn.execute(
                        """
                        insert into lexicon.form_source (form_id, source_file_id)
                        select f.id, %s
                        from lexicon.form f
                        join tmp_kaikki_form_batch b
                          on b.lexeme_id = f.lexeme_id
                         and b.normalized_form = f.normalized_form
                         and b.features = f.features
                        where f.form_kind = 'kaikki'
                        on conflict do nothing
                        """,
                        (source_file_id,),
                    )
                    conn.execute("truncate tmp_kaikki_form_batch")
                form_rows.clear()

        for index, entry in enumerate(entries, start=1):
            part_of_speech = normalize_part_of_speech(entry["pos"])
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update set display_lemma = excluded.display_lemma
                returning id
                """,
                (entry["word"], entry["word"], part_of_speech),
            ).fetchone()[0]

            if source_file_id is not None:
                conn.execute(
                    """
                    insert into tmp_kaikki_seen_lexeme (lexeme_id)
                    values (%s)
                    on conflict do nothing
                    """,
                    (lexeme_id,),
                )

            if lexeme_id not in reset_form_lexeme_id_set:
                reset_form_lexeme_ids.append(lexeme_id)
                reset_form_lexeme_id_set.add(lexeme_id)

            if entry.get("sounds"):
                conn.execute(
                    """
                    insert into lexicon.pronunciation (lexeme_id, ipa, tts_voice)
                    values (%s, %s, %s)
                    on conflict do nothing
                    """,
                    (lexeme_id, entry["sounds"][0].get("ipa"), "fi"),
                )
                pronunciation_id = conn.execute(
                    """
                    select id
                    from lexicon.pronunciation
                    where lexeme_id = %s and ipa = %s
                    """,
                    (lexeme_id, entry["sounds"][0].get("ipa")),
                ).fetchone()[0]
                if source_file_id is not None:
                    link_source_row(
                        conn,
                        ownership_table="lexicon.pronunciation_source",
                        row_id_column="pronunciation_id",
                        row_id=pronunciation_id,
                        source_file_id=source_file_id,
                    )

            if entry.get("etymology_text"):
                conn.execute(
                    """
                    insert into lexicon.grammar_note (lexeme_id, note_en, note_kind)
                    values (%s, %s, %s)
                    on conflict (lexeme_id, note_kind, note_en)
                    where sense_id is null and note_en is not null
                    do nothing
                    """,
                    (lexeme_id, entry["etymology_text"], "etymology"),
                )
                grammar_note_id = conn.execute(
                    """
                    select id
                    from lexicon.grammar_note
                    where lexeme_id = %s
                      and sense_id is null
                      and note_en = %s
                      and note_kind = 'etymology'
                    """,
                    (lexeme_id, entry["etymology_text"]),
                ).fetchone()[0]
                if source_file_id is not None:
                    link_source_row(
                        conn,
                        ownership_table="lexicon.grammar_note_source",
                        row_id_column="grammar_note_id",
                        row_id=grammar_note_id,
                        source_file_id=source_file_id,
                    )

            for form in entry.get("forms", []):
                if not isinstance(form, dict):
                    continue
                surface_form = form.get("form")
                features = form.get("features")
                if not isinstance(surface_form, str) or not isinstance(features, dict):
                    continue
                form_rows.append(
                    (
                        lexeme_id,
                        surface_form,
                        normalize_surface_form(surface_form),
                        Jsonb(features),
                    )
                )
            for sort_order, sense in enumerate(entry.get("senses", []), start=1):
                gloss_en = _join_glosses(sense.get("glosses"))
                if gloss_en is None:
                    continue
                sense_id = conn.execute(
                    """
                    insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                    values (%s, %s, %s, %s, %s)
                    on conflict (lexeme_id, sense_key) do update
                    set gloss_en = excluded.gloss_en, labels = excluded.labels, sort_order = excluded.sort_order
                    returning id
                    """,
                    (
                        lexeme_id,
                        sense["id"],
                        gloss_en,
                        sense.get("tags", []),
                        sort_order,
                    ),
                ).fetchone()[0]

                if source_file_id is not None:
                    conn.execute(
                        """
                        insert into tmp_kaikki_present_sense (lexeme_id, sense_key)
                        values (%s, %s)
                        on conflict do nothing
                        """,
                        (lexeme_id, sense["id"]),
                    )
                    conn.execute(
                        """
                        insert into lexicon.sense_source (sense_id, source_file_id)
                        values (%s, %s)
                        on conflict do nothing
                        """,
                        (sense_id, source_file_id),
                    )

                for note_en in _sense_usage_notes(sense):
                    note_rows.append((sense_id, note_en, "usage-note"))

                if sense.get("warning"):
                    warning_rows.append((sense_id, sense["warning"], "sense-warning"))
                topic_rows.extend(_sense_topic_rows(lexeme_id, sense_id, sense))
            for item in entry.get("derived", []):
                child_row = conn.execute(
                    """
                    select id
                    from lexicon.lexeme child
                    where child.lemma = %s
                    order by
                      exists (
                        select 1
                        from lexicon.lexeme_sense ls
                        where ls.lexeme_id = child.id
                          and coalesce(btrim(ls.gloss_en), '') <> ''
                      ) desc,
                      (child.part_of_speech = %s) desc,
                      child.id
                    limit 1
                    """,
                    (item["word"], part_of_speech),
                ).fetchone()
                if child_row is None:
                    continue
                child_id = child_row[0]
                conn.execute(
                    """
                    insert into lexicon.derivation_relation (parent_lexeme_id, child_lexeme_id, relation_type, note)
                    values (%s, %s, %s, %s)
                    on conflict (parent_lexeme_id, child_lexeme_id, relation_type, note) do nothing
                    """,
                    (lexeme_id, child_id, "derived-term", "kaikki-derived"),
                )
                relation_id = conn.execute(
                    """
                    select id
                    from lexicon.derivation_relation
                    where parent_lexeme_id = %s
                      and child_lexeme_id = %s
                      and relation_type = 'derived-term'
                      and note = 'kaikki-derived'
                    """,
                    (lexeme_id, child_id),
                ).fetchone()[0]
                if source_file_id is not None:
                    link_source_row(
                        conn,
                        ownership_table="lexicon.derivation_relation_source",
                        row_id_column="relation_id",
                        row_id=relation_id,
                        source_file_id=source_file_id,
                    )

            with conn.cursor() as cursor:
                if note_rows:
                    cursor.executemany(
                        """
                        insert into lexicon.grammar_note (sense_id, note_en, note_kind)
                        values (%s, %s, %s)
                        on conflict (sense_id, note_kind, note_en)
                        where lexeme_id is null and note_en is not null
                        do nothing
                        """,
                        note_rows,
                    )
                    if source_file_id is not None:
                        for sense_id, note_en, note_kind in note_rows:
                            grammar_note_id = cursor.execute(
                                """
                                select id
                                from lexicon.grammar_note
                                where sense_id = %s
                                  and note_en = %s
                                  and note_kind = %s
                                """,
                                (sense_id, note_en, note_kind),
                            ).fetchone()[0]
                            link_source_row(
                                conn,
                                ownership_table="lexicon.grammar_note_source",
                                row_id_column="grammar_note_id",
                                row_id=grammar_note_id,
                                source_file_id=source_file_id,
                            )
                    note_rows.clear()
                if warning_rows:
                    cursor.executemany(
                        """
                        insert into lexicon.usage_warning (sense_id, warning_en, warning_kind)
                        values (%s, %s, %s)
                        on conflict (sense_id, warning_kind, warning_en)
                        where lexeme_id is null and warning_en is not null
                        do nothing
                        """,
                        warning_rows,
                    )
                    if source_file_id is not None:
                        for sense_id, warning_en, warning_kind in warning_rows:
                            usage_warning_id = cursor.execute(
                                """
                                select id
                                from lexicon.usage_warning
                                where sense_id = %s
                                  and warning_en = %s
                                  and warning_kind = %s
                                """,
                                (sense_id, warning_en, warning_kind),
                            ).fetchone()[0]
                            link_source_row(
                                conn,
                                ownership_table="lexicon.usage_warning_source",
                                row_id_column="usage_warning_id",
                                row_id=usage_warning_id,
                                source_file_id=source_file_id,
                            )
                    warning_rows.clear()
                if topic_rows:
                    cursor.executemany(
                        """
                        insert into lexicon.topic_taxonomy (id, label_en, source)
                        values (%s, %s, 'kaikki')
                        on conflict (id) do nothing
                        """,
                        [(topic_id, label_en) for topic_id, label_en, *_rest in topic_rows],
                    )
                    cursor.executemany(
                        """
                        insert into lexicon.lexeme_topic (
                            lexeme_id,
                            sense_id,
                            topic_id,
                            confidence,
                            source,
                            source_payload
                        )
                        values (%s, %s, %s, %s, %s, %s)
                        on conflict (lexeme_id, sense_id, topic_id, source)
                        where sense_id is not null
                        do update set
                            confidence = greatest(lexicon.lexeme_topic.confidence, excluded.confidence),
                            source_payload = excluded.source_payload,
                            status = 'active',
                            updated_at = now()
                        """,
                        [
                            (lexeme_id, sense_id, topic_id, confidence, source, source_payload)
                            for topic_id, _label_en, lexeme_id, sense_id, confidence, source, source_payload in topic_rows
                        ],
                    )
                    if source_file_id is not None:
                        for topic_id, _label_en, lexeme_id, sense_id, _confidence, source, _payload in topic_rows:
                            topic_row_id = cursor.execute(
                                """
                                select id
                                from lexicon.lexeme_topic
                                where lexeme_id = %s
                                  and sense_id = %s
                                  and topic_id = %s
                                  and source = %s
                                """,
                                (lexeme_id, sense_id, topic_id, source),
                            ).fetchone()[0]
                            link_source_row(
                                conn,
                                ownership_table="lexicon.lexeme_topic_source",
                                row_id_column="lexeme_topic_id",
                                row_id=topic_row_id,
                                source_file_id=source_file_id,
                            )
                    topic_rows.clear()
            if index % KAIIKKI_PROJECT_FLUSH_INTERVAL == 0:
                flush_kaikki_forms()
        flush_kaikki_forms()
        if source_file_id is not None and not replace_snapshot:
            conn.execute(
                """
                delete from lexicon.sense_source ss
                using lexicon.lexeme_sense ls
                join tmp_kaikki_seen_lexeme seen on seen.lexeme_id = ls.lexeme_id
                where ss.source_file_id = %s
                  and ss.sense_id = ls.id
                  and not exists (
                      select 1
                      from tmp_kaikki_present_sense present
                      where present.lexeme_id = ls.lexeme_id
                        and present.sense_key = ls.sense_key
                  )
                """,
                (source_file_id,),
            )
        if source_file_id is not None:
            _delete_orphan_kaikki_senses(conn)
        if replace_snapshot:
            conn.execute(
                """
                delete from lexicon.form f
                where f.form_kind = 'kaikki'
                  and not exists (
                      select 1
                      from lexicon.form_source fs
                      where fs.form_id = f.id
                  )
                """
            )
        if owns_connection:
            conn.commit()


def clear_kaikki_stale_data_for_non_projection_entries(
    entries: Iterable[dict] | None = None, *, source_file_id: int, connection=None
) -> None:
    """Remove source-owned data for valid Kaikki entries no longer projected.

    The compact projection intentionally skips entries without dictionary
    content. A later snapshot can still contain such an entry after its
    senses/forms disappear, so the skipped row must be able to clear its old
    Kaikki-owned data without creating an empty lexeme shell. Restrict every
    delete to this source file so an incremental import cannot remove data
    owned by another Kaikki snapshot.
    """

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        # The atomic Kaikki project may run this cleanup on the same
        # transaction as ``upsert_kaikki_entries``.  Those two routines use
        # similarly named scratch tables for different phases, so explicitly
        # reset the cleanup-owned tables before recreating them.
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
        if owns_connection:
            conn.commit()
