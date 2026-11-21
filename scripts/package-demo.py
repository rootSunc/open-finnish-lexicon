"""Package the example SQLite export as a static browser demo."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite", type=Path, help="SQLite export from examples/source_releases.toml")
    parser.add_argument("output", type=Path, help="Static demo directory")
    args = parser.parse_args()

    with closing(sqlite3.connect(args.sqlite.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("SELECT version FROM sources WHERE name = 'kaikki'").fetchone() != ("fixture-demo",):
            parser.error("build the SQLite export from examples/source_releases.toml first")
        db.row_factory = sqlite3.Row
        lookup = {}
        for row in db.execute("""
            SELECT lemma AS query, lemma, part_of_speech, primary_gloss_en AS gloss, NULL AS features
            FROM v_lexeme_summary WHERE is_lemma = 1
            UNION ALL
            SELECT f.surface_form, l.lemma, l.part_of_speech, l.primary_gloss_en, f.features
            FROM form AS f JOIN v_lexeme_summary AS l ON l.id = f.lexeme_id
            WHERE l.is_lemma = 1
            ORDER BY query, lemma, part_of_speech
        """):
            entry = dict(row)
            query = entry.pop("query")
            entry["features"] = json.loads(entry["features"]) if entry["features"] else {}
            lookup.setdefault(query, []).append(entry)

    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    for asset in (root / "examples" / "demo").iterdir():
        shutil.copyfile(asset, args.output / asset.name)
    shutil.copyfile(root / "LICENSE", args.output / "LICENSE")
    shutil.copyfile(args.sqlite, args.output / "sample.sqlite")
    (args.output / "sample-data.js").write_text(
        f"const sampleLookup = {json.dumps(lookup)};\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
