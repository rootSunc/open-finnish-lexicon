"""``ofl build``: argument checks and a full run on the fixture manifest."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from open_finnish_lexicon.build import BuildOptions, build, output_format, report_path_for
from open_finnish_lexicon.cli import main
from test_end_to_end import DATA_TABLES

import psycopg
from support import get_test_database_url

FIXTURE_MANIFEST = "tests/fixtures/releases/test_source_releases.toml"


class BuildOptionTests(unittest.TestCase):
    def test_output_format_from_suffix(self):
        self.assertEqual(output_format(Path("a.sqlite")), "sqlite")
        self.assertEqual(output_format(Path("a.db")), "sqlite")
        self.assertEqual(output_format(Path("a.jsonl")), "jsonl")
        with self.assertRaises(ValueError):
            output_format(Path("a.csv"))

    def test_refuses_existing_output_before_touching_the_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "fi.sqlite"
            output.write_text("keep")
            with patch("open_finnish_lexicon.build.init_db") as init_db:
                with self.assertRaises(FileExistsError):
                    build(BuildOptions(output=output))
            init_db.assert_not_called()

    def test_refuses_unknown_format_before_touching_the_database(self):
        with patch("open_finnish_lexicon.build.init_db") as init_db:
            with self.assertRaises(ValueError):
                build(BuildOptions(output=Path("fi.csv")))
        init_db.assert_not_called()

    def test_skip_sync_runs_remaining_steps_in_order(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir, (
            patch("open_finnish_lexicon.build.init_db", side_effect=lambda: calls.append("init"))
        ), patch(
            "open_finnish_lexicon.build.sync_all", side_effect=lambda **_: calls.append("sync")
        ), patch(
            "open_finnish_lexicon.build.reconcile_lexemes", side_effect=lambda: calls.append("reconcile")
        ), patch(
            "open_finnish_lexicon.build.refresh_runtime_views", side_effect=lambda: calls.append("refresh")
        ), patch(
            "open_finnish_lexicon.build.export_jsonl", side_effect=lambda _p: calls.append("export")
        ):
            build(BuildOptions(output=Path(temp_dir) / "fi.jsonl", skip_sync=True, report=False))
        self.assertEqual(calls, ["init", "reconcile", "refresh", "export"])

    def test_cli_requires_output(self):
        with self.assertRaises(SystemExit):
            main(["build"])


class BuildFixtureRunTests(unittest.TestCase):
    def test_build_from_fixture_manifest(self):
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(f"truncate {DATA_TABLES} restart identity cascade")
            conn.commit()
        with (
            tempfile.TemporaryDirectory() as data_dir,
            tempfile.TemporaryDirectory() as out_dir,
            patch.dict(os.environ, {"OFL_DATA_DIR": data_dir}),
        ):
            output = Path(out_dir) / "release" / "fi.sqlite"
            exit_code = main(["build", "--output", str(output), "--manifest", FIXTURE_MANIFEST])

            self.assertEqual(exit_code, 0)
            db = sqlite3.connect(output)
            try:
                lexemes = db.execute("select count(*) from lexeme").fetchone()[0]
                sources = {row[0] for row in db.execute("select name from sources")}
            finally:
                db.close()
            report = json.loads(report_path_for(output).read_text(encoding="utf-8"))

        self.assertGreater(lexemes, 0)
        self.assertTrue({"kaikki", "tatoeba", "omorfi", "frequency"}.issubset(sources))
        self.assertEqual(
            list(report["build_steps_seconds"]),
            ["init-db", "sync", "reconcile", "refresh", "export"],
        )
        self.assertGreater(report["counts"]["lexicon.lexeme"], 0)
