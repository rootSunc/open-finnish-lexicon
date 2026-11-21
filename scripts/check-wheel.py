"""Smoke-test an installed OFL wheel against an empty PostgreSQL demo database."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory

from open_finnish_lexicon.lookup import lookup, resolve_sense_reference, sense_reference


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ofl = Path(sys.executable).with_name("ofl")
    with TemporaryDirectory(prefix="ofl-wheel-") as scratch:
        work = Path(scratch)
        env = os.environ | {"OFL_PROFILE": "fixture", "OFL_DATA_DIR": str(work / "data")}
        subprocess.run([ofl, "--version"], cwd=work, env=env, check=True)
        subprocess.run(
            [ofl, "build", "--manifest", "examples/source_releases.toml", "--output", work / "demo.sqlite"],
            cwd=root,
            env=env,
            check=True,
        )
        dist = work / "release"
        subprocess.run(
            [ofl, "package-release", "--dist-dir", dist, "--level", "1", "--pure-jsonl",
             "--remove-uncompressed"],
            cwd=work,
            env=env,
            check=True,
        )
        for line in (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            checksum, name = line.split("  ", 1)
            with (dist / name).open("rb") as handle:
                assert hashlib.file_digest(handle, "sha256").hexdigest() == checksum

        manifest = json.loads((dist / "release-manifest.json").read_text(encoding="utf-8"))
        assert manifest["snapshot"]["profile"] == "fixture"
        assert manifest["summary"]["counts"]["lexicon.lexeme"] == 7
        assert manifest["summary"]["sources"][0]["assets"][0]["sha256"]
        assert (dist / "DATA-NOTICE.md").is_file()
        assert not (dist / "fi.sqlite").exists()

        sqlite_path = work / "unpacked.sqlite"
        with sqlite_path.open("wb") as handle:
            subprocess.run(["zstd", "-dc", dist / "fi.sqlite.zst"], stdout=handle, check=True)
        with closing(sqlite3.connect(sqlite_path)) as db:
            assert db.execute("pragma quick_check").fetchall() == [("ok",)]
            query = (root / "examples" / "lookup.sql").read_text(encoding="utf-8")
            form, homograph, source = query.strip().rstrip(";").split(";")
            assert db.execute(form).fetchall() == [("juoksen", "juosta", "verb", "verified")]
            assert db.execute(homograph).fetchall() == [
                ("kuusi", "noun", "spruce tree"), ("kuusi", "num", "six"),
            ]
            assert db.execute(source).fetchall() == [("to run", "kaikki", "juosta", "fixture-demo")]
            assert lookup(db, "KA\u0308DESSA\u0308")[0]["lemma"] == "käsi"
            assert {row["lemma"] for row in lookup(db, "tulin")} == {"tuli", "tulla"}
            sense_id = db.execute("select id from sense where gloss_en = 'hand'").fetchone()[0]
            reference = sense_reference(db, sense_id)

        output = subprocess.check_output(["zstd", "-dc", dist / "fi.jsonl.zst"], text=True)
        rows = [json.loads(line) for line in output.splitlines()]
        assert sorted(row["lemma"] for row in rows) == [
            "juosta", "kuusi", "kuusi", "käsi", "talo", "tuli", "tulla",
        ]

        demo = work / "demo-site"
        subprocess.run([sys.executable, root / "scripts/package-demo.py", sqlite_path, demo], check=True)
        assert (demo / "sample.sqlite").read_bytes() == sqlite_path.read_bytes()
        script = (demo / "sample-data.js").read_text(encoding="utf-8").strip()
        sample_lookup = json.loads(script.removeprefix("const sampleLookup = ").removesuffix(";"))
        assert [entry["lemma"] for entry in sample_lookup["tulin"]] == ["tuli", "tulla"]
        assert sample_lookup["kädessä"][0]["features"]["case"] == "inessive"

        with closing(sqlite3.connect(sqlite_path)) as db:
            db.execute("update lexeme set frequency_rank = 1 where lemma = 'käsi'")
            db.commit()
        lite = work / "fi-lite.sqlite"
        subprocess.run([sys.executable, root / "scripts/export-lite.py", sqlite_path, lite,
                        "--max-rank", "1"], check=True)
        with closing(sqlite3.connect(lite)) as db:
            assert db.execute("select lemma from lexeme").fetchall() == [("käsi",)]
            assert db.execute("pragma foreign_key_check").fetchall() == []
            assert resolve_sense_reference(db, reference) == {"status": "matched", "sense_ids": [sense_id]}
            db.execute("update sense set id = ?", (sense_id + 100,))
            assert resolve_sense_reference(db, reference) == {
                "status": "matched", "sense_ids": [sense_id + 100],
            }


if __name__ == "__main__":
    main()
