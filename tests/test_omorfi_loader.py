import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.normalize.forms import normalize_surface_form
from open_finnish_lexicon.sources.omorfi_loader import (
    OmorfiRow,
    find_omorfi_generation_models,
    generate_omorfi_paradigm_rows,
    read_omorfi_rows,
)
from support import get_test_database_url


class OmorfiLoaderTests(unittest.TestCase):
    def test_normalize_surface_form_is_case_insensitive(self):
        self.assertEqual(normalize_surface_form("  JuOkSeN  "), "juoksen")
        self.assertEqual(normalize_surface_form("ÄITI"), "äiti")
        self.assertEqual(normalize_surface_form("Straße"), "strasse")

    def test_read_omorfi_rows_drops_affix_placeholders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "omorfi.tsv"
            input_path.write_text(
                "-lainen\tlainen\tADJ\t{}\n"
                "suomalainen\tsuomalainen\tADJ\t{}\n"
                "suomi-kieli\tsuomi-kieli\tNOUN\t{}\n"
                "lainen-\tlainen\tADJ\t{}\n"
            )

            rows = read_omorfi_rows(input_path)

        self.assertEqual(
            [row.surface_form for row in rows], ["suomalainen", "suomi-kieli"]
        )

    def test_find_omorfi_generation_models_requires_a_matching_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "releases/omorfi/0.9.11/unpacked").mkdir(parents=True)
            (data_dir / "releases/omorfi/0.9.12/unpacked").mkdir(parents=True)
            (data_dir / "releases/omorfi/0.9.11/unpacked/omorfi.generate.hfst").touch()
            (data_dir / "releases/omorfi/0.9.11/unpacked/omorfi.analyse.hfst").touch()
            (data_dir / "releases/omorfi/0.9.12/unpacked/omorfi.generate.hfst").touch()

            self.assertEqual(
                find_omorfi_generation_models(data_dir),
                (
                    data_dir / "releases/omorfi/0.9.11/unpacked/omorfi.generate.hfst",
                    data_dir / "releases/omorfi/0.9.11/unpacked/omorfi.analyse.hfst",
                ),
            )

    @unittest.skipUnless(importlib.util.find_spec("omorfi"), "needs the [omorfi] extra")
    def test_omorfi_generation_keeps_only_analyser_verified_cells(self):
        class FakeAnalysis:
            lemmas = ["talo"]
            upos = "NOUN"
            ufeats = {"Number": "Sing", "Case": "Nom"}

        class FakeOmorfi:
            def load_generator(self, _path):
                return None

            def load_analyser(self, _path):
                return None

            def generate(self, raw):
                return "talo" if "[CASE=NOM]" in raw and "[NUM=SG]" in raw else []

            def analyse(self, surface_form):
                return [FakeAnalysis()] if surface_form == "talo" else []

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            unpacked = data_dir / "releases/omorfi/0.9.12/unpacked"
            unpacked.mkdir(parents=True)
            (unpacked / "omorfi.generate.hfst").touch()
            (unpacked / "omorfi.analyse.hfst").touch()
            with patch("omorfi.omorfi.Omorfi", FakeOmorfi):
                rows = generate_omorfi_paradigm_rows(
                    [(7, "talo", "noun", ()), (8, "juosta", "verb", ())],
                    data_dir=data_dir,
                )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 7)
        self.assertEqual(rows[0][1].surface_form, "talo")
        self.assertEqual(rows[0][1].features, {"Number": "Sing", "Case": "Nom"})

    def test_omorfi_loader_populates_forms_and_analyses(self):
        exit_code = main(["ingest-omorfi", "--input", "tests/fixtures/omorfi.tsv"])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme = conn.execute(
                "select id from lexicon.lexeme where lemma = 'juosta' and part_of_speech = 'verb'"
            ).fetchone()
            self.assertIsNotNone(lexeme)

            fixture_rows = read_omorfi_rows(Path("tests/fixtures/omorfi.tsv"))
            expected_forms = {
                (
                    row.surface_form,
                    row.lemma,
                    row.part_of_speech,
                    json.dumps(row.features, ensure_ascii=False, sort_keys=True),
                )
                for row in fixture_rows
            }
            forms = conn.execute(
                """
                select f.surface_form, l.lemma, l.part_of_speech, f.features
                from lexicon.form f
                join lexicon.lexeme l on l.id = f.lexeme_id
                where f.form_kind = 'omorfi'
                """
            ).fetchall()
            actual_forms = {
                (
                    row[0],
                    row[1],
                    row[2],
                    json.dumps(row[3], ensure_ascii=False, sort_keys=True),
                )
                for row in forms
            }
            self.assertEqual(actual_forms, expected_forms)

            analyses = conn.execute(
                "select normalized_query from lexicon.form_analysis where normalized_query = 'juoksen'"
            ).fetchall()
            document_count = conn.execute(
                "select count(*) from warehouse.source_document where external_id like 'omorfi:%'"
            ).fetchone()[0]
            self.assertEqual(len(analyses), 1)
            self.assertGreaterEqual(document_count, 2)

    def test_omorfi_loader_supports_real_hfst_model_and_example_tokens(self):
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(
                """
                insert into lexicon.example (text_fi, text_en, source_label, quality_score)
                values (%s, %s, %s, %s)
                """,
                ("Zorblaan nopeasti.", None, "fixture", 1.0),
            )
            conn.commit()

        captured_tokens: list[str] = []

        def fake_analyse_omorfi_model_rows(_input_path: Path, candidate_tokens: list[str]) -> list[OmorfiRow]:
            captured_tokens.extend(candidate_tokens)
            return [
                OmorfiRow(
                    surface_form="zorblaan",
                    lemma="zorbla",
                    part_of_speech="verb",
                    features={
                        "Voice": "Act",
                        "VerbForm": "Fin",
                        "Mood": "Ind",
                        "Tense": "Pres",
                        "Number": "Sing",
                        "Person": "1",
                    },
                    analysis_rank=1,
                    confidence=1.0,
                )
            ]

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "omorfi.analyse.hfst"
            input_path.write_text("fake hfst model")

            with patch(
                "open_finnish_lexicon.sources.omorfi_stage.analyse_omorfi_model_rows",
                fake_analyse_omorfi_model_rows,
            ):
                exit_code = main(["ingest-omorfi", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("zorblaan", captured_tokens)
        self.assertIn("nopeasti", captured_tokens)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zorbla' and part_of_speech = 'verb'"
            ).fetchone()
            self.assertIsNotNone(lexeme)

            forms = conn.execute(
                """
                select surface_form
                from lexicon.form
                where normalized_form = 'zorblaan'
                order by surface_form
                """
            ).fetchall()
            self.assertEqual([row[0] for row in forms], ["zorblaan"])

            analyses = conn.execute(
                """
                select normalized_query, confidence
                from lexicon.form_analysis
                where normalized_query = 'zorblaan'
                """
            ).fetchall()
            source_kind = conn.execute(
                "select source_kind from warehouse.source_registry where name = 'omorfi'"
            ).fetchone()[0]

        self.assertEqual(len(analyses), 1)
        self.assertAlmostEqual(float(analyses[0][1]), 1.0, places=5)
        self.assertEqual(source_kind, "hfst")
