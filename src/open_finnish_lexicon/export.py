"""Export the lexicon and Chinese layer to SQLite or JSON Lines.

Both formats carry upstream source versions and licenses so the exported file
keeps its attribution, and both write via a temporary ``.part`` file followed
by an atomic rename so an interrupted export never leaves a half-written output.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import LiteralString
import warnings

import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.lookup import lookup_key

EXPORT_SCHEMA_VERSION = 2

# (sqlite table, column definitions, postgres select returning the same columns)
SQLITE_TABLES: tuple[tuple[str, str, LiteralString], ...] = (
    (
        "lexeme",
        "id integer primary key, lemma text not null, display_lemma text not null, "
        "part_of_speech text not null, frequency_rank integer, is_lemma integer not null default 1",
        "select id, lemma, display_lemma, part_of_speech, frequency_rank, "
        "case when is_lemma then 1 else 0 end from lexicon.lexeme order by id",
    ),
    (
        "sense",
        "id integer primary key, lexeme_id integer not null references lexeme(id), "
        "sense_key text, gloss_fi text, gloss_en text, labels text, sort_order integer",
        "select id, lexeme_id, sense_key, gloss_fi, gloss_en, array_to_json(labels)::text, sort_order "
        "from lexicon.lexeme_sense order by id",
    ),
    (
        "form",
        "id integer primary key, lexeme_id integer not null references lexeme(id), "
        "surface_form text not null, form_kind text, features text, validation text",
        "select f.id, f.lexeme_id, f.surface_form, f.form_kind, f.features::text, v.verdict "
        "from lexicon.form f left join lexicon.form_validation v on v.form_id = f.id order by f.id",
    ),
    (
        "pronunciation",
        "id integer primary key, lexeme_id integer not null references lexeme(id), "
        "ipa text, syllabification text",
        "select id, lexeme_id, ipa, syllabification from lexicon.pronunciation order by id",
    ),
    (
        "example",
        "id integer primary key, text_fi text not null, text_en text, "
        "source_label text, attribution text, provenance text",
        "select id, text_fi, text_en, source_label, attribution, provenance::text from lexicon.example order by id",
    ),
    (
        "sense_example",
        "sense_id integer not null references sense(id), "
        "example_id integer not null references example(id), sort_order integer, match_method text",
        "select sense_id, example_id, sort_order, match_method from lexicon.export_example_link "
        "where match_method <> 'inferred-headword' order by sense_id, sort_order, example_id",
    ),
    (
        "lexeme_example",
        "lexeme_id integer not null references lexeme(id), "
        "example_id integer not null references example(id), sort_order integer, match_method text",
        "select lexeme_id, example_id, min(sort_order), match_method from lexicon.export_example_link "
        "where match_method = 'inferred-headword' group by lexeme_id, example_id, match_method "
        "order by lexeme_id, min(sort_order), example_id",
    ),
    (
        "relation",
        "source_lexeme_id integer not null references lexeme(id), "
        "target_lexeme_id integer not null references lexeme(id), relation_type text",
        "select source_lexeme_id, target_lexeme_id, relation_type from lexicon.lexical_relation",
    ),
    (
        "derivation",
        "parent_lexeme_id integer not null references lexeme(id), "
        "child_lexeme_id integer not null references lexeme(id), relation_type text",
        "select parent_lexeme_id, child_lexeme_id, relation_type from lexicon.derivation_relation",
    ),
    (
        "collocation",
        "lexeme_id integer references lexeme(id), sense_id integer references sense(id), "
        "phrase text not null, score real",
        "select lexeme_id, sense_id, phrase, score::float8 from lexicon.collocation",
    ),
    (
        "topic",
        "lexeme_id integer not null references lexeme(id), sense_id integer references sense(id), "
        "topic_id text not null, label_en text, label_cn text",
        "select t.lexeme_id, t.sense_id, t.topic_id, tx.label_en, tx.label_cn "
        "from lexicon.lexeme_topic t join lexicon.topic_taxonomy tx on tx.id = t.topic_id "
        "where t.status = 'active'",
    ),
    (
        "grammar_note",
        "id integer primary key, lexeme_id integer references lexeme(id), "
        "sense_id integer references sense(id), note_fi text, note_en text, note_kind text not null",
        "select id, lexeme_id, sense_id, note_fi, note_en, note_kind from lexicon.grammar_note order by id",
    ),
    (
        "usage_warning",
        "id integer primary key, lexeme_id integer references lexeme(id), "
        "sense_id integer references sense(id), warning_fi text, warning_en text, warning_kind text not null",
        "select id, lexeme_id, sense_id, warning_fi, warning_en, warning_kind from lexicon.usage_warning order by id",
    ),
    (
        "sense_source",
        "sense_id integer not null references sense(id), source_name text not null, source_entry text not null",
        "select distinct ss.sense_id, sr.name, l.lemma from lexicon.sense_source ss "
        "join lexicon.lexeme_sense s on s.id = ss.sense_id join lexicon.lexeme l on l.id = s.lexeme_id "
        "join warehouse.source_file sf on sf.id = ss.source_file_id "
        "join warehouse.source_registry sr on sr.id = sf.source_registry_id "
        "where sf.snapshot_state = 'active' order by ss.sense_id, sr.name, l.lemma",
    ),
    (
        "zh_gloss",
        "sense_id integer not null references sense(id), gloss_zh text not null, method text, "
        "source_name text, source_entry text, confidence real",
        "select g.sense_id, g.gloss_zh, g.generation_method, "
        "case when g.generation_method = 'project-rule' then 'project_rules' else c.source_name end, "
        "case when g.generation_method <> 'project-rule' then d.external_id end, "
        "selection.confidence_score::float8 from zh_layer.zh_gloss g "
        "left join semantic.zh_gloss_selection selection "
        "on selection.target_sense_id = g.sense_id and selection.gloss_zh = g.gloss_zh "
        "left join semantic.zh_gloss_candidate c on c.id = selection.zh_gloss_candidate_id "
        "left join warehouse.source_document d on d.id = c.source_document_id "
        "where g.is_primary and g.gloss_zh is not null order by g.sense_id",
    ),
    (
        "zh_example_translation",
        "example_id integer not null references example(id), text_zh text not null, method text",
        "select example_id, text_zh, generation_method from zh_layer.zh_example_translation "
        "where is_primary and is_usable and btrim(text_zh) <> '' order by example_id",
    ),
    (
        "sources",
        "name text primary key, version text, source_url text, license text, sha256 text",
        "select sr.name, sf.source_version, "
        "case when sf.source_url like 'https://%' or sf.source_url like 'http://%' "
        "then sf.source_url end, sr.license, nullif(sf.checksum_sha256, '') "
        "from warehouse.source_registry sr "
        "join warehouse.source_file sf "
        "on sf.source_registry_id = sr.id and sf.snapshot_state = 'active' "
        "order by sr.name",
    ),
)

SQLITE_INDEXES: tuple[str, ...] = (
    "create index idx_lexeme_lemma on lexeme (lemma)",
    "create index idx_lexeme_lookup_key on lexeme (lookup_key)",
    "create index idx_lexeme_frequency on lexeme (frequency_rank) where frequency_rank is not null",
    "create index idx_sense_lexeme on sense (lexeme_id)",
    "create index idx_sense_source_sense on sense_source (sense_id)",
    "create index idx_form_lexeme on form (lexeme_id)",
    "create index idx_form_surface on form (surface_form)",
    "create index idx_form_lookup_key on form (lookup_key)",
    "create index idx_pronunciation_lexeme on pronunciation (lexeme_id)",
    "create index idx_sense_example_sense on sense_example (sense_id)",
    "create index idx_sense_example_example on sense_example (example_id)",
    "create index idx_lexeme_example_lexeme on lexeme_example (lexeme_id)",
    "create index idx_relation_source on relation (source_lexeme_id)",
    "create index idx_relation_target on relation (target_lexeme_id)",
    "create index idx_derivation_parent on derivation (parent_lexeme_id)",
    "create index idx_derivation_child on derivation (child_lexeme_id)",
    "create index idx_collocation_lexeme on collocation (lexeme_id)",
    "create index idx_collocation_sense on collocation (sense_id)",
    "create index idx_topic_lexeme on topic (lexeme_id)",
    "create index idx_grammar_note_lexeme on grammar_note (lexeme_id)",
    "create index idx_grammar_note_sense on grammar_note (sense_id)",
    "create index idx_usage_warning_sense on usage_warning (sense_id)",
    "create index idx_zh_gloss_sense on zh_gloss (sense_id)",
    "create index idx_zh_example_translation_example on zh_example_translation (example_id)",
)

BATCH_SIZE = 5000


def _build_sqlite_views_and_fts(target: sqlite3.Connection) -> None:
    target.execute(
        """
        create view v_lexeme_summary as
        select
            l.id,
            l.lemma,
            l.display_lemma,
            l.part_of_speech,
            l.frequency_rank,
            l.is_lemma,
            (select p.ipa from pronunciation p where p.lexeme_id = l.id order by p.id limit 1) as primary_ipa,
            primary_sense.gloss_en as primary_gloss_en,
            zg.gloss_zh as primary_gloss_zh
        from lexeme l
        left join sense primary_sense on primary_sense.id = (
            select s.id from sense s
            where s.lexeme_id = l.id and coalesce(s.gloss_en, s.gloss_fi) is not null
            order by (case when coalesce(s.labels, '') like '%"form-of"%' then 1 else 0 end), s.sort_order, s.id
            limit 1
        )
        left join zh_gloss zg on zg.sense_id = primary_sense.id
        """
    )
    try:
        target.execute(
            """
            create virtual table lexeme_fts using fts5(
                lexeme_id unindexed,
                lemma,
                display_lemma,
                part_of_speech unindexed,
                gloss_en,
                gloss_zh,
                tokenize = 'unicode61 remove_diacritics 2'
            )
            """
        )
        target.execute(
            """
            insert into lexeme_fts (lexeme_id, lemma, display_lemma, part_of_speech, gloss_en, gloss_zh)
            select
                l.id,
                l.lemma,
                l.display_lemma,
                l.part_of_speech,
                coalesce((
                    select group_concat(s.gloss_en, ' ; ')
                    from sense s
                    where s.lexeme_id = l.id and s.gloss_en is not null
                ), ''),
                coalesce((
                    select group_concat(zg.gloss_zh, ' ； ')
                    from sense s
                    join zh_gloss zg on zg.sense_id = s.id
                    where s.lexeme_id = l.id
                ), '')
            from lexeme l
            """
        )
    except sqlite3.OperationalError as exc:
        if str(exc) != "no such module: fts5":
            raise
        warnings.warn("SQLite was built without FTS5. The export uses regular indexes.", stacklevel=2)


def export_sqlite(
    output: Path,
    *,
    overwrite: bool = False,
    connection: psycopg.Connection | None = None,
    build_id: str | None = None,
) -> dict[str, int]:
    if output.exists() and not overwrite:
        raise FileExistsError(f"{output} already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output.with_name(f".{output.name}.part")
    temp_path.unlink(missing_ok=True)

    counts: dict[str, int] = {}
    target = sqlite3.connect(temp_path)
    try:
        target.execute("pragma journal_mode = memory")
        target.execute("pragma synchronous = off")
        target.execute("pragma temp_store = memory")
        target.execute(f"pragma user_version = {EXPORT_SCHEMA_VERSION}")
        if build_id is not None:
            target.execute("create table export_metadata (build_id text not null)")
            target.execute("insert into export_metadata values (?)", (build_id,))
        with connection_scope(connection) as conn:
            for table, columns, select_sql in SQLITE_TABLES:
                normalized_column = {"lexeme": 1, "form": 2}.get(table)
                if normalized_column is not None:
                    columns += ", lookup_key text not null"
                target.execute(f"create table {table} ({columns})")
                total = 0
                with conn.cursor(name=f"export_{table}") as cursor:
                    cursor.itersize = BATCH_SIZE
                    cursor.execute(select_sql)
                    assert cursor.description is not None
                    placeholders = ", ".join("?" * (len(cursor.description) + (normalized_column is not None)))
                    while rows := cursor.fetchmany(BATCH_SIZE):
                        if normalized_column is not None:
                            insert_rows = [(*row, lookup_key(row[normalized_column])) for row in rows]
                        else:
                            insert_rows = rows
                        target.executemany(f"insert into {table} values ({placeholders})", insert_rows)
                        total += len(rows)
                counts[table] = total
        for index_sql in SQLITE_INDEXES:
            target.execute(index_sql)
        _build_sqlite_views_and_fts(target)
        target.execute("analyze")
        target.commit()
        target.execute("pragma optimize")
        target.close()
        temp_path.replace(output)
    except BaseException:
        target.close()
        temp_path.unlink(missing_ok=True)
        raise
    return counts


_JSONL_SQL = """
select jsonb_build_object(
    'id', l.id,
    'lemma', l.lemma,
    'display_lemma', l.display_lemma,
    'is_lemma', l.is_lemma,
    'pos', l.part_of_speech,
    'frequency_rank', l.frequency_rank,
    'ipa', (
        select array_agg(p.ipa order by p.id)
        from lexicon.pronunciation p
        where p.lexeme_id = l.id and p.ipa is not null
    ),
    'pronunciations', coalesce((
        select jsonb_agg(jsonb_build_object(
            'ipa', p.ipa,
            'syllabification', p.syllabification
        ) order by p.id)
        from lexicon.pronunciation p
        where p.lexeme_id = l.id
    ), '[]'::jsonb),
    'etymology', (
        select gn.note_en
        from lexicon.grammar_note gn
        where gn.lexeme_id = l.id and gn.sense_id is null and gn.note_kind = 'etymology'
        order by gn.id
        limit 1
    ),
    'senses', coalesce((
        select jsonb_agg(jsonb_build_object(
            'id', s.id,
            'sense_key', s.sense_key,
            'gloss_en', s.gloss_en,
            'gloss_fi', s.gloss_fi,
            'gloss_zh', zg.gloss_zh,
            'gloss_zh_method', zg.generation_method,
            'gloss_zh_source', zg.provenance,
            'sources', coalesce((
                select jsonb_agg(distinct jsonb_build_object('name', sr.name, 'entry', l.lemma)
                                 order by jsonb_build_object('name', sr.name, 'entry', l.lemma))
                from lexicon.sense_source ss
                join warehouse.source_file sf on sf.id = ss.source_file_id and sf.snapshot_state = 'active'
                join warehouse.source_registry sr on sr.id = sf.source_registry_id
                where ss.sense_id = s.id
            ), '[]'::jsonb),
            'labels', s.labels,
            'notes', coalesce((
                select jsonb_agg(gn.note_en order by gn.id)
                from lexicon.grammar_note gn
                where gn.sense_id = s.id and gn.note_en is not null
            ), '[]'::jsonb),
            'warnings', coalesce((
                select jsonb_agg(uw.warning_en order by uw.id)
                from lexicon.usage_warning uw
                where uw.sense_id = s.id and uw.warning_en is not null
            ), '[]'::jsonb),
            'examples', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'fi', e.text_fi,
                    'en', e.text_en,
                    'zh', zet.text_zh,
                    'source', e.source_label,
                    'attribution', e.attribution,
                    'provenance', e.provenance,
                    'match_method', se.match_method
                ) order by se.sort_order, e.id)
                from lexicon.export_example_link se
                join lexicon.example e on e.id = se.example_id
                left join lateral (
                    select t.text_zh
                    from zh_layer.zh_example_translation t
                    where t.example_id = e.id
                      and t.is_primary
                      and t.is_usable
                      and btrim(t.text_zh) <> ''
                    order by t.id
                    limit 1
                ) zet on true
                where se.sense_id = s.id and se.match_method <> 'inferred-headword'
            ), '[]'::jsonb)
        ) order by s.sort_order, s.id)
        from lexicon.lexeme_sense s
        left join lateral (
            select g.gloss_zh, g.generation_method,
                   case
                       when g.generation_method = 'project-rule' then jsonb_build_object(
                           'name', 'project_rules', 'entry', null, 'confidence', selection.confidence_score
                       )
                       when c.id is not null then jsonb_build_object(
                           'name', c.source_name, 'entry', d.external_id, 'confidence', selection.confidence_score
                       )
                   end as provenance
            from zh_layer.zh_gloss g
            left join semantic.zh_gloss_selection selection
              on selection.target_sense_id = g.sense_id and selection.gloss_zh = g.gloss_zh
            left join semantic.zh_gloss_candidate c on c.id = selection.zh_gloss_candidate_id
            left join warehouse.source_document d on d.id = c.source_document_id
            where g.sense_id = s.id and g.is_primary
            order by g.id desc
            limit 1
        ) zg on true
        where s.lexeme_id = l.id
    ), '[]'::jsonb),
    'examples', coalesce((
        select jsonb_agg(jsonb_build_object(
            'fi', e.text_fi, 'en', e.text_en, 'zh', zet.text_zh, 'source', e.source_label,
            'attribution', e.attribution, 'provenance', e.provenance,
            'match_method', 'inferred-headword'
        ) order by link.sort_order, e.id)
        from (
            select se.example_id, min(se.sort_order) as sort_order
            from lexicon.export_example_link se
            where se.lexeme_id = l.id and se.match_method = 'inferred-headword'
            group by se.example_id
        ) link
        join lexicon.example e on e.id = link.example_id
        left join lateral (
            select t.text_zh from zh_layer.zh_example_translation t
            where t.example_id = e.id and t.is_primary and t.is_usable and btrim(t.text_zh) <> ''
            order by t.id limit 1
        ) zet on true
    ), '[]'::jsonb),
    'forms', coalesce((
        select jsonb_agg(jsonb_build_object(
            'form', f.surface_form,
            'form_kind', f.form_kind,
            'features', f.features,
            'validation', v.verdict
        ) order by f.id)
        from lexicon.form f
        left join lexicon.form_validation v on v.form_id = f.id
        where f.lexeme_id = l.id
    ), '[]'::jsonb),
    'relations', coalesce((
        select jsonb_agg(jsonb_build_object(
            'target_lexeme_id', r.target_lexeme_id,
            'target_lemma', tl.lemma,
            'type', r.relation_type
        ) order by r.relation_type, tl.lemma, r.id)
        from lexicon.lexical_relation r
        join lexicon.lexeme tl on tl.id = r.target_lexeme_id
        where r.source_lexeme_id = l.id
    ), '[]'::jsonb),
    'derivations', coalesce((
        select jsonb_agg(jsonb_build_object(
            'child_lexeme_id', dr.child_lexeme_id,
            'child_lemma', cl.lemma,
            'type', dr.relation_type
        ) order by cl.lemma, dr.id)
        from lexicon.derivation_relation dr
        join lexicon.lexeme cl on cl.id = dr.child_lexeme_id
        where dr.parent_lexeme_id = l.id
    ), '[]'::jsonb),
    'collocations', coalesce((
        select jsonb_agg(jsonb_build_object(
            'phrase', c.phrase,
            'sense_id', c.sense_id,
            'score', c.score::float8
        ) order by c.score desc, c.id)
        from lexicon.collocation c
        where c.lexeme_id = l.id
    ), '[]'::jsonb),
    'topics', coalesce((
        select jsonb_agg(jsonb_build_object(
            'topic_id', t.topic_id,
            'sense_id', t.sense_id,
            'label_en', tx.label_en,
            'label_cn', tx.label_cn
        ) order by t.confidence desc, t.id)
        from lexicon.lexeme_topic t
        join lexicon.topic_taxonomy tx on tx.id = t.topic_id
        where t.lexeme_id = l.id and t.status = 'active'
    ), '[]'::jsonb)
)::text
from lexicon.lexeme l
order by l.id
"""


def export_jsonl(
    output: Path,
    *,
    overwrite: bool = False,
    include_sources_header: bool = True,
    connection: psycopg.Connection | None = None,
    build_id: str | None = None,
) -> int:
    """Write one lexeme per line; by default the first line is a ``_sources`` header."""

    if output.exists() and not overwrite:
        raise FileExistsError(f"{output} already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output.with_name(f".{output.name}.part")
    temp_path.unlink(missing_ok=True)

    total = 0
    try:
        with connection_scope(connection) as conn, temp_path.open("w", encoding="utf-8") as handle:
            if include_sources_header:
                sources = conn.execute(SQLITE_TABLES[-1][2]).fetchall()
                header = {
                    "_sources": [
                        {"name": n, "version": v, "url": u, "license": lic, "sha256": checksum}
                        for n, v, u, lic, checksum in sources
                    ]
                }
                if build_id is not None:
                    header["_export"] = {"build_id": build_id, "schema_version": EXPORT_SCHEMA_VERSION}
                handle.write(json.dumps(header, ensure_ascii=False) + "\n")
            with conn.cursor(name="export_jsonl") as cursor:
                cursor.itersize = 2000
                cursor.execute(_JSONL_SQL)
                while rows := cursor.fetchmany(2000):
                    for (line,) in rows:
                        handle.write(line + "\n")
                    total += len(rows)
        temp_path.replace(output)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return total
