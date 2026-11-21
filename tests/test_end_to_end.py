"""Seed every fixture source, refresh, and export both formats."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import psycopg

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.export import export_jsonl, export_sqlite
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
        self.assertEqual(rows["finnwordnet"], "WordNet AND CC-BY-3.0")
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
                fts_hits = db.execute(
                    "select lemma from lexeme_fts where lexeme_fts match 'juosta'"
                ).fetchall()
                summary_rows = db.execute(
                    "select lemma, is_lemma from v_lexeme_summary where lemma = 'juosta'"
                ).fetchall()
                tables = {
                    row[0]
                    for row in db.execute(
                        "select name from sqlite_master where type in ('table', 'view')"
                    ).fetchall()
                }
            finally:
                db.close()
        self.assertGreater(lexemes, 0)
        self.assertGreater(senses, 0)
        self.assertIn("kaikki", licenses)
        self.assertTrue(any(row[0] == "juosta" for row in fts_hits))
        self.assertEqual(summary_rows, [("juosta", 1)])
        self.assertTrue(
            {"grammar_note", "usage_warning", "v_lexeme_summary", "lexeme_fts"}.issubset(tables)
        )

    def test_export_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "fi.jsonl"
            self.assertEqual(main(["export-jsonl", "--output", str(output)]), 0)
            lines = output.read_text(encoding="utf-8").splitlines()
            pure_output = Path(temp_dir) / "fi-pure.jsonl"
            self.assertEqual(
                main(["export-jsonl", "--output", str(pure_output), "--pure-jsonl"]),
                0,
            )
            pure_lines = pure_output.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        entries = [json.loads(line) for line in lines[1:]]
        pure_entries = [json.loads(line) for line in pure_lines]
        self.assertIn("_sources", header)
        self.assertEqual(len(pure_entries), len(entries))
        self.assertTrue(all("lemma" in item for item in pure_entries))
        juosta = next(entry for entry in entries if entry["lemma"] == "juosta")
        self.assertTrue(juosta["senses"])
        self.assertTrue(juosta["forms"])
        for expected_field in (
            "display_lemma",
            "is_lemma",
            "etymology",
            "pronunciations",
            "relations",
            "derivations",
            "collocations",
            "topics",
        ):
            self.assertIn(expected_field, juosta)
        self.assertIn("notes", juosta["senses"][0])
        self.assertIn("warnings", juosta["senses"][0])

    def test_export_keeps_ambiguous_tatoeba_examples_at_headword(self):
        with tempfile.TemporaryDirectory() as temp_dir, psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute("""
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('esimerkkisana', 'esimerkkisana', 'noun') returning id
            """).fetchone()[0]
            sense_id = conn.execute("""
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en)
                values (%s, 'test-1', 'sample'), (%s, 'test-2', 'demonstration') returning id
            """, (lexeme_id, lexeme_id)).fetchone()[0]
            rows = conn.execute("""
                insert into lexicon.example (text_fi, source_label, quality_score)
                values ('Testiesimerkki.', 'tatoeba', 0.95), ('Lähde-esimerkki.', 'wiktionary', 0.95)
                returning id
            """).fetchall()
            conn.execute("""
                insert into lexicon.sense_example (sense_id, example_id, is_core)
                values (%s, %s, true), (%s, %s, true)
            """, (sense_id, rows[0][0], sense_id, rows[1][0]))

            sqlite_path = Path(temp_dir) / "export.sqlite"
            jsonl_path = Path(temp_dir) / "export.jsonl"
            export_sqlite(sqlite_path, connection=conn)
            export_jsonl(jsonl_path, connection=conn)
            conn.rollback()
            with sqlite3.connect(sqlite_path) as db:
                self.assertEqual(db.execute(
                    "select example_id, match_method from lexeme_example where lexeme_id = ?",
                    (lexeme_id,),
                ).fetchall(), [(rows[0][0], "inferred-headword")])
                self.assertEqual(db.execute(
                    "select example_id, match_method from sense_example where sense_id = ?",
                    (sense_id,),
                ).fetchall(), [(rows[1][0], "source-sense")])

            with jsonl_path.open(encoding="utf-8") as handle:
                entries = (json.loads(line) for line in handle)
                item = next(entry for entry in entries if entry.get("id") == lexeme_id)
            self.assertEqual(item["examples"][0]["match_method"], "inferred-headword")
            first = next(sense for sense in item["senses"] if sense["id"] == sense_id)
            self.assertEqual([example["match_method"] for example in first["examples"]], ["source-sense"])

    def test_export_refuses_to_overwrite_unless_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "fi.sqlite"
            output.write_text("keep")
            with self.assertRaises(FileExistsError):
                main(["export-sqlite", "--output", str(output)])
            self.assertEqual(output.read_text(), "keep")
            self.assertEqual(
                main(["export-sqlite", "--output", str(output), "--overwrite"]),
                0,
            )
            self.assertFalse(list(Path(temp_dir).glob(".*.part")))
