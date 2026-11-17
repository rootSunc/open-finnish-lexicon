"""Seed every fixture source, refresh, and export both formats."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import psycopg

from open_finnish_lexicon.cli import main
from support import get_test_database_url

DATA_TABLES = """
    lexicon.lexeme_topic_source, lexicon.lexeme_topic, lexicon.topic_taxonomy,
    lexicon.collocation, lexicon.sense_example, lexicon.example, lexicon.form_validation,
    lexicon.form_source, lexicon.form_analysis, lexicon.form, lexicon.pronunciation_source,
    lexicon.pronunciation, lexicon.lexical_relation_source, lexicon.lexical_relation,
    lexicon.derivation_relation_source, lexicon.derivation_relation, lexicon.frequency_signal,
    lexicon.grammar_note_source, lexicon.grammar_note, lexicon.usage_warning_source,
    lexicon.usage_warning, lexicon.sense_source, lexicon.lexeme_sense, lexicon.lexeme,
    zh_layer.zh_gloss, zh_layer.zh_example_translation, zh_layer.zh_note, zh_layer.zh_warning,
    semantic.zh_gloss_selection, semantic.zh_gloss_candidate, semantic.sense_alignment,
    semantic.sense_alignment_candidate, warehouse.source_claim, warehouse.source_document,
    warehouse.source_release, warehouse.source_file, warehouse.parser_run, warehouse.build_run,
    warehouse.source_registry
"""


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(f"truncate {DATA_TABLES} restart identity cascade")
            conn.commit()
        assert main(["seed-fixtures"]) == 0

    def test_sources_carry_licenses(self):
        with psycopg.connect(get_test_database_url()) as conn:
            rows = dict(conn.execute("select name, license from warehouse.source_registry").fetchall())
        self.assertEqual(rows["kaikki"], "CC-BY-SA-4.0 OR GFDL-1.3-or-later")
        self.assertEqual(rows["tatoeba"], "CC-BY-2.0-FR")
        self.assertNotIn("panlex", rows)

    def test_fixture_lexicon_is_populated(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexemes, senses, forms = conn.execute(
                """
                select (select count(*) from lexicon.lexeme),
                       (select count(*) from lexicon.lexeme_sense),
                       (select count(*) from lexicon.form)
                """
            ).fetchone()
            juosta = conn.execute(
                "select count(*) from lexicon.lexeme where lemma = 'juosta'"
            ).fetchone()[0]
        self.assertGreater(lexemes, 0)
        self.assertGreater(senses, 0)
        self.assertGreater(forms, 0)
        self.assertEqual(juosta, 1)

    def test_export_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "fi.sqlite"
            self.assertEqual(main(["export-sqlite", "--output", str(output)]), 0)
            db = sqlite3.connect(output)
            try:
                lexemes = db.execute("select count(*) from lexeme").fetchone()[0]
                senses = db.execute(
                    "select count(*) from sense join lexeme on lexeme.id = sense.lexeme_id "
                    "where lexeme.lemma = 'juosta'"
                ).fetchone()[0]
                licenses = dict(db.execute("select name, license from sources").fetchall())
            finally:
                db.close()
        self.assertGreater(lexemes, 0)
        self.assertGreater(senses, 0)
        self.assertIn("kaikki", licenses)

    def test_export_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "fi.jsonl"
            self.assertEqual(main(["export-jsonl", "--output", str(output)]), 0)
            lines = output.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        entries = [json.loads(line) for line in lines[1:]]
        self.assertIn("_sources", header)
        juosta = next(entry for entry in entries if entry["lemma"] == "juosta")
        self.assertTrue(juosta["senses"])
        self.assertTrue(juosta["forms"])

    def test_export_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "fi.sqlite"
            output.write_text("keep")
            with self.assertRaises(FileExistsError):
                main(["export-sqlite", "--output", str(output)])
            self.assertEqual(output.read_text(), "keep")
