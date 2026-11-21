"""Read-only SQLite lookup. This module uses only the Python standard library."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import TypedDict
import unicodedata


def lookup_key(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text.strip()).casefold())


def lookup(db: sqlite3.Connection, word: str) -> list[dict]:
    exact = unicodedata.normalize("NFC", word.strip())
    key = lookup_key(exact)
    if not key:
        return []
    version = db.execute("pragma user_version").fetchone()[0]
    if version not in (1, 2):
        raise ValueError(f"unsupported SQLite schema version: {version}")
    if version == 2:
        lemma_filter, form_filter, arguments = "lookup_key = ?", "lookup_key = ?", (key, key)
    else:
        # The v1 export has exact indexes. Include both the original and normalized input.
        lemma_filter = "lemma in (?, ?)"
        form_filter = "surface_form in (?, ?)"
        arguments = (exact, key, exact, key)

    rows = db.execute(f"""
        WITH hits AS (
            SELECT id AS lexeme_id, lemma AS surface, 1 AS direct, NULL AS features, NULL AS validation
            FROM lexeme WHERE {lemma_filter} AND is_lemma = 1
            UNION ALL
            SELECT lexeme_id, surface_form, 0, features, validation FROM form WHERE {form_filter}
        )
        SELECT l.lemma, l.part_of_speech, l.primary_gloss_en, l.primary_gloss_zh,
               hits.surface, hits.direct, hits.features, hits.validation, l.id
        FROM hits JOIN v_lexeme_summary AS l ON l.id = hits.lexeme_id
        WHERE l.is_lemma = 1
        ORDER BY hits.direct DESC, hits.surface = ? DESC, l.frequency_rank IS NULL,
                 l.frequency_rank, l.lemma, l.part_of_speech, l.id, hits.features, hits.validation
    """, (*arguments, exact))
    results = {}
    for lemma, pos, en, zh, surface, direct, features, validation, lexeme_id in rows:
        entry = results.setdefault(lexeme_id, {
            "lemma": lemma, "part_of_speech": pos, "gloss_en": en, "gloss_zh": zh, "matches": [],
        })
        match = {"surface": surface, "headword": bool(direct),
                 "features": json.loads(features) if features else {}, "validation": validation}
        if match not in entry["matches"]:
            entry["matches"].append(match)
    return list(results.values())


class SenseReference(TypedDict):
    version: int
    lemma: str
    part_of_speech: str
    gloss_en: str


def sense_reference(db: sqlite3.Connection, sense_id: int) -> SenseReference:
    row = db.execute("""
        SELECT l.lemma, l.part_of_speech, s.gloss_en
        FROM sense s JOIN lexeme l ON l.id = s.lexeme_id WHERE s.id = ?
    """, (sense_id,)).fetchone()
    if row is None or not row[2]:
        raise ValueError("sense is missing or has no English gloss")
    return {"version": 1, "lemma": row[0], "part_of_speech": row[1], "gloss_en": row[2]}


def resolve_sense_reference(db: sqlite3.Connection, reference: SenseReference) -> dict:
    if reference["version"] != 1:
        raise ValueError("unsupported sense reference version")
    rows = db.execute("""
        SELECT s.id, s.gloss_en FROM lexeme l JOIN sense s ON s.lexeme_id = l.id
        WHERE l.lemma = ? AND l.part_of_speech = ? ORDER BY s.id
    """, (reference["lemma"], reference["part_of_speech"]))
    expected = lookup_key(" ".join(reference["gloss_en"].split()))
    ids = [sense_id for sense_id, gloss in rows if gloss and lookup_key(" ".join(gloss.split())) == expected]
    status = "matched" if len(ids) == 1 else "ambiguous" if ids else "unresolved"
    return {"status": status, "sense_ids": ids}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--save-sense", type=int, help="Write a portable reference for a numeric sense ID")
    mode.add_argument("--resolve-sense", type=Path, help="Resolve a saved reference in this snapshot")
    parser.add_argument("word", nargs="?")
    args = parser.parse_args()
    if sum(value is not None for value in (args.word, args.save_sense, args.resolve_sense)) != 1:
        parser.error("provide a word, --save-sense, or --resolve-sense")
    try:
        with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if args.save_sense is not None:
                result = sense_reference(db, args.save_sense)
            elif args.resolve_sense is not None:
                reference = json.loads(args.resolve_sense.read_text(encoding="utf-8"))
                result = resolve_sense_reference(db, reference)
            else:
                result = lookup(db, args.word)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
