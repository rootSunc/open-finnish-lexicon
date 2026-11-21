"""Build a smaller SQLite dictionary from a full schema-v2 export."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from open_finnish_lexicon.export import EXPORT_SCHEMA_VERSION, _build_sqlite_views_and_fts


LEXEMES = "select id from selected_lexeme"
SENSES = "select id from sense"
EXAMPLES = "select example_id from sense_example union select example_id from lexeme_example"
SELECTED_OWNER = (
    f"(lexeme_id is null or lexeme_id in ({LEXEMES})) and "
    f"(sense_id is null or sense_id in ({SENSES})) and (lexeme_id is not null or sense_id is not null)"
)
TABLE_FILTERS = {
    "lexeme": f"id in ({LEXEMES})",
    "sense": f"lexeme_id in ({LEXEMES})",
    "form": f"lexeme_id in ({LEXEMES})",
    "pronunciation": f"lexeme_id in ({LEXEMES})",
    "sense_example": f"sense_id in ({SENSES})",
    "lexeme_example": f"lexeme_id in ({LEXEMES})",
    "example": f"id in ({EXAMPLES})",
    "relation": f"source_lexeme_id in ({LEXEMES}) and target_lexeme_id in ({LEXEMES})",
    "derivation": f"parent_lexeme_id in ({LEXEMES}) and child_lexeme_id in ({LEXEMES})",
    "collocation": SELECTED_OWNER,
    "topic": f"lexeme_id in ({LEXEMES}) and sense_id in ({SENSES})",
    "grammar_note": SELECTED_OWNER,
    "usage_warning": SELECTED_OWNER,
    "sense_source": f"sense_id in ({SENSES})",
    "zh_gloss": f"sense_id in ({SENSES})",
    "zh_example_translation": f"example_id in ({EXAMPLES})",
    "sources": "1",
}


def export_lite(source: Path, output: Path, max_rank: int) -> dict:
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".ofl-lite-") as scratch:
        stage = Path(scratch) / output.name
        with closing(sqlite3.connect(stage, uri=True)) as db:
            db.execute("attach database ? as full_db", (source.resolve().as_uri() + "?mode=ro",))
            version = db.execute("pragma full_db.user_version").fetchone()[0]
            if version != EXPORT_SCHEMA_VERSION:
                raise ValueError(f"expected schema {EXPORT_SCHEMA_VERSION}, found {version}")
            db.execute(f"pragma main.user_version = {EXPORT_SCHEMA_VERSION}")
            db.execute("create temp table selected_lexeme (id integer primary key)")
            db.execute("""
                insert into temp.selected_lexeme
                select id from full_db.lexeme where is_lemma = 1 and frequency_rank <= ?
            """, (max_rank,))
            definitions = dict(db.execute(
                "select name, sql from full_db.sqlite_master where type = 'table'"
            ))
            for table, where in TABLE_FILTERS.items():
                db.execute(definitions[table])
                db.execute(f'insert into main."{table}" select * from full_db."{table}" where {where}')
            build_id = None
            if "export_metadata" in definitions:
                db.execute(definitions["export_metadata"])
                db.execute("insert into main.export_metadata select * from full_db.export_metadata")
                build_id = db.execute("select build_id from main.export_metadata").fetchone()[0]
            db.execute("create table distribution_metadata (edition text not null, max_frequency_rank integer)")
            db.execute("insert into distribution_metadata values ('lite', ?)", (max_rank,))
            for table, definition in db.execute(
                "select tbl_name, sql from full_db.sqlite_master where type = 'index' and sql is not null"
            ).fetchall():
                if table in TABLE_FILTERS:
                    db.execute(definition)
            _build_sqlite_views_and_fts(db)
            db.execute("analyze main")
            counts = dict(db.execute("""
                select 'headwords', count(*) from main.lexeme
                union all select 'forms', count(*) from main.form
                union all select 'senses', count(*) from main.sense
            """))
            if not counts["headwords"]:
                raise ValueError("no headwords selected")
            if db.execute("pragma main.quick_check").fetchall() != [("ok",)]:
                raise ValueError("lite export failed quick_check")
            if db.execute("pragma main.foreign_key_check").fetchone():
                raise ValueError("lite export contains broken foreign keys")
            db.commit()
        output.hardlink_to(stage)
    return {
        "schema_version": version, "parent_build_id": build_id, "max_frequency_rank": max_rank,
        "counts": counts, "size_bytes": output.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-rank", required=True, type=int)
    args = parser.parse_args()
    if args.max_rank < 1:
        parser.error("--max-rank must be positive")
    try:
        print(json.dumps(export_lite(args.source, args.output, args.max_rank), indent=2))
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
