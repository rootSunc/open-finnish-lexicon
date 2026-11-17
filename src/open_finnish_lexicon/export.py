"""Export the lexicon and Chinese layer to SQLite or JSON Lines.

Both formats carry a ``sources`` record with each upstream source's version
and license, so the exported file keeps its attribution.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from open_finnish_lexicon.db import connect

# (sqlite table, column definitions, postgres select returning the same columns)
SQLITE_TABLES: tuple[tuple[str, str, str], ...] = (
    (
        "lexeme",
        "id integer primary key, lemma text not null, display_lemma text not null, "
        "part_of_speech text not null, frequency_rank integer",
        "select id, lemma, display_lemma, part_of_speech, frequency_rank from lexicon.lexeme",
    ),
    (
        "sense",
        "id integer primary key, lexeme_id integer not null references lexeme(id), "
        "sense_key text, gloss_fi text, gloss_en text, labels text, sort_order integer",
        "select id, lexeme_id, sense_key, gloss_fi, gloss_en, array_to_json(labels)::text, sort_order "
        "from lexicon.lexeme_sense",
    ),
    (
        "form",
        "id integer primary key, lexeme_id integer not null references lexeme(id), "
        "surface_form text not null, form_kind text, features text, validation text",
        "select f.id, f.lexeme_id, f.surface_form, f.form_kind, f.features::text, v.verdict "
        "from lexicon.form f left join lexicon.form_validation v on v.form_id = f.id",
    ),
    (
        "pronunciation",
        "id integer primary key, lexeme_id integer not null references lexeme(id), "
        "ipa text, syllabification text",
        "select id, lexeme_id, ipa, syllabification from lexicon.pronunciation",
    ),
    (
        "example",
        "id integer primary key, text_fi text not null, text_en text, source_label text",
        "select id, text_fi, text_en, source_label from lexicon.example",
    ),
    (
        "sense_example",
        "sense_id integer not null references sense(id), "
        "example_id integer not null references example(id), sort_order integer",
        "select sense_id, example_id, sort_order from lexicon.sense_example",
    ),
    (
        "relation",
        "source_lexeme_id integer not null, target_lexeme_id integer not null, relation_type text",
        "select source_lexeme_id, target_lexeme_id, relation_type from lexicon.lexical_relation",
    ),
    (
        "derivation",
        "parent_lexeme_id integer not null, child_lexeme_id integer not null, relation_type text",
        "select parent_lexeme_id, child_lexeme_id, relation_type from lexicon.derivation_relation",
    ),
    (
        "collocation",
        "lexeme_id integer, sense_id integer, phrase text not null, score real",
        "select lexeme_id, sense_id, phrase, score::float8 from lexicon.collocation",
    ),
    (
        "topic",
        "lexeme_id integer not null, sense_id integer, topic_id text not null, label_en text",
        "select t.lexeme_id, t.sense_id, t.topic_id, tx.label_en "
        "from lexicon.lexeme_topic t join lexicon.topic_taxonomy tx on tx.id = t.topic_id",
    ),
    (
        "zh_gloss",
        "sense_id integer not null references sense(id), gloss_zh text not null, method text",
        "select sense_id, gloss_zh, generation_method from zh_layer.zh_gloss "
        "where is_primary and gloss_zh is not null",
    ),
    (
        "zh_example_translation",
        "example_id integer not null references example(id), text_zh text not null, method text",
        "select example_id, text_zh, generation_method from zh_layer.zh_example_translation "
        "where is_primary and btrim(text_zh) <> ''",
    ),
    (
        "sources",
        "name text primary key, version text, source_url text, license text",
        "select sr.name, coalesce(sf.source_version, sr.version), coalesce(sf.source_url, sr.source_url), "
        "sr.license from warehouse.source_registry sr left join warehouse.source_file sf "
        "on sf.source_registry_id = sr.id and sf.snapshot_state = 'active'",
    ),
)

BATCH_SIZE = 5000


def export_sqlite(output: Path) -> dict[str, int]:
    if output.exists():
        raise FileExistsError(f"{output} already exists")
    counts: dict[str, int] = {}
    target = sqlite3.connect(output)
    try:
        with connect() as conn:
            for table, columns, select_sql in SQLITE_TABLES:
                target.execute(f"create table {table} ({columns})")
                total = 0
                with conn.cursor(name=f"export_{table}") as cursor:
                    cursor.execute(select_sql)
                    rows = cursor.fetchmany(BATCH_SIZE)
                    placeholders = ", ".join("?" * len(cursor.description))
                    while rows:
                        target.executemany(f"insert into {table} values ({placeholders})", rows)
                        total += len(rows)
                        rows = cursor.fetchmany(BATCH_SIZE)
                counts[table] = total
        target.execute("create index idx_sense_lexeme on sense (lexeme_id)")
        target.execute("create index idx_form_lexeme on form (lexeme_id)")
        target.execute("create index idx_form_surface on form (surface_form)")
        target.execute("create index idx_lexeme_lemma on lexeme (lemma)")
        target.commit()
    finally:
        target.close()
    return counts


_JSONL_SQL = """
select jsonb_build_object(
    'id', l.id,
    'lemma', l.lemma,
    'pos', l.part_of_speech,
    'frequency_rank', l.frequency_rank,
    'ipa', (select array_agg(p.ipa order by p.id) from lexicon.pronunciation p
            where p.lexeme_id = l.id and p.ipa is not null),
    'senses', coalesce((
        select jsonb_agg(jsonb_build_object(
            'id', s.id,
            'gloss_en', s.gloss_en,
            'gloss_fi', s.gloss_fi,
            'gloss_zh', (select g.gloss_zh from zh_layer.zh_gloss g
                         where g.sense_id = s.id and g.is_primary limit 1),
            'labels', s.labels,
            'examples', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'fi', e.text_fi,
                    'en', e.text_en,
                    'zh', (select t.text_zh from zh_layer.zh_example_translation t
                           where t.example_id = e.id and t.is_primary
                             and btrim(t.text_zh) <> '' limit 1),
                    'source', e.source_label
                ) order by se.sort_order, e.id)
                from lexicon.sense_example se
                join lexicon.example e on e.id = se.example_id
                where se.sense_id = s.id
            ), '[]'::jsonb)
        ) order by s.sort_order, s.id)
        from lexicon.lexeme_sense s where s.lexeme_id = l.id
    ), '[]'::jsonb),
    'forms', coalesce((
        select jsonb_agg(jsonb_build_object(
            'form', f.surface_form,
            'features', f.features,
            'validation', v.verdict
        ) order by f.id)
        from lexicon.form f
        left join lexicon.form_validation v on v.form_id = f.id
        where f.lexeme_id = l.id
    ), '[]'::jsonb)
)::text
from lexicon.lexeme l
order by l.id
"""


def export_jsonl(output: Path) -> int:
    """Write one lexeme per line; the first line is a ``_sources`` header."""

    if output.exists():
        raise FileExistsError(f"{output} already exists")
    total = 0
    with connect() as conn, output.open("w", encoding="utf-8") as handle:
        sources = conn.execute(SQLITE_TABLES[-1][2]).fetchall()
        header = {
            "_sources": [
                {"name": n, "version": v, "url": u, "license": lic} for n, v, u, lic in sources
            ]
        }
        handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        with conn.cursor(name="export_jsonl") as cursor:
            cursor.execute(_JSONL_SQL)
            while rows := cursor.fetchmany(1000):
                for (line,) in rows:
                    handle.write(line + "\n")
                total += len(rows)
    return total
