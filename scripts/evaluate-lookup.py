"""Measure lookup coverage and run small, hand-checked data regressions."""

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from open_finnish_lexicon.lookup import lookup, lookup_key


def evaluate(db: sqlite3.Connection, sample: dict) -> dict:
    tokens = Counter(
        lookup_key(token)
        for passage in sample["passages"]
        for token in re.findall(r"[^\W\d_]+", passage, flags=re.UNICODE)
    )
    missed = {word: count for word, count in tokens.items() if not lookup(db, word)}
    forms = []
    for case in sample["forms"]:
        found = [row["lemma"] for row in lookup(db, case["word"])]
        forms.append(case | {
            "actual": found, "ok": set(case["expected"]).issubset(found),
            "top1_ok": bool(found and found[0] in case["expected"]),
        })

    chinese = []
    for case in sample["chinese"]:
        glosses = [row[0] for row in db.execute("""
            select g.gloss_zh from lexeme l join sense s on s.lexeme_id = l.id
            join zh_gloss g on g.sense_id = s.id
            where l.lemma = ? and l.part_of_speech = ? and l.is_lemma = 1 and instr(s.gloss_en, ?) > 0
        """, (case["lemma"], case["pos"], case["sense"]))]
        chinese.append(case | {
            "actual": glosses, "covered": bool(glosses),
            "ok": any(expected in gloss for expected in case["expected"] for gloss in glosses),
        })

    examples = []
    version = db.execute("pragma user_version").fetchone()[0]
    for case in sample["exclude_from_senses"]:
        attached = [row[0] for row in db.execute("""
            select s.gloss_en from lexeme l join sense s on s.lexeme_id = l.id
            join sense_example se on se.sense_id = s.id
            join example e on e.id = se.example_id
            where l.lemma = ? and e.text_fi = ? and e.source_label = 'tatoeba'
        """, (case["lemma"], case["sentence"]))]
        retained = None if version == 1 else bool(db.execute("""
            select 1 from lexeme l join lexeme_example le on le.lexeme_id = l.id
            join example e on e.id = le.example_id
            where l.lemma = ? and e.text_fi = ? and le.match_method = 'inferred-headword'
        """, (case["lemma"], case["sentence"])).fetchone())
        examples.append(case | {"actual": attached, "retained_at_headword": retained,
                                "ok": not attached and retained is not False})

    return {
        "corpus": {
            "tokens": tokens.total(), "tokens_found": tokens.total() - sum(missed.values()),
            "types": len(tokens), "types_found": len(tokens) - len(missed), "missed": missed,
        },
        "forms": {"passed": sum(case["ok"] for case in forms), "top1": sum(case["top1_ok"] for case in forms),
                  "total": len(forms), "cases": forms},
        "chinese": {"covered": sum(case["covered"] for case in chinese),
                    "passed": sum(case["ok"] for case in chinese), "total": len(chinese), "cases": chinese},
        "example_regressions": {"passed": sum(case["ok"] for case in examples),
                                "total": len(examples), "cases": examples},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--sample", type=Path,
                        default=Path(__file__).resolve().parents[1] / "evaluation/fi-sample.json")
    parser.add_argument("--strict", action="store_true", help="Fail when a curated case does not pass")
    args = parser.parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        result = evaluate(db, sample)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and any(result[key]["passed"] != result[key]["total"]
                           for key in ("forms", "chinese", "example_regressions")):
        parser.exit(1)


if __name__ == "__main__":
    main()
